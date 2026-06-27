# UDP Hole Punching 工具集

一组展示和验证 UDP NAT traversal 技术的脚本，从教科书式的 rendezvous server 模型到可通过对称 NAT / CGNAT 的端口扫描变体。

## 背景：UDP hole punching 何时有效？

UDP hole punching 只在至少一端 NAT 是 **endpoint-independent**（cone）时才能成功。如果两端都在 **symmetric NAT** 后面（中国运营商 CGNAT 的典型情况），纯 P2P 是不可能的 —— 端口预测/扫描是唯一剩下的选项，而且它至少需要一端是 cone NAT。

| NAT 类型 | 行为 | Hole punching |
|---|---|---|
| Full Cone | 任何目标使用相同公网端口；接受任何来源 | Trivial |
| Restricted Cone | 相同公网端口；接受你发送过的来源 | Easy |
| Port-Restricted Cone | 相同公网端口；只接受你发送过的目标 | Easy |
| Symmetric / CGNAT | 每个目标不同公网端口 | 经典 punch 失败；需要端口扫描 |

本仓库提供两种策略：
1. **Classic**（`holepunch_cli.py`）—— 用于 cone+cone pair。
2. **Scanner/puncher**（`holepunch_scan.py`）—— 用于 cone+symmetric NAT pair。cone 端扫描 symmetric 端公网 IP 的全部 65535 个端口；symmetric 端持续向 cone 端稳定的 advertised port 发送 keep-alive packet 以保持 mapping。

## 文件

| 文件 | 用途 |
|---|---|
| `holepunch_server.py` | Rendezvous server。记录每个 client 的 public endpoint 并广播 peer list。两种 client 策略都使用它。 |
| `holepunch_cli.py` | 简单 hole-punching client。每个 client 一个 socket，向 peer 的广播 endpoint 喷射 packet。仅适用于 cone NAT。 |
| `holepunch_scan.py` | 用于 cone+symmetric NAT pair 的 scanner/puncher client。基于 bitmap 的随机端口扫描，支持 per-port replicate burst 和直连 keep-alive mode。 |
| `echo_server.py` | `nat_detect.py` 使用的多端口 UDP echo server，用于探测 NAT mapping behavior。监听 9997、9998、9999。 |
| `nat_detect.py` | 从固定本地端口向多个 destination 发送 UDP probe，并比较每个 destination 报告的 source port。判断 cone vs symmetric。 |
| `send_udp.py` | Legacy ad-hoc UDP packet sender。 |

## 检测你的 NAT 类型

```bash
# 在公网 host 上启动 echo_server（Python 3.8+）
python3 echo_server.py

# 从你想测试的网络：
python3 nat_detect.py <echo_server_ip>
```

输出解释：

```
via 9997 -> 1.2.3.4:38250
via 9998 -> 1.2.3.4:38250
via 9999 -> 1.2.3.4:38250
=> 各 destination source port 相同 -> Cone NAT
```

Same port = cone NAT（使用简单 client）。Different ports = symmetric NAT / CGNAT（使用 scanner/puncher）。

## 方案 1：classic hole punching（cone+cone）

适用于两个都在 cone NAT 后的 peer。

```bash
# Public server
python3 holepunch_server.py --port 9876

# Peer A（任意网络）
python3 holepunch_cli.py --server <host>:9876 --message alice

# Peer B（任意网络）
python3 holepunch_cli.py --server <host>:9876 --message bob
```

每个 client 绑定到一个 ephemeral UDP port，向 server 注册，并向 broadcast list 中的每个 peer endpoint 喷射 packet。一旦两端都完成 punch，packet 就在 peer 之间直接流动。

**Limitation：**如果任意一端在 symmetric NAT 后则完全失败 —— advertised port 只对到 server 的流量有效，对 peer 无效。

## 方案 2：scanner/puncher（cone+symmetric）

适用于一端在 cone NAT 后（scanner）、一端在 symmetric NAT / CGNAT 后（puncher）。已在 CGNAT 移动网络 + 企业 cone NAT 上验证 working。

### 算法

```
   puncher（symmetric）         server（public）          scanner（cone）
        │                              │                          │
   ①─── HELLO ──────────────────► register                         │
        │                        broadcast peer list ◄────────── HELLO ───②
        │                              │                          │
   ③── PUNCH ─────────────────────────────────────────────────► learns peer IP
   （每 0.5 秒，build/stabilize                                      │
     symmetric NAT mapping）                                          │
        │                              │                          │
        │                              │                  ④── SCAN ──────►
        │                              │                  （random order，
        │                              │                   65535 ports，
        │                              │                   N packets each）
        │                              │                          │
        │◄───────────────────────────────────────────── SCAN hits real port ──④
        │                            （puncher's NAT accepts because
        │                             scanner's source matches the
        │                             destination it punched to）
        │                              │                          │
   ⑤ 双方 lock onto discovered endpoint，切换到 PING/PONG heartbeat
```

