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
DEFAULT_BROADCAST_INTERVAL = 3.0

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
    parser.add_argument(
        "--broadcast-interval",
        type=float,
        default=DEFAULT_BROADCAST_INTERVAL,
        help="Seconds between peer-list broadcasts. Keep-alives are accepted silently between broadcasts.",
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
        print(f"Broadcasting peer list every {args.broadcast_interval:.1f}s; "
              f"pruning clients idle > {args.timeout:.0f}s")

        sock.settimeout(0.5)
        last_broadcast = 0.0

        while True:
            now = time.time()
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                pass
            except KeyboardInterrupt:
                print("Server exiting.")
                break
            except OSError:
                continue
            else:
                message = normalize_message(data)
                is_new = addr not in clients
                clients[addr] = (message, now)
                if is_new:
                    print(f"New client {addr[0]}:{addr[1]} -> '{message}'")

            prune_clients(clients, args.timeout)

            if clients and now - last_broadcast >= args.broadcast_interval:
                destinations = list(clients.keys())
                for peer in destinations:
                    try:
                        payload = build_broadcast(clients, peer)
                        sock.sendto(payload, peer)
                    except OSError as exc:
                        print(f"Failed to send peer list to {peer[0]}:{peer[1]} ({exc})", file=sys.stderr)
                last_broadcast = now
                print(f"Broadcasted list ({len(destinations)} peers)")


if __name__ == "__main__":
    main()
