#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any


PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_PORT", "9000"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))


def pretty_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_request(
    target: str,
    operation: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "REQUEST",
        "target": target,
        "operation": operation,
        "payload": payload or {},
    }


async def send_request(
    client_name: str,
    request: dict[str, Any],
    host: str = PROXY_HOST,
    port: int = PROXY_PORT,
) -> dict[str, Any]:
    print(f"\n[{client_name}] Connecting to proxy at {host}:{port}")
    print(f"[{client_name}] Sending request:")
    print(pretty_json(request))

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=REQUEST_TIMEOUT,
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise ConnectionError(f"Could not connect to proxy at {host}:{port}") from exc

    try:
        line = json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"

        writer.write(line.encode("utf-8"))
        await writer.drain()

        response_line = await asyncio.wait_for(
            reader.readline(),
            timeout=REQUEST_TIMEOUT,
        )

        if not response_line:
            raise ConnectionError("Proxy closed the connection without a response")

        response = json.loads(response_line.decode("utf-8"))

        if not isinstance(response, dict):
            raise ValueError("Proxy response is not a JSON object")

        print(f"[{client_name}] Received response:")
        print(pretty_json(response))

        return response

    finally:
        writer.close()
        await writer.wait_closed()


async def demo_proxy_ping() -> None:
    print("\n" + "=" * 80)
    print("DEMO 1: proxy_ping - cerere adresată direct proxy-ului")
    print("=" * 80)

    await send_request(
        "Client A",
        build_request(
            target="proxy",
            operation="proxy_ping",
        ),
    )


async def demo_destination_operations() -> None:
    print("\n" + "=" * 80)
    print("DEMO 2: cereri forwardate către destination server")
    print("=" * 80)

    await send_request(
        "Client A",
        build_request(
            target="destination",
            operation="echo",
            payload={"text": "salut de la client"},
        ),
    )

    await send_request(
        "Client A",
        build_request(
            target="destination",
            operation="uppercase",
            payload={"text": "salut de la client"},
        ),
    )


async def demo_out_of_order() -> None:
    print("\n" + "=" * 80)
    print("DEMO 3: doi clienți logici + răspunsuri out-of-order")
    print("=" * 80)
    print("Client A trimite primul o cerere lentă.")
    print("Client B trimite al doilea o cerere rapidă.")
    print("Rezultatul corect: răspunsul Clientului B ar trebui să apară primul.")

    slow_request = build_request(
        target="destination",
        operation="delay_echo",
        payload={
            "text": "slow request from Client A",
            "delay_ms": 3000,
        },
    )

    fast_request = build_request(
        target="destination",
        operation="delay_echo",
        payload={
            "text": "fast request from Client B",
            "delay_ms": 500,
        },
    )

    slow_task = asyncio.create_task(send_request("Client A", slow_request))

    await asyncio.sleep(0.2)

    fast_task = asyncio.create_task(send_request("Client B", fast_request))

    responses = []

    for task in asyncio.as_completed([slow_task, fast_task]):
        response = await task
        responses.append(response)

    print("\nOrdinea răspunsurilor primite:")
    for index, response in enumerate(responses, start=1):
        request_id = response.get("request_id")
        data = response.get("data", {})
        text = data.get("text")
        delay_ms = data.get("delay_ms")

        print(f"{index}. request_id={request_id}, text={text}, delay_ms={delay_ms}")


async def demo_proxy_read_file() -> None:
    print("\n" + "=" * 80)
    print("DEMO 4: proxy_read_file - cerere adresată direct proxy-ului")
    print("=" * 80)

    await send_request(
        "Client A",
        build_request(
            target="proxy",
            operation="proxy_read_file",
            payload={"filename": "sample.txt"},
        ),
    )


async def demo_invalid_target() -> None:
    print("\n" + "=" * 80)
    print("DEMO 5: target invalid - eroare controlată")
    print("=" * 80)

    await send_request(
        "Client A",
        build_request(
            target="invalid",
            operation="whatever",
            payload={},
        ),
    )


async def demo_destination_unavailable() -> None:
    print("\n" + "=" * 80)
    print("DEMO 6: destination indisponibil")
    print("=" * 80)
    print("Pentru acest test, oprește destination server înainte:")
    print("  docker compose stop destination")
    print("Apoi rulează:")
    print("  python3 client/demo_client.py unavailable")
    print("Răspunsul așteptat: status=error, code=DESTINATION_UNAVAILABLE")

    await send_request(
        "Client A",
        build_request(
            target="destination",
            operation="echo",
            payload={"text": "test destination unavailable"},
        ),
    )


async def run_full_demo() -> None:
    await demo_proxy_ping()
    await demo_destination_operations()
    await demo_out_of_order()
    await demo_proxy_read_file()
    await demo_invalid_target()

    print("\n" + "=" * 80)
    print("Demo principal terminat.")
    print("=" * 80)
    print("Pentru testul de destination indisponibil:")
    print("1. Lasă proxy-ul pornit.")
    print("2. Oprește destination:")
    print("   docker compose stop destination")
    print("3. Rulează:")
    print("   python3 client/demo_client.py unavailable")
    print("4. Repornește destination:")
    print("   docker compose start destination")


async def main() -> None:
    global PROXY_HOST, PROXY_PORT

    parser = argparse.ArgumentParser(
        description="Client demo pentru proiectul Rechini pe fir",
    )

    parser.add_argument(
        "scenario",
        nargs="?",
        default="full",
        choices=[
            "full",
            "ping",
            "destination",
            "out-of-order",
            "read-file",
            "invalid-target",
            "unavailable",
        ],
        help="Scenariul de rulat",
    )

    parser.add_argument(
        "--host",
        default=PROXY_HOST,
        help=f"Host proxy, default: {PROXY_HOST}",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=PROXY_PORT,
        help=f"Port proxy, default: {PROXY_PORT}",
    )

    args = parser.parse_args()

    PROXY_HOST = args.host
    PROXY_PORT = args.port

    try:
        if args.scenario == "full":
            await run_full_demo()
        elif args.scenario == "ping":
            await demo_proxy_ping()
        elif args.scenario == "destination":
            await demo_destination_operations()
        elif args.scenario == "out-of-order":
            await demo_out_of_order()
        elif args.scenario == "read-file":
            await demo_proxy_read_file()
        elif args.scenario == "invalid-target":
            await demo_invalid_target()
        elif args.scenario == "unavailable":
            await demo_destination_unavailable()

    except (
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
        OSError,
        ValueError,
    ) as exc:
        print("\nDemo failed:")
        print(f"  {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    asyncio.run(main())
