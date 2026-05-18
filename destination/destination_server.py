#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any


DESTINATION_HOST = os.getenv("DESTINATION_HOST", "0.0.0.0")
DESTINATION_PORT = int(os.getenv("DESTINATION_PORT", "9101"))

ALLOWED_OPERATIONS = {"echo", "uppercase", "delay_echo"}

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("destination")


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
    return make_destination_response(
        request_id=request_id,
        status="error",
        error={
            "code": code,
            "message": message,
        },
    )


def parse_json_line(line: bytes) -> dict[str, Any]:
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

        if not isinstance(delay_ms, int | float) or delay_ms < 0:
            return make_error(
                request_id,
                "INVALID_REQUEST",
                "delay_echo requires payload.delay_ms to be a non-negative number",
            )

        await asyncio.sleep(delay_ms / 1000)

        return make_destination_response(
            request_id,
            "ok",
            {
                "text": str(text),
                "delay_ms": delay_ms,
            },
        )

    return make_error(
        request_id,
        "UNKNOWN_OPERATION",
        f"Destination operation '{operation}' is not supported",
    )


async def send_json(
    writer: asyncio.StreamWriter,
    message: dict[str, Any],
) -> None:
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    writer.write(line.encode("utf-8"))
    await writer.drain()


async def handle_proxy_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer_info = writer.get_extra_info("peername")
    peer = str(peer_info)

    logger.info("Proxy connected: %s", peer)

    try:
        line = await reader.readline()

        if not line:
            return

        try:
            message = parse_json_line(line)
            request_id, operation, payload = validate_forwarded_request(message)
        except ValueError as exc:
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
