#!/usr/bin/env python3
"""Multi-port UDP echo server for NAT type detection.

Listens on several ports and replies to each datagram with a string
describing the source endpoint (ip:port) as seen from the server.
Comparing the source port seen across different destination ports
reveals whether the NAT uses endpoint-independent mapping (cone)
or endpoint-dependent mapping (symmetric / CGNAT).
"""

from __future__ import annotations

import socket
import threading

PORTS = [9997, 9998, 9999]


def serve(port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    print(f"[echo] listening on :{port}", flush=True)
    while True:
        data, addr = sock.recvfrom(4096)
        reply = f"via {port} -> {addr[0]}:{addr[1]}".encode()
        sock.sendto(reply, addr)


def main() -> None:
    for p in PORTS:
        threading.Thread(target=serve, args=(p,), daemon=True).start()
    threading.Event().wait()


if __name__ == "__main__":
    main()
