# UDP Hole Punching Utilities

A collection of scripts demonstrating and validating UDP NAT traversal techniques, from the textbook rendezvous-server model to a port-scanning variant that works through symmetric NAT / CGNAT.

## Background: when does UDP hole punching work?

UDP hole punching succeeds only when at least one peer's NAT is **endpoint-independent** (cone). If both peers are behind **symmetric NAT** (typical of carrier CGNAT, common in China), pure P2P is impossible — port prediction/scanning is the only remaining option, and it requires at least one cone endpoint.

| NAT type | Behavior | Hole punching |
|---|---|---|
| Full Cone | Same public port for any destination; accepts from any source | Trivial |
| Restricted Cone | Same public port; accepts from sources you've sent to | Easy |
| Port-Restricted Cone | Same public port; accepts only from dst you've sent to | Easy |
| Symmetric / CGNAT | Different public port per destination | Classic punch fails; needs port scanning |

This repo provides two strategies:
1. **Classic** (`holepunch_cli.py`) — for cone+cone pairs.
2. **Scanner/puncher** (`holepunch_scan.py`) — for cone+symmetric pairs. The cone side sprays all 65535 ports on the symmetric peer's public IP; the symmetric side continuously punches the cone side's stable advertised port to keep its mapping alive.

## Files

| File | Purpose |
|---|---|
| `holepunch_server.py` | Rendezvous server. Records each client's public endpoint and broadcasts the peer list. Used by both client strategies. |
| `holepunch_cli.py` | Simple hole-punching client. One socket per client, sprays packets at peers' advertised endpoints. Works for cone NAT only. |
| `holepunch_scan.py` | Scanner/puncher client for cone+symmetric NAT pairs. Bitmap-based random port scan with per-port replicate bursts and keep-alive direct mode. |
| `echo_server.py` | Multi-port UDP echo server used by `nat_detect.py` to probe NAT mapping behavior. Listens on 9997, 9998, 9999. |
| `nat_detect.py` | Sends UDP probes from a fixed local port to multiple destinations and compares the source port each destination reports. Determines cone vs symmetric. |
| `send_udp.py` | Legacy ad-hoc UDP packet sender. |

## Detecting your NAT type

```bash
# Start echo_server on a public host (Python 3.8+)
python3 echo_server.py

# From the network you want to test:
python3 nat_detect.py <echo_server_ip>
```

Output interpretation:

```
via 9997 -> 1.2.3.4:38250
via 9998 -> 1.2.3.4:38250
via 9999 -> 1.2.3.4:38250
=> Same source port across destinations -> Cone NAT
```

Same port = cone NAT (use the simple client). Different ports = symmetric NAT / CGNAT (use scanner/puncher).

## Approach 1: classic hole punching (cone+cone)

For two peers both behind cone NAT.

```bash
# Public server
python3 holepunch_server.py --port 9876

# Peer A (any network)
python3 holepunch_cli.py --server <host>:9876 --message alice

# Peer B (any network)
python3 holepunch_cli.py --server <host>:9876 --message bob
```

Each client binds to an ephemeral UDP port, registers with the server, and sprays packets at every peer endpoint in the broadcasted list. Packets flow directly between peers once both sides have punched.

**Limitation:** fails completely if either peer is behind symmetric NAT — the advertised port is only valid for traffic to the server, not to the peer.

## Approach 2: scanner/puncher (cone+symmetric)

For one peer behind cone NAT (scanner) and one behind symmetric NAT / CGNAT (puncher). Validated working against a CGNAT mobile network + corporate cone NAT.

### Algorithm

```
   puncher (symmetric)            server (public)            scanner (cone)
        │                              │                          │
   ①─── HELLO ──────────────────► register                         │
        │                        broadcast peer list ◄────────── HELLO ───②
        │                              │                          │
   ③── PUNCH ─────────────────────────────────────────────────► learns peer IP
   (every 0.5s, builds/stabilizes                                      │
    the symmetric NAT mapping)                                         │
        │                              │                          │
        │                              │                  ④── SCAN ──────►
        │                              │                  (random order,
        │                              │                   65535 ports,
        │                              │                   N packets each)
        │                              │                          │
        │◄───────────────────────────────────────────── SCAN hits real port ──④
        │                            (puncher's NAT accepts because
        │                             scanner's source matches the
        │                             destination it punched to)
        │                              │                          │
   ⑤ Both lock onto the discovered endpoint, switch to PING/PONG heartbeat
```

