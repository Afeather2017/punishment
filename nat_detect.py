#!/usr/bin/env python3
"""NAT mapping behavior detector.

Sends UDP packets from one fixed local socket to several destinations
on a public server and compares the source port each destination
sees. Same port across destinations = endpoint-independent mapping
(cone NAT); different ports = endpoint-dependent mapping (symmetric
NAT / CGNAT).
"""

from __future__ import annotations

import argparse
import re
import socket
import time

LOCAL_PORT = 54321
TIMEOUT = 5.0


def main() -> None:
    parser = argparse.ArgumentParser(description="NAT mapping behavior detector")
    parser.add_argument("server", help="Server IP address")
    args = parser.parse_args()

    server = args.server
    targets = [(server, p) for p in (9997, 9998, 9999)]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", LOCAL_PORT))
    sock.settimeout(0.5)

    print(f"Local socket bound on 0.0.0.0:{LOCAL_PORT}")
    print(f"Sending to {len(targets)} destinations on {server}\n")

    for target in targets:
        sock.sendto(b"probe", target)

    seen: dict[tuple[str, int], str] = {}
    deadline = time.time() + TIMEOUT
    while time.time() < deadline and len(seen) < len(targets):
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        seen[addr] = data.decode("utf-8", errors="replace")

    if not seen:
        print("=> No responses. UDP may be blocked or server unreachable.")
        return

    for addr, text in sorted(seen.items()):
        print(f"  {text}")

    ports: list[int] = []
    for text in seen.values():
        m = re.search(r":(\d+)$", text)
        if m:
            ports.append(int(m.group(1)))

    if len(ports) < len(targets):
        missing = len(targets) - len(ports)
        print(f"\nOnly {len(ports)}/{len(targets)} responses received ({missing} lost)")

    print()
    if len(set(ports)) <= 1:
        print(f"=> Same source port across destinations: {ports}")
        print("=> Endpoint-INDEPENDENT mapping -> Cone NAT, hole punching viable")
    else:
        print(f"=> Source port differs per destination: {ports}")
        print("=> Endpoint-DEPENDENT mapping -> Symmetric NAT / CGNAT")
        print("=> Pure UDP hole punching will fail; relay (TURN/frp/etc.) required")


if __name__ == "__main__":
    main()
