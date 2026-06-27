#!/usr/bin/env python3
"""UDP hole-punching client that traverses cone+symmetric NAT pairs.

For topologies where one peer is behind cone NAT (stable public port)
and the other behind symmetric NAT / CGNAT (port changes per
destination). The cone-side `scanner` registers with the rendezvous
server, learns the symmetric peer's public IP, then sprays all 65535
ports on that IP. The symmetric-side `puncher` continuously sends to
the cone side's stable advertised port, keeping its own outbound NAT
mapping alive. When the scanner's spray finally hits the puncher's
real mapped port, the puncher's NAT accepts the packet (source
matches the destination it punched to) and both sides lock on.

Usage:
    # symmetric side (e.g. mobile hotspot / CGNAT)
    python holepunch_scan.py --server HOST:9999 --role puncher

    # cone side (e.g. corporate network)
    python holepunch_scan.py --server HOST:9999 --role scanner

Requires holepunch_server.py running on a public host.
"""

from __future__ import annotations

import argparse
import random
import socket
import threading
import time

DEFAULT_SCAN_RATE = 200.0       # scanner total packets per second
DEFAULT_REPLICATES = 3          # packets sent per port (loss tolerance)
DEFAULT_PUNCH_INTERVAL = 0.5    # puncher keep-alive interval (s)
DEFAULT_KEEPALIVE_INTERVAL = 2.0  # direct-mode NAT keep-alive (s)

MAX_PORT = 65535


class PortBitmap:
    """Tracks which ports in [1, 65535] have been visited, with O(1)
    random selection of unvisited ports. 8 KB bitmap; when nearly full,
    falls back to linear sweep for the tail to avoid random retries.
    """

    def __init__(self) -> None:
        self.bitmap = bytearray(8192)  # 65536 bits
        self.bitmap[0] = 0x01  # mark port 0 as visited (unused)
        self.remaining = MAX_PORT  # ports 1..65535

    def _set(self, port: int) -> None:
        self.bitmap[port >> 3] |= 1 << (port & 7)

    def _is_set(self, port: int) -> bool:
        return bool(self.bitmap[port >> 3] & (1 << (port & 7)))

    def pick(self) -> int | None:
        if self.remaining == 0:
            return None
        if self.remaining > 256:
            for _ in range(32):
                port = random.randint(1, MAX_PORT)
                if not self._is_set(port):
                    self._set(port)
                    self.remaining -= 1
                    return port
        for byte_idx in range(8192):
            b = self.bitmap[byte_idx]
            if b == 0xFF:
                continue
            for bit_idx in range(8):
                if not (b & (1 << bit_idx)):
                    port = (byte_idx << 3) | bit_idx
                    if 1 <= port <= MAX_PORT:
                        self._set(port)
                        self.remaining -= 1
                        return port
        return None

    def reset(self) -> None:
        for i in range(len(self.bitmap)):
            self.bitmap[i] = 0
        self.bitmap[0] = 0x01
        self.remaining = MAX_PORT


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--server", required=True, help="rendezvous server host:port")
    p.add_argument("--role", required=True, choices=["scanner", "puncher"],
                   help="scanner = cone side (sprays all ports); puncher = symmetric side (keeps mapping alive)")
    p.add_argument("--id", default=socket.gethostname(), help="identifier shared with peer")
    p.add_argument("--scan-rate", type=float, default=DEFAULT_SCAN_RATE,
                   help=f"scanner total packets per second (default {DEFAULT_SCAN_RATE})")
    p.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES,
                   help=f"packets per port for loss tolerance (default {DEFAULT_REPLICATES})")
    p.add_argument("--punch-interval", type=float, default=DEFAULT_PUNCH_INTERVAL,
                   help=f"puncher send interval in seconds (default {DEFAULT_PUNCH_INTERVAL})")
    return p.parse_args()


def resolve(target: str) -> tuple[str, int]:
    host, port_str = target.rsplit(":", 1)
    infos = socket.getaddrinfo(host, int(port_str), type=socket.SOCK_DGRAM)
    if not infos:
        raise ValueError(f"cannot resolve {target}")
    return infos[0][4]


def register_and_get_peer(sock: socket.socket, server_addr: tuple[str, int],
                          my_id: str, timeout: float = 30.0) -> tuple[str, int]:
    payload = f"HELLO {my_id}".encode()
    sock.sendto(payload, server_addr)
    deadline = time.time() + timeout
    sock.settimeout(1.0)
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            sock.sendto(payload, server_addr)
            continue
        if addr != server_addr:
            continue
        for line in data.decode("utf-8", errors="replace").splitlines():
            parts = line.split(None, 2)
            if len(parts) < 2:
                continue
            try:
                return parts[0], int(parts[1])
            except ValueError:
                continue
    raise RuntimeError("timed out waiting for peer to register")


