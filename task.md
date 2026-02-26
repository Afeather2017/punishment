Prompt for Programming Tool

Project: UDP Hole Punching Demo with Peer-to-Peer Communication

Objective: Create a complete UDP hole punching demonstration with three components:
1. Signaling Server - Public server that facilitates address exchange
2. Client A - Behind NAT/firewall #1  
3. Client B - Behind NAT/firewall #2

After the server helps them exchange public addresses, the two clients should establish direct peer-to-peer UDP communication to demonstrate successful NAT traversal.

Requirements

1. Signaling Server (Python)

• Purpose: Help clients discover each other's public endpoints

• Features:

  • UDP server on port 9999

  • Register clients and store their (public_ip, public_port) pairs

  • List registered clients with unique IDs

  • Exchange addresses between two specific clients

  • Relay initial "punch" messages to trigger hole punching

2. Client Application (Python - Single script for both A and B)

• Purpose: Demonstrate successful UDP hole punching and peer-to-peer chat

• Features:

  • Register with signaling server

  • Request peer list

  • Select a peer for direct connection

  • Perform UDP hole punching sequence:

    1. Get peer's public address from server
    2. Simultaneously send UDP packets to create NAT openings
    3. Establish direct communication channel
  • Simple chat interface after connection:

    ◦ Send messages directly to peer

    ◦ Receive messages from peer

    ◦ Show connection status (direct vs relayed)

  • Display public/private IP information

  • Handle different NAT scenarios

Technical Specifications

Protocol Messages

Client → Server (UDP):
• REGISTER <client_id> - Register with optional ID

• LIST - Request list of connected peers

• CONNECT_TO <peer_id> - Request connection to specific peer

• PUNCH <peer_id> <message> - Relay initial punch message

Server → Client (UDP):
• REGISTERED <your_id> - Registration confirmation

• PEERS <peer1_id:ip:port,peer2_id:ip:port,...> - List of available peers

• PEER_ADDRESS <peer_id> <peer_ip> <peer_port> - Specific peer's public address

• RELAY <from_peer_id> <message> - Relay message from another peer

Peer-to-Peer (Direct UDP after hole punch):
• HELLO - Initial connection test

• PING - Keepalive

• MSG <text> - Chat message

• BYE - End connection

Implementation Requirements

Server Code (udp_holepunch_server.py):

# Must include:
# - UDP socket on configurable port
# - Thread-safe client registry
# - Address exchange logic
# - Simple command-line interface showing connected clients
# - Ability to manually trigger hole punching between two clients


Client Code (udp_holepunch_client.py):

# Must include:
# - Command-line arguments: server_ip, server_port, [client_id]
# - Two communication channels:
#   1. To server (for signaling)
#   2. To peer (for direct communication after hole punch)
# - Two threads:
#   1. Listen for messages (both from server AND peer)
#   2. User input for sending messages
# - Clear status display showing:
#   - Public IP:Port (as seen by server)
#   - Private IP:Port
#   - Current peer connection status
# - Hole punching sequence with automatic retry


Expected Behavior

1. Start server on public machine:
   python udp_holepunch_server.py 0.0.0.0 9999
   

2. Start Client A behind NAT #1:
   python udp_holepunch_client.py server_ip 9999 Alice
   
   • Registers, gets public endpoint

   • Requests peer list (initially empty)

3. Start Client B behind NAT #2:
   python udp_holepunch_client.py server_ip 9999 Bob
   
   • Registers, gets public endpoint

4. Alice requests Bob's address:
   • Alice: connect Bob

   • Server sends Bob's public address to Alice

   • Server sends Alice's public address to Bob

5. Hole punching sequence:
   • Alice and Bob simultaneously send UDP packets to each other's public addresses

   • NATs create temporary openings

   • Direct connection established

6. Peer-to-peer chat:

   [Alice] Connected directly to Bob!
   [Alice] > Hello Bob!
   [Bob] Received from Alice: Hello Bob!
   [Bob] > Hi Alice! This is direct P2P!
   

Success Criteria

• Two clients behind different NATs establish direct UDP communication

• Server only facilitates initial introduction, not ongoing data transfer

• Clients display both public and private IP information

• After hole punch, chat messages flow directly between clients

• Handle at least 3 failed punch attempts before falling back to server relay

• Clear console output showing each step of the process

Testing Instructions

1. Deploy server on public cloud (AWS EC2, DigitalOcean, etc.)
2. Run Client A on home network #1
3. Run Client B on home network #2 (or use phone hotspot)
4. Verify:
   • Clients can see each other through server

   • Clients exchange public addresses

   • Direct communication succeeds (or fails with clear reason)

   • Messages appear in real-time

Deliverables

1. udp_holepunch_server.py - Complete signaling server
2. udp_holepunch_client.py - Client application with hole punching
3. README.md - Setup and testing instructions
4. Example output screenshots showing successful hole punch

Note: Include error handling for common NAT types (full cone, restricted, port restricted, symmetric) with appropriate fallback strategies.