The puncher's continuous traffic is essential — symmetric NAT mappings expire after 30s–2min, and once expired, the next send may allocate a **different** public port, invalidating what the scanner already discovered.

### Usage

```bash
# Public server (same as classic)
python3 holepunch_server.py --port 9876

# Symmetric side (e.g. CGNAT mobile hotspot) — start FIRST
python3 holepunch_scan.py --server <host>:9876 --role puncher

# Cone side (e.g. corporate network) — start SECOND
python3 holepunch_scan.py --server <host>:9876 --role scanner
```

Start order matters: puncher must establish its NAT mapping before the scanner can hit it.

### Key options

| Option | Default | Effect |
|---|---|---|
| `--scan-rate` | 200 | Total packets per second from scanner. Higher = faster but more visible. |
| `--replicates` | 3 | Packets sent per port (loss tolerance). Higher = slower but more reliable. |
| `--punch-interval` | 0.5 | Seconds between puncher's keep-alive packets. Lower = more stable mapping, more traffic. |

Effective port-visit rate is `scan_rate / replicates`. A full scan round at defaults (200/3 ≈ 67 ports/s) takes ~16 minutes. In practice the puncher's real port is usually found within the first several thousand ports scanned — validated at ~8000 ports with `--replicates 5` (a few minutes).

### Tuning recipes

| Scenario | Command |
|---|---|
| Default (try first) | no extra flags |
| Fastest connection | `--scan-rate 500 --replicates 2` (~4 min/round) |
| Lossy network | `--replicates 5` (sacrifice speed for reliability) |
| Stealth (avoid IDS) | `--scan-rate 80` (~40 min/round, looks like background traffic) |
| Aggressive NAT timeout | `--punch-interval 0.2` (puncher side) |

### After connection

Once the scanner discovers the puncher's real port, both sides enter direct mode:
- **PING/PONG heartbeat** every 2s keeps the NAT mapping alive and verifies bidirectional liveness
- **Stats line** every 15s: `alive Ns | sent X | recv Y | last recv Zs ago`
- **Optional chat**: type at the `> ` prompt to send messages; PING/PONG/SCAN/PUNCH traffic is filtered out

If `last recv` keeps growing, the channel is dead — restart both ends.

## Deployment on a public server

The rendezvous server must sit on the public internet. Example deployment using `setsid` to survive SSH disconnect:

```bash
scp holepunch_server.py root@<server>:/root/
ssh root@<server> 'setsid python3 -u /root/holepunch_server.py --port 9876 \
                   < /dev/null > /tmp/holepunch.log 2>&1 &'
```

Verify it's listening:

```bash
ssh root@<server> 'ss -lun | grep :9876'
```

For NAT detection, deploy `echo_server.py` the same way (uses ports 9997–9999).

> **Gotcha:** never run `pkill -f <script_name>` over SSH — the parent shell's argv contains the pattern and gets killed too (SSH exits with code 255). Use the bracket trick (`pkill -f "[e]cho_server"`) or pgrep-only checks.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Scanner completes a full round, no discovery | Puncher isn't running, or its mapping expired | Verify puncher is still printing; restart both ends |
| Puncher receives SCAN once, then silence | Scanner hit the port but packets dropped afterwards | Raise `--replicates 5` |
| Server receives no HELLO | UDP egress blocked | Run `nat_detect.py` to verify basic UDP connectivity |
| `last recv` grows after connection | One side's NAT mapping was reclaimed | Lower `--punch-interval`; restart if needed |
| Corporate network flags the scan | Full-range UDP spray is IDS-visible | Drop `--scan-rate` to 50, or fall back to a relay (frp/wireguard) |

## Environment

- Python 3.8+ (uses `from __future__ import annotations`, f-strings, type hints)
- Validate syntax with `python3 -m compileall *.py`
- No third-party dependencies

## Original prompt

> We are going to create hole-punching scripts consisting of a server (srv) and client (cli) Python script. Upon startup, each client continuously sends UDP messages to the server every 5 seconds. The server extracts the IP address and port of each NATed client from these messages. When the server receives a message, it broadcasts the list of all known IP addresses and ports to every client. Upon receiving the broadcasted list, each client attempts to send UDP messages to the IP addresses and ports in that list. Whenever a client receives a message from another client, it prints the sender's IP address, port, and the message content. With only two clients and one server, the setup remains straightforward. During broadcasting, the server should filter out a client's own IP address and port by removing that client's information from the peer list before sending.