def scanner_mode(server_addr: tuple[str, int], my_id: str,
                 scan_rate: float, replicates: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    print(f"[scanner] local {sock.getsockname()[0]}:{sock.getsockname()[1]}")

    peer_ip, peer_advertised = register_and_get_peer(sock, server_addr, my_id)
    print(f"[scanner] peer (symmetric) public IP: {peer_ip}")
    print(f"[scanner] note: peer's advertised port {peer_advertised} is its mapping "
          f"to the server only — not what we need to hit")
    ports_per_sec = scan_rate / replicates if replicates > 0 else scan_rate
    round_seconds = MAX_PORT / ports_per_sec if ports_per_sec > 0 else float("inf")
    print(f"[scanner] spraying {MAX_PORT} ports in random order, {replicates}x per port, "
          f"~{scan_rate:.0f} pps total ({ports_per_sec:.0f} ports/s, "
          f"~{round_seconds/60:.1f} min per round)")

    stop = threading.Event()

    def spray() -> None:
        interval = 1.0 / scan_rate if scan_rate > 0 else 0
        bitmap = PortBitmap()
        total_pkts = 0
        ports_this_round = 0
        while not stop.is_set():
            port = bitmap.pick()
            if port is None:
                print(f"[scanner]   round done ({total_pkts} pkts), starting next round",
                      flush=True)
                bitmap.reset()
                ports_this_round = 0
                continue
            for _ in range(replicates):
                if stop.is_set():
                    return
                try:
                    sock.sendto(b"SCAN", (peer_ip, port))
                    total_pkts += 1
                except OSError:
                    pass
                if interval:
                    time.sleep(interval)
            ports_this_round += 1
            if ports_this_round % 2000 == 0:
                print(f"[scanner]   scanned {ports_this_round} ports "
                      f"({total_pkts} pkts)", flush=True)

    threading.Thread(target=spray, daemon=True).start()

    sock.settimeout(0.5)
    discovered_port: int | None = None
    while discovered_port is None:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            sock.sendto(f"HELLO {my_id}".encode(), server_addr)
            continue
        if addr[0] == peer_ip:
            discovered_port = addr[1]
    stop.set()

    print(f"\n[scanner] *** discovered real peer port: {discovered_port} ***\n")
    direct_loop(sock, peer_ip, discovered_port, "scanner")


def puncher_mode(server_addr: tuple[str, int], my_id: str,
                 punch_interval: float) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    print(f"[puncher] local {sock.getsockname()[0]}:{sock.getsockname()[1]}")

    peer_ip, peer_port = register_and_get_peer(sock, server_addr, my_id)
    print(f"[puncher] peer (cone) at {peer_ip}:{peer_port} (stable)")
    print(f"[puncher] punching every {punch_interval:.2f}s to keep NAT mapping alive...")

    stop = threading.Event()

    def punch() -> None:
        while not stop.is_set():
            try:
                sock.sendto(b"PUNCH", (peer_ip, peer_port))
            except OSError:
                pass
            time.sleep(punch_interval)

    threading.Thread(target=punch, daemon=True).start()

    sock.settimeout(0.5)
    found = False
    while not found:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            sock.sendto(f"HELLO {my_id}".encode(), server_addr)
            continue
        if addr[0] == peer_ip:
            found = True
    stop.set()

    print(f"\n[puncher] *** scanner found us ***\n")
    direct_loop(sock, peer_ip, peer_port, "puncher")


def direct_loop(sock: socket.socket, peer_ip: str, peer_port: int,
                role: str) -> None:
    print(f"[{role}] direct channel established with {peer_ip}:{peer_port}")
    print(f"[{role}] keep-alive mode — channel stays open. Type to send, Ctrl-C to exit\n")

    stop = threading.Event()
    stats = {"sent": 0, "recv": 0, "last_recv": None, "started": time.time()}

    def keepalive() -> None:
        while not stop.is_set():
            try:
                sock.sendto(b"PING", (peer_ip, peer_port))
                stats["sent"] += 1
            except OSError:
                pass
            time.sleep(DEFAULT_KEEPALIVE_INTERVAL)

    def listener() -> None:
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if addr[0] != peer_ip:
                continue
            text = data.decode("utf-8", errors="replace")
            stats["recv"] += 1
            stats["last_recv"] = time.time()
            if text == "PING":
                try:
                    sock.sendto(b"PONG", (peer_ip, peer_port))
                except OSError:
                    pass
                continue
            if text in ("PONG", "PUNCH", "SCAN"):
                continue
            print(f"\r[peer] {text}\n> ", end="", flush=True)

    def stats_printer() -> None:
        while not stop.is_set():
            time.sleep(15)
            uptime = int(time.time() - stats["started"])
            if stats["last_recv"]:
                ago = f"{int(time.time() - stats['last_recv'])}s ago"
            else:
                ago = "never"
            print(f"[{role}] alive {uptime}s | sent {stats['sent']} | "
                  f"recv {stats['recv']} | last recv {ago}", flush=True)

    sock.settimeout(0.5)
    threading.Thread(target=keepalive, daemon=True).start()
    threading.Thread(target=listener, daemon=True).start()
    threading.Thread(target=stats_printer, daemon=True).start()

    try:
        while not stop.is_set():
            msg = input("> ")
            if msg:
                sock.sendto(msg.encode(), (peer_ip, peer_port))
    except (KeyboardInterrupt, EOFError):
        stop.set()
        print()


def main() -> None:
    args = parse_args()
    server_addr = resolve(args.server)
    if args.role == "scanner":
        scanner_mode(server_addr, args.id, args.scan_rate, args.replicates)
    else:
        puncher_mode(server_addr, args.id, args.punch_interval)


if __name__ == "__main__":
    main()
