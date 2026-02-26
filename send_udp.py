#!/usr/bin/env python3
"""Simple UDP sender that reads targets from stdin.

Each line should contain an IP and port (e.g. "192.168.1.10 9999").
Optionally append a custom message after the port. If no message is
provided, the script sends a default ping payload.
"""

import socket
import sys
import threading


def send_udp(sock: socket.socket, target_ip: str, target_port: int, payload: bytes) -> None:
    """Send a single UDP packet to the provided address via the shared socket."""

    sock.sendto(payload, (target_ip, target_port))


def parse_line(line: str):
    """Parse a line from stdin, returning ip, port, and optional message."""

    if not line:
        return None

    parts = line.strip().split()
    if len(parts) < 2:
        raise ValueError("Each line must have at least IP and port")

    ip = parts[0]
    port = int(parts[1])
    message = " ".join(parts[2:]) if len(parts) > 2 else "udp ping"
    return ip, port, message.encode("utf-8")


def listen_for_responses(sock: socket.socket, stop_event: threading.Event) -> None:
    """Continuously receive packets from the socket and print the peer info."""

    sock.settimeout(0.5)
    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            break

        message = data.decode("utf-8", errors="replace")
        print(f"Received {len(data)} bytes from {addr[0]}:{addr[1]} -> {message}")


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", 0))
        stop_event = threading.Event()
        listener = threading.Thread(
            target=listen_for_responses, args=(sock, stop_event), daemon=True
        )
        listener.start()

        local_addr = sock.getsockname()
        print(
            "Enter IP and port pairs (one per line). Ctrl-D to finish."
            f" Listening on {local_addr[0]}:{local_addr[1]}."
        )

        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            try:
                ip, port, payload = parse_line(raw_line)
            except ValueError as exc:
                print(f"Skipping line: {exc}", file=sys.stderr)
                continue

            try:
                send_udp(sock, ip, port, payload)
                print(f"Sent {len(payload)} bytes to {ip}:{port}")
            except Exception as exc:  # pragma: no cover
                print(f"Failed to send to {ip}:{port} ({exc})", file=sys.stderr)

        stop_event.set()


if __name__ == "__main__":
    main()
