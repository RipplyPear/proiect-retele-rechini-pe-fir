#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any


# Destination server este serverul final care procesează cererile forwardate
# de proxy.
#
# El nu primește mesaje direct de la clientul demo în fluxul normal.
# Fluxul normal este:
#
#   Client -> Proxy -> Destination -> Proxy -> Client
#
# În Docker, destination ascultă pe 0.0.0.0:9101 ca să fie accesibil din
# containerul proxy.


DESTINATION_HOST = os.getenv("DESTINATION_HOST", "0.0.0.0")
DESTINATION_PORT = int(os.getenv("DESTINATION_PORT", "9101"))

# Operațiile pe care destination server știe să le execute.
ALLOWED_OPERATIONS = {"echo", "uppercase", "delay_echo"}


# Logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("destination")


# Destination răspunde proxy-ului cu mesaje de forma:
#
# {
#   "type": "DESTINATION_RESPONSE",
#   "request_id": "...",
#   "status": "ok",
#   "data": {...}
# }
#
# sau:
#
# {
#   "type": "DESTINATION_RESPONSE",
#   "request_id": "...",
#   "status": "error",
#   "error": {"code": "...", "message": "..."}
# }
#
# Foarte important:
#   request_id-ul primit de la proxy trebuie păstrat în răspuns.
#
# Altfel proxy-ul nu ar putea corela răspunsul cu clientul corect.


def make_destination_response(
    request_id: str | None,
    status: str,
    data: dict[str, Any] | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "type": "DESTINATION_RESPONSE",
        "request_id": request_id,
        "status": status,
    }

    if status == "ok":
        response["data"] = data or {}
    else:
        response["error"] = error or {
            "code": "UNKNOWN_ERROR",
            "message": "Unknown error",
        }

    return response


def make_error(
    request_id: str | None,
    code: str,
    message: str,
) -> dict[str, Any]:
    """Scurtătură pentru construirea unui răspuns de eroare."""

    return make_destination_response(
        request_id=request_id,
        status="error",
        error={
            "code": code,
            "message": message,
        },
    )


# Protocolul este JSON line-delimited:
#   - fiecare mesaj este un obiect JSON
#   - fiecare mesaj se termină cu "\n"
#
# Destination primește de la proxy un mesaj de tip:
#
# {
#   "type": "FORWARDED_REQUEST",
#   "request_id": "...",
#   "operation": "...",
#   "payload": {...}
# }


def parse_json_line(line: bytes) -> dict[str, Any]:
    """Transformă o linie de bytes primită pe socket într-un dicționar."""

    try:
        decoded = line.decode("utf-8").strip()
        message = json.loads(decoded)
    except UnicodeDecodeError as exc:
        raise ValueError("Message is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Message is not valid JSON") from exc

    if not isinstance(message, dict):
        raise ValueError("Message must be a JSON object")

    return message


def validate_forwarded_request(
    message: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Verifică forma mesajului Proxy -> Destination.

    Returnează valorile importante:
      request_id, operation, payload
    """

    if message.get("type") != "FORWARDED_REQUEST":
        raise ValueError("Field 'type' must be 'FORWARDED_REQUEST'")

    request_id = message.get("request_id")
    operation = message.get("operation")
    payload = message.get("payload", {})

    if not isinstance(request_id, str) or not request_id:
        raise ValueError("Field 'request_id' must be a non-empty string")

    if not isinstance(operation, str) or not operation:
        raise ValueError("Field 'operation' must be a non-empty string")

    if payload is None:
        payload = {}

    if not isinstance(payload, dict):
        raise ValueError("Field 'payload' must be an object")

    return request_id, operation, payload


# Această funcție conține logica efectivă a serverului destination.
#
# Operații:
#   echo       -> returnează textul primit
#   uppercase  -> returnează textul cu litere mari
#   delay_echo -> așteaptă delay_ms, apoi returnează textul
#
# delay_echo este important pentru demo-ul de out-of-order:
#   - o cerere lentă poate răspunde după o cerere rapidă trimisă ulterior.


async def execute_operation(
    request_id: str,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if operation not in ALLOWED_OPERATIONS:
        return make_error(
            request_id,
            "UNKNOWN_OPERATION",
            f"Destination operation '{operation}' is not supported",
        )

    if operation == "echo":
        text = payload.get("text", "")
        return make_destination_response(
            request_id,
            "ok",
            {
                "text": str(text),
            },
        )

    if operation == "uppercase":
        text = payload.get("text", "")
        return make_destination_response(
            request_id,
            "ok",
            {
                "text": str(text).upper(),
            },
        )

    if operation == "delay_echo":
        text = payload.get("text", "")
        delay_ms = payload.get("delay_ms", 0)

        # delay_ms trebuie să fie număr pozitiv sau zero.
        if not isinstance(delay_ms, int | float) or delay_ms < 0:
            return make_error(
                request_id,
                "INVALID_REQUEST",
                "delay_echo requires payload.delay_ms to be a non-negative number",
            )

        # Aici apare întârzierea artificială.
        #
        # await asyncio.sleep(...) nu blochează întreg serverul.
        # Cât timp această cerere doarme, event loop-ul poate procesa alte cereri.
        await asyncio.sleep(delay_ms / 1000)

        return make_destination_response(
            request_id,
            "ok",
            {
                "text": str(text),
                "delay_ms": delay_ms,
            },
        )

    # Teoretic nu ajungem aici din cauza verificării ALLOWED_OPERATIONS,
    # dar păstrăm fallback-ul pentru siguranță.
    return make_error(
        request_id,
        "UNKNOWN_OPERATION",
        f"Destination operation '{operation}' is not supported",
    )


async def send_json(
    writer: asyncio.StreamWriter,
    message: dict[str, Any],
) -> None:
    """Trimite un dicționar ca JSON line-delimited."""

    line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    writer.write(line.encode("utf-8"))
    await writer.drain()


# În implementarea curentă, proxy-ul deschide o conexiune nouă către destination
# pentru fiecare cerere. Destination citește o linie, procesează cererea,
# trimite un răspuns și închide conexiunea.


async def handle_proxy_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer_info = writer.get_extra_info("peername")
    peer = str(peer_info)

    logger.info("Proxy connected: %s", peer)

    try:
        # Citim o singură cerere JSON.
        line = await reader.readline()

        if not line:
            return

        try:
            message = parse_json_line(line)
            request_id, operation, payload = validate_forwarded_request(message)
        except ValueError as exc:
            # Dacă mesajul primit de la proxy este invalid, răspundem controlat.
            #
            # Nu avem request_id valid, deci trimitem request_id = None.
            await send_json(
                writer,
                make_error(
                    None,
                    "INVALID_REQUEST",
                    str(exc),
                ),
            )
            return

        logger.info(
            "Received request_id=%s operation=%s from=%s",
            request_id,
            operation,
            peer,
        )

        response = await execute_operation(request_id, operation, payload)
        await send_json(writer, response)

        logger.info(
            "Sent response for request_id=%s status=%s",
            request_id,
            response.get("status"),
        )

    except ConnectionError:
        logger.info("Connection error from proxy: %s", peer)

    finally:
        writer.close()
        await writer.wait_closed()
        logger.info("Proxy disconnected: %s", peer)


async def main() -> None:
    # asyncio.start_server pornește un server TCP.
    #
    # Pentru fiecare conexiune nouă, va apela handle_proxy_connection.
    server = await asyncio.start_server(
        handle_proxy_connection,
        DESTINATION_HOST,
        DESTINATION_PORT,
    )

    addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])

    logger.info("Destination server started on %s", addresses)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Destination server stopped")
