#!/usr/bin/env python3
"""UDP hole-punch rendezvous server for two or more clients."""

from __future__ import annotations

import argparse
import socket
import sys
import time
from typing import Dict, Tuple

DEFAULT_BIND = "0.0.0.0"
DEFAULT_PORT = 9999
DEFAULT_TIMEOUT = 30.0

ClientEntry = Tuple[str, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UDP server that tracks client keep-alives and broadcasts peer lists."
    )
    parser.add_argument("--bind", default=DEFAULT_BIND, help="Address to bind the server to.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP port to listen on.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Seconds before a client is removed after its last keep-alive.",
    )
    return parser.parse_args()


def normalize_message(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    return text.replace("\n", " ").strip()


def build_broadcast(
    clients: Dict[Tuple[str, int], ClientEntry], exclude: Tuple[str, int] | None = None
) -> bytes:
    lines = []
    for (ip, port), (message, _) in clients.items():
        if exclude is not None and (ip, port) == exclude:
            continue
        safe_message = message.replace("\n", " ") if message else ""
        lines.append(f"{ip} {port} {safe_message}")
    payload = "\n".join(lines)
    return payload.encode("utf-8")


def prune_clients(clients: Dict[Tuple[str, int], ClientEntry], timeout: float) -> None:
    now = time.time()
    stale = [addr for addr, (_, last_seen) in clients.items() if now - last_seen > timeout]
    for addr in stale:
        del clients[addr]


def main() -> None:
    args = parse_args()
    clients: Dict[Tuple[str, int], ClientEntry] = {}

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.bind((args.bind, args.port))
        except OSError as exc:
            print(f"Failed to bind server socket: {exc}", file=sys.stderr)
            sys.exit(1)

        print(f"Holepunch server listening on {sock.getsockname()[0]}:{sock.getsockname()[1]}")

        while True:
            try:
                data, addr = sock.recvfrom(4096)
            except KeyboardInterrupt:
                print("Server exiting.")
                break
            except OSError:
                continue

            message = normalize_message(data)
            now = time.time()
            clients[addr] = (message, now)
            print(f"Received keep-alive from {addr[0]}:{addr[1]} -> '{message}'")

            prune_clients(clients, args.timeout)

            if not clients:
                continue

            destinations = list(clients.keys())
            for peer in destinations:
                try:
                    payload = build_broadcast(clients, peer)
                    sock.sendto(payload, peer)
                except OSError as exc:
                    print(f"Failed to send peer list to {peer[0]}:{peer[1]} ({exc})", file=sys.stderr)

            print(f"Broadcasted list ({len(destinations)} peers)")


if __name__ == "__main__":
    main()
