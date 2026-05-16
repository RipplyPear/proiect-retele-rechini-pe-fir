#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROXY_HOST = os.getenv("PROXY_HOST", "0.0.0.0")
PROXY_PORT = int(os.getenv("PROXY_PORT", "9000"))

DESTINATION_HOST = os.getenv("DESTINATION_HOST", "127.0.0.1")
DESTINATION_PORT = int(os.getenv("DESTINATION_PORT", "9101"))
DESTINATION_TIMEOUT = float(os.getenv("DESTINATION_TIMEOUT", "5"))

PROXY_DATA_DIR = Path(os.getenv("PROXY_DATA_DIR", "proxy_data/public")).resolve()

ALLOWED_PROXY_OPERATIONS = {"proxy_ping", "proxy_read_file"}
ALLOWED_DESTINATION_OPERATIONS = {"echo", "uppercase", "delay_echo"}

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("proxy")

pending_requests: dict[str, "ClientConnection"] = {}


@dataclass(slots=True)
class ClientConnection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    peer: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False


def make_response(
    request_id: str | None,
    status: str,
    data: dict[str, Any] | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "type": "RESPONSE",
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
    return make_response(
        request_id=request_id,
        status="error",
        error={
            "code": code,
            "message": message,
        },
    )


async def send_json(client: ClientConnection, message: dict[str, Any]) -> None:
    if client.closed or client.writer.is_closing():
        raise ConnectionError("Client connection is already closed")

    line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"

    async with client.lock:
        client.writer.write(line.encode("utf-8"))
        await client.writer.drain()


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


def validate_client_request(message: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if message.get("type") != "REQUEST":
        raise ValueError("Field 'type' must be 'REQUEST'")

    target = message.get("target")
    operation = message.get("operation")
    payload = message.get("payload", {})

    if not isinstance(target, str) or not target:
        raise ValueError("Field 'target' must be a non-empty string")

    if not isinstance(operation, str) or not operation:
        raise ValueError("Field 'operation' must be a non-empty string")

    if payload is None:
        payload = {}

    if not isinstance(payload, dict):
        raise ValueError("Field 'payload' must be an object")

    return target, operation, payload


async def handle_proxy_operation(
    client: ClientConnection,
    request_id: str,
    operation: str,
    payload: dict[str, Any],
) -> None:
    if operation not in ALLOWED_PROXY_OPERATIONS:
        await send_json(
            client,
            make_error(
                request_id,
                "UNKNOWN_OPERATION",
                f"Proxy operation '{operation}' is not supported",
            ),
        )
        return

    if operation == "proxy_ping":
        await send_json(
            client,
            make_response(
                request_id,
                "ok",
                {
                    "message": "pong",
                    "proxy": "alive",
                },
            ),
        )
        return

    if operation == "proxy_read_file":
        filename = payload.get("filename") or payload.get("path")

        if not isinstance(filename, str) or not filename:
            await send_json(
                client,
                make_error(
                    request_id,
                    "INVALID_REQUEST",
                    "proxy_read_file requires payload.filename",
                ),
            )
            return

        requested_path = (PROXY_DATA_DIR / filename).resolve()

        try:
            requested_path.relative_to(PROXY_DATA_DIR)
        except ValueError:
            await send_json(
                client,
                make_error(
                    request_id,
                    "INVALID_REQUEST",
                    "File path escapes the exposed proxy directory",
                ),
            )
            return

        if not requested_path.is_file():
            await send_json(
                client,
                make_error(
                    request_id,
                    "INVALID_REQUEST",
                    f"File '{filename}' does not exist in proxy data directory",
                ),
            )
            return

        try:
            content = requested_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            await send_json(
                client,
                make_error(
                    request_id,
                    "INVALID_REQUEST",
                    f"File '{filename}' is not a valid UTF-8 text file",
                ),
            )
            return

        await send_json(
            client,
            make_response(
                request_id,
                "ok",
                {
                    "filename": filename,
                    "content": content,
                },
            ),
        )


async def call_destination_server(
    forwarded_request: dict[str, Any],
) -> dict[str, Any]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(DESTINATION_HOST, DESTINATION_PORT),
            timeout=DESTINATION_TIMEOUT,
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise ConnectionError("Destination server unavailable") from exc

    try:
        line = (
            json.dumps(forwarded_request, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        )

        writer.write(line.encode("utf-8"))
        await writer.drain()

        response_line = await asyncio.wait_for(
            reader.readline(),
            timeout=DESTINATION_TIMEOUT,
        )

        if not response_line:
            raise ValueError(
                "Destination server closed the connection without response"
            )

        return parse_json_line(response_line)

    finally:
        writer.close()
        await writer.wait_closed()


async def forward_to_destination(
    client: ClientConnection,
    request_id: str,
    operation: str,
    payload: dict[str, Any],
) -> None:
    if operation not in ALLOWED_DESTINATION_OPERATIONS:
        await send_json(
            client,
            make_error(
                request_id,
                "UNKNOWN_OPERATION",
                f"Destination operation '{operation}' is not supported",
            ),
        )
        return

    pending_requests[request_id] = client

    forwarded_request = {
        "type": "FORWARDED_REQUEST",
        "request_id": request_id,
        "operation": operation,
        "payload": payload,
    }

    try:
        destination_response = await call_destination_server(forwarded_request)

        if destination_response.get("type") != "DESTINATION_RESPONSE":
            await send_json(
                client,
                make_error(
                    request_id,
                    "INVALID_RESPONSE_ID",
                    "Destination response has invalid type",
                ),
            )
            return

        if destination_response.get("request_id") != request_id:
            await send_json(
                client,
                make_error(
                    request_id,
                    "INVALID_RESPONSE_ID",
                    "Destination response has missing or mismatched request_id",
                ),
            )
            return

        mapped_client = pending_requests.get(request_id)

        if mapped_client is None or mapped_client.closed:
            logger.warning(
                "Client disconnected before response for request_id=%s", request_id
            )
            return

        status = destination_response.get("status", "ok")

        if status == "ok":
            await send_json(
                mapped_client,
                make_response(
                    request_id,
                    "ok",
                    destination_response.get("data", {}),
                ),
            )
        else:
            await send_json(
                mapped_client,
                make_response(
                    request_id,
                    "error",
                    error=destination_response.get(
                        "error",
                        {
                            "code": "UNKNOWN_ERROR",
                            "message": "Destination returned an unknown error",
                        },
                    ),
                ),
            )

    except (ConnectionError, OSError, asyncio.TimeoutError):
        if not client.closed:
            await send_json(
                client,
                make_error(
                    request_id,
                    "DESTINATION_UNAVAILABLE",
                    "Server destination unavailable",
                ),
            )

    except ValueError as exc:
        if not client.closed:
            await send_json(
                client,
                make_error(
                    request_id,
                    "INVALID_RESPONSE_ID",
                    str(exc),
                ),
            )

    finally:
        pending_requests.pop(request_id, None)


async def handle_client_message(client: ClientConnection, line: bytes) -> None:
    try:
        message = parse_json_line(line)
        target, operation, payload = validate_client_request(message)
    except ValueError as exc:
        await send_json(
            client,
            make_error(
                None,
                "INVALID_REQUEST",
                str(exc),
            ),
        )
        return

    request_id = str(uuid.uuid4())

    logger.info(
        "Received request_id=%s from=%s target=%s operation=%s",
        request_id,
        client.peer,
        target,
        operation,
    )

    if target == "proxy":
        await handle_proxy_operation(client, request_id, operation, payload)
        return

    if target == "destination":
        await forward_to_destination(client, request_id, operation, payload)
        return

    await send_json(
        client,
        make_error(
            request_id,
            "INVALID_REQUEST",
            f"Target '{target}' is not supported",
        ),
    )


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer_info = writer.get_extra_info("peername")
    peer = str(peer_info)

    client = ClientConnection(
        reader=reader,
        writer=writer,
        peer=peer,
    )

    logger.info("Client connected: %s", peer)

    try:
        while not reader.at_eof():
            line = await reader.readline()

            if not line:
                break

            asyncio.create_task(handle_client_message(client, line))

    except ConnectionError:
        logger.info("Client connection error: %s", peer)

    finally:
        client.closed = True

        for request_id, mapped_client in list(pending_requests.items()):
            if mapped_client is client:
                pending_requests.pop(request_id, None)
                logger.info(
                    "Cleaned pending request_id=%s for disconnected client", request_id
                )

        writer.close()
        await writer.wait_closed()

        logger.info("Client disconnected: %s", peer)


async def main() -> None:
    PROXY_DATA_DIR.mkdir(parents=True, exist_ok=True)

    server = await asyncio.start_server(
        handle_client,
        PROXY_HOST,
        PROXY_PORT,
    )

    addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])

    logger.info("Proxy server started on %s", addresses)
    logger.info("Exposed proxy data directory: %s", PROXY_DATA_DIR)
    logger.info("Destination configured as %s:%s", DESTINATION_HOST, DESTINATION_PORT)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Proxy server stopped")
