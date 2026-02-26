# UDP Hole Punching Utilities

This repository now hosts a lightweight signaling server and client pair (`holepunch_server.py` / `holepunch_cli.py`) plus the legacy `send_udp.py` helper retained for ad-hoc testing. Together they demonstrate how a central server can keep track of NATed endpoints and broadcast peer lists so every client can hole-punch through NATs.

## Prompt to generate the code

We are going to create hole-punching scripts consisting of a server (srv) and client (cli) Python script. Upon startup, each client continuously sends UDP messages to the server every 5 seconds. The server extracts the IP address and port of each NATed client from these messages. When the server receives a message, it broadcasts the list of all known IP addresses and ports to every client. Upon receiving the broadcasted list, each client attempts to send UDP messages to the IP addresses and ports in that list. Whenever a client receives a message from another client, it prints the sender's IP address, port, and the message content. With only two clients and one server, the setup remains straightforward. During broadcasting, the server should filter out a client's own IP address and port by removing that client's information from the peer list before sending.

## Files

- `holepunch_server.py`: UDP rendezvous server that records client keep-alives, prunes inactive peers after a configurable timeout, and replies to each keep-alive with a newline-separated list of *other* clients. Each list line follows `IP PORT MESSAGE` to keep things easy to parse.
- `holepunch_cli.py`: Sends a keep-alive message to the server every few seconds, listens for the server’s peer list broadcast, punches UDP packets at every returned endpoint, and logs any peer messages it receives.
- `send_udp.py`: Legacy helper tool for manually sending UDP packets; left untouched so it can still be used for unrelated testing.

## Running the server

```bash
python holepunch_server.py --port 9999
```

Options:

- `--bind`: Address to bind to (`0.0.0.0` by default).
- `--port`: UDP port (default `9999`).
- `--timeout`: Seconds of inactivity before a client is dropped (`30`).

The server logs keep-alives, prunes idle peers, and broadcasts the current peer list (excluding the recipient) whenever it gets a keep-alive.

## Running a client

```bash
python holepunch_cli.py --server <host>:<port> --message "my id"
```

Options:

- `--server`: Required `host:port` for the rendezvous server.
- `--message`: UTF-8 payload shared with peers (defaults to `hostname:pid`).
- `--interval`: Seconds between keep-alives (default `5`).

Each CLI binds to an ephemeral UDP port, reports that endpoint to the server, then immediately tries to punch a packet to every peer listed in the broadcast it receives. Incoming peer packets are logged as `Received N bytes from IP:PORT -> MESSAGE`.

## Validation

1. Start `holepunch_server.py` on a reachable host.
2. Run two clients (on the same machine or different networks) pointing at the server with different `--message` values.
3. Watch each client print the other peer’s packets and the server log the keep-alives/broadcasts.
4. Use `send_udp.py` separately if you need to simulate custom packets for debugging.

## Environment

- Python 3.8+ is required for the holepunch scripts; `python3 -m compileall holepunch_server.py holepunch_cli.py` ensures both modules are syntactically valid.
- UDP connectivity must be open so the server can receive the clients’ packets and forward the peer lists.