Puncher 的持续流量至关重要 —— symmetric NAT mapping 在 30 秒~2 分钟后 expire，一旦 expire，下一次 send 可能分配**不同的** public port，使 scanner 已发现的信息 invalidate。

### 用法

```bash
# Public server（与 classic 相同）
python3 holepunch_server.py --port 9876

# Symmetric 端（如 CGNAT mobile hotspot）—— 先启动
python3 holepunch_scan.py --server <host>:9876 --role puncher

# Cone 端（如 corporate network）—— 后启动
python3 holepunch_scan.py --server <host>:9876 --role scanner
```

启动顺序很重要：puncher 必须在 scanner 能 hit 它之前建立其 NAT mapping。

### Key options

| Option | Default | Effect |
|---|---|---|
| `--scan-rate` | 200 | Scanner 每秒总 packet 数。越高 = 越快但更显眼。 |
| `--replicates` | 3 | Per-port 发送 packet 数（loss tolerance）。越高 = 越慢但更可靠。 |
| `--punch-interval` | 0.5 | Puncher keep-alive packet 间隔（秒）。越低 = mapping 更稳定，流量更多。 |

有效 port visit 速率为 `scan_rate / replicates`。默认完整一轮 scan（200/3 ≈ 67 ports/s）耗时约 16 分钟。实践中 puncher 的 real port 通常在 scan 前几千个 port 内发现 —— 已在 `--replicates 5` 时约 8000 port 验证（几分钟）。

### Tuning recipes

| Scenario | Command |
|---|---|
| Default（先试这个） | 无 extra flags |
| Fastest connection | `--scan-rate 500 --replicates 2`（约 4 分钟/round） |
| Lossy network | `--replicates 5`（牺牲 speed 换 reliability） |
| Stealth（避免 IDS） | `--scan-rate 80`（约 40 分钟/round，看起来像 background traffic） |
| Aggressive NAT timeout | `--punch-interval 0.2`（puncher 端） |

### 连接成功后

一旦 scanner 发现 puncher 的 real port，双方进入 direct mode：
- **PING/PONG heartbeat**每 2 秒保持 NAT mapping alive 并验证 bidirectional liveness
- **Stats line**每 15 秒：`alive Ns | sent X | recv Y | last recv Zs ago`
- **Optional chat**：在 `> ` prompt 输入发送 message；PING/PONG/SCAN/PUNCH traffic 会被 filter

如果 `last recv` 持续增长，channel 已死 —— 重启两端。

## 在 public server 上部署

Rendezvous server 必须位于 public internet。使用 `setsid` 在 SSH 断开后继续运行的 deployment 示例：

```bash
scp holepunch_server.py root@<server>:/root/
ssh root@<server> 'setsid python3 -u /root/holepunch_server.py --port 9876 \
                   < /dev/null > /tmp/holepunch.log 2>&1 &'
```

验证它正在 listening：

```bash
ssh root@<server> 'ss -lun | grep :9876'
```

对于 NAT detection，同样 deploy `echo_server.py`（使用 ports 9997–9999）。

> **Gotcha**：永远不要通过 SSH 运行 `pkill -f <script_name>` —— 父 shell 的 argv 包含该 pattern 并被一起 kill（SSH 以 code 255 退出）。使用 bracket trick（`pkill -f "[e]cho_server"`）或仅 pgrep check。

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Scanner 完成一轮，无 discovery | Puncher 未 running，或其 mapping 已 expire | 验证 puncher 仍在 printing；重启两端 |
| Puncher 收到一次 SCAN，然后 silence | Scanner hit port 但之后 packet drop | 提高 `--replicates 5` |
| Server 未收到 HELLO | UDP egress 被阻 | 运行 `nat_detect.py` 验证 basic UDP connectivity |
| 连接后 `last recv` 增长 | 一端 NAT mapping 被 reclaim | 降低 `--punch-interval`；必要时 restart |
| Corporate network 标记 scan | Full-range UDP spray 对 IDS 可见 | 将 `--scan-rate` 降至 50，或 fallback 到 relay（frp/wireguard） |

## 环境

- Python 3.8+（使用 `from __future__ import annotations`、f-string、type hints）
- 用 `python3 -m compileall *.py` 验证 syntax
- 无 third-party dependencies

## 原始提示

> We are going to create hole-punching scripts consisting of a server (srv) and client (cli) Python script. Upon startup, each client continuously sends UDP messages to the server every 5 seconds. The server extracts the IP address and port of each NATed client from these messages. When the server receives a message, it broadcasts the list of all known IP addresses and ports to every client. Upon receiving the broadcasted list, each client attempts to send UDP messages to the IP addresses and ports in that list. Whenever a client receives a message from another client, it prints the sender's IP address, port, and the message content. With only two clients and one server, the setup remains straightforward. During broadcasting, the server should filter out a client's own IP address and port by removing that client's information from the peer list before sending.
