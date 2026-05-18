#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any


# Clientul este doar un script care se conectează
# la proxy, trimite cereri JSON și afișează răspunsurile primite.
#
# Variabilele pot fi suprascrise din environment, dar au valori default potrivite
# pentru rularea locală:
#
#   proxy host: 127.0.0.1
#   proxy port: 9000
#
# În Docker Compose, proxy-ul expune portul 9000 către host, deci clientul
# local se poate conecta tot la 127.0.0.1:9000.


PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_PORT", "9000"))

# Timeout-ul protejează clientul de situații în care proxy-ul nu răspunde.
# Fără timeout, clientul ar putea rămâne blocat așteptând la infinit.
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))


# UTILITARE


def pretty_json(data: dict[str, Any]) -> str:
    """Transformă un dicționar Python în JSON frumos indentat pentru afișare."""

    return json.dumps(data, ensure_ascii=False, indent=2)


def build_request(
    target: str,
    operation: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construiește mesajul standard Client -> Proxy.

    Toate cererile clientului au forma:

    {
        "type": "REQUEST",
        "target": "proxy" sau "destination",
        "operation": "...",
        "payload": {...}
    }

    Clientul nu trimite request_id, este generat de proxy.
    """

    return {
        "type": "REQUEST",
        "target": target,
        "operation": operation,
        "payload": payload or {},
    }


# Functia centrala a clientului.
#
# Aceasta:
#   1. se conectează la proxy prin TCP
#   2. trimite un mesaj JSON terminat cu newline
#   3. citește o linie de răspuns de la proxy
#   4. parsează răspunsul ca JSON
#   5. afișează răspunsul
#   6. închide conexiunea
#
# Protocolul este "JSON line-delimited":
#   - un mesaj = un JSON pe o singură linie
#   - finalul mesajului = caracterul "\n"


async def send_request(
    client_name: str,
    request: dict[str, Any],
    host: str | None = None,
    port: int | None = None,
) -> dict[str, Any]:
    # Dacă funcția nu primește explicit host/port, folosește valorile globale.
    #
    # E important crearea fallback-urilor aici, în runtime, nu în semnătura funcției,
    # ca opțiunile --host și --port din argparse să funcționeze corect.
    if host is None:
        host = PROXY_HOST

    if port is None:
        port = PROXY_PORT

    print(f"\n[{client_name}] Connecting to proxy at {host}:{port}")
    print(f"[{client_name}] Sending request:")
    print(pretty_json(request))

    try:
        # Deschidem conexiunea TCP către proxy.
        #
        # asyncio.open_connection(...) întoarce:
        #   reader -> pentru citire din socket
        #   writer -> pentru scriere în socket
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=REQUEST_TIMEOUT,
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise ConnectionError(f"Could not connect to proxy at {host}:{port}") from exc

    try:
        # Serializăm cererea ca JSON compact și adăugăm \n.
        line = json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"

        # Trimitem bytes prin socket.
        writer.write(line.encode("utf-8"))
        await writer.drain()

        # Citim răspunsul proxy-ului.
        #
        # Pentru că protocolul folosește newline ca separator, readline()
        # știe unde se termină un mesaj.
        response_line = await asyncio.wait_for(
            reader.readline(),
            timeout=REQUEST_TIMEOUT,
        )

        if not response_line:
            raise ConnectionError("Proxy closed the connection without a response")

        # Transformăm bytes -> string -> obiect JSON.
        response = json.loads(response_line.decode("utf-8"))

        if not isinstance(response, dict):
            raise ValueError("Proxy response is not a JSON object")

        print(f"[{client_name}] Received response:")
        print(pretty_json(response))

        return response

    finally:
        # Închidem conexiunea după fiecare cerere.
        #
        # Aici, o cerere = o conexiune.
        writer.close()
        await writer.wait_closed()


# Fiecare funcție de mai jos demonstrează o cerință importantă a proiectului.
#
# Pot fi rulate toate odată:
#
#   python3 client/demo_client.py full
#
# sau individual:
#
#   python3 client/demo_client.py ping
#   python3 client/demo_client.py out-of-order
#   etc.


async def demo_proxy_ping() -> None:
    """Demonstrează o cerere adresată direct proxy-ului."""

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
    """Demonstrează cereri care trec prin proxy către destination server."""

    print("\n" + "=" * 80)
    print("DEMO 2: cereri forwardate către destination server")
    print("=" * 80)

    # Cerere echo:
    # Client -> Proxy -> Destination -> Proxy -> Client
    await send_request(
        "Client A",
        build_request(
            target="destination",
            operation="echo",
            payload={"text": "salut de la client"},
        ),
    )

    # Cerere uppercase:
    # Destination va transforma textul în litere mari.
    await send_request(
        "Client A",
        build_request(
            target="destination",
            operation="uppercase",
            payload={"text": "salut de la client"},
        ),
    )


async def demo_out_of_order() -> None:
    """Demonstrează doi clienți logici și răspunsuri out-of-order.

    Ideea:
      - Client A trimite primul o cerere lentă.
      - Client B trimite al doilea o cerere rapidă.
      - Răspunsul lui B vine primul.
      - Proxy-ul totuși livrează fiecare răspuns clientului corect datorită
        request_id-ului.
    """

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

    # Pornim cererea lentă prima.
    #
    # create_task(...) permite rularea concurentă: nu așteptăm să termine
    # slow_task înainte să pornim fast_task.
    slow_task = asyncio.create_task(send_request("Client A", slow_request))

    # Mic delay artificial ca să fie clar că cererea lentă a fost trimisă prima.
    await asyncio.sleep(0.2)

    # Pornim cererea rapidă după cererea lentă.
    fast_task = asyncio.create_task(send_request("Client B", fast_request))

    responses = []

    # asyncio.as_completed(...) ne dă task-urile în ordinea în care se termină,
    # nu în ordinea în care au fost pornite.
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
    """Demonstrează operația directă proxy_read_file."""

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
    """Demonstrează tratarea controlată a unui target invalid."""

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
    """Demonstrează cazul în care destination server este oprit."""

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
    """Rulează scenariul principal de demo.

    Nu include automat testul destination unavailable, pentru că acela cere
    oprirea manuală a containerului destination.
    """

    await demo_proxy_ping()
    await demo_destination_operations()
    await demo_out_of_order()
    await demo_proxy_read_file()
    await demo_invalid_target()

    print("\n" + "=" * 80)
    print("Demo principal terminat.")
    print("=" * 80)
    print("Pentru testul de destination indisponibil:")
    print("1. Proxy pornit.")
    print("2. docker compose stop destination")
    print("3. python3 client/demo_client.py unavailable")
    print("4. docker compose start destination")


# Punctul de intrare al scriptului.


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

    # Actualizăm valorile globale ca toate funcțiile demo să folosească
    # host/port-ul primit din CLI.
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
