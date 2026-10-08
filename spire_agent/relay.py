"""
CommunicationMod Socket Relay Bridge
将《杀戮尖塔》Steam CommunicationMod (stdin/stdout) 桥接至本地 TCP 端口 (127.0.0.1:18888)，
使 MCP Server、Antigravity、Cursor 或外部脚本能在非阻塞状态下与游戏自由通信。

使用方式:
在 Steam SlayTheSpire/mods/CommunicationMod 配置中设置 command 为:
python -m spire_agent.relay
"""

import sys
import socket
import threading
import json
import time
import logging

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s [Relay] %(message)s")
logger = logging.getLogger("spire_relay")

HOST = "127.0.0.1"
PORT = 18888


def handle_client(conn, addr, lock, last_state_container):
    logger.info(f"客户端已连接: {addr}")
    # 若已有缓存的最新状态帧，立即推给刚连上的客户端
    with lock:
        if last_state_container["state"]:
            try:
                conn.sendall((last_state_container["state"] + "\n").encode("utf-8"))
            except Exception:
                pass
        else:
            # 若尚未收到任何状态帧，向游戏主动请求一次最新稳定状态
            sys.stdout.write("state\n")
            sys.stdout.flush()

    try:
        f = conn.makefile("r", encoding="utf-8")
        while True:
            line = f.readline()
            if not line:
                break
            cmd = line.strip()
            if cmd:
                # 转发客户端发送的指令至游戏标准输入
                sys.stdout.write(cmd + "\n")
                sys.stdout.flush()
    except Exception as e:
        logger.warning(f"客户端 {addr} 断开连接: {e}")
    finally:
        conn.close()


def main():
    logger.info(f"启动 CommunicationMod Socket 继电器服务: {HOST}:{PORT} ...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
    except Exception as e:
        logger.error(f"绑定端口 {PORT} 失败: {e}")
        return

    server.listen(5)

    lock = threading.Lock()
    last_state = {"state": None}
    clients = []

    def stdin_reader():
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line_str = line.strip()
            if not line_str:
                continue
            with lock:
                last_state["state"] = line_str
                # 广播给所有已连接的外部客户端
                for c in list(clients):
                    try:
                        c.sendall((line_str + "\n").encode("utf-8"))
                    except Exception:
                        if c in clients:
                            clients.remove(c)

    threading.Thread(target=stdin_reader, daemon=True).start()

    # 向游戏握手发送初始 ready 信号
    sys.stdout.write("ready\n")
    sys.stdout.flush()

    while True:
        try:
            conn, addr = server.accept()
            with lock:
                clients.append(conn)
            threading.Thread(target=handle_client, args=(conn, addr, lock, last_state), daemon=True).start()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"接受连接异常: {e}")


if __name__ == "__main__":
    main()
