#!/usr/bin/env python3
"""Client that keeps a hole-punching connection active via a central server."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
from typing import Tuple

DEFAULT_INTERVAL = 5.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UDP hole-punch client.")
    parser.add_argument("--server", required=True, help="Server address (host:port) to report to.")
    parser.add_argument(
        "--message",
        help="Short UTF-8 message payload that peers should see.",
        default=f"{socket.gethostname()}:{os.getpid()}",
    )
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="Seconds between keep-alive messages.")
    return parser.parse_args()


def resolve_server(target: str) -> Tuple[str, int]:
    if ":" not in target:
        raise ValueError("Server address must include host and port separated by ':'")
    host, port_str = target.rsplit(":", 1)
    port = int(port_str)
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    if not infos:
        raise ValueError(f"Failed to resolve server address {host}:{port}")
    return infos[0][4]


def punch_peers(sock: socket.socket, payload: bytes, broadcast: str, server_addr: Tuple[str, int]) -> None:
    for line in broadcast.splitlines():
        entry = line.strip()
        if not entry:
            continue

        parts = entry.split(None, 2)
        if len(parts) < 2:
            continue

        peer_ip = parts[0]
        try:
            peer_port = int(parts[1])
        except ValueError:
            continue

        peer_addr = (peer_ip, peer_port)
        if peer_addr == server_addr:
            continue

        try:
            sock.sendto(payload, peer_addr)
            print(f"Sent to {peer_ip}:{peer_port}")
        except OSError as exc:
            print(f"Failed to punch {peer_ip}:{peer_port} ({exc})", file=sys.stderr)


def listen(sock: socket.socket, server_addr: Tuple[str, int], payload: bytes, stop_event: threading.Event) -> None:
    sock.settimeout(0.5)
    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            break

        if addr == server_addr:
            broadcast = data.decode("utf-8", errors="replace")
            punch_peers(sock, payload, broadcast, server_addr)
        else:
            message = data.decode("utf-8", errors="replace")
            print(f"Received {len(data)} bytes from {addr[0]}:{addr[1]} -> {message}")


def main() -> None:
    args = parse_args()
    server_addr = resolve_server(args.server)
    payload = args.message.encode("utf-8")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", 0))
        local_addr = sock.getsockname()
        print(f"Client listening on {local_addr[0]}:{local_addr[1]}, server at {server_addr[0]}:{server_addr[1]}")

        stop_event = threading.Event()
        listener = threading.Thread(
            target=listen, args=(sock, server_addr, payload, stop_event), daemon=True
        )
        listener.start()

        try:
            while not stop_event.is_set():
                sock.sendto(payload, server_addr)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("Shutting down client.")
        finally:
            stop_event.set()
            listener.join()


if __name__ == "__main__":
    main()
