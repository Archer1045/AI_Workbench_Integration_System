"""后端启动入口：先检查端口，避免重复实例，再启动 uvicorn。"""
import socket
import sys

import uvicorn

import config

HOST = config.BACKEND_HOST
PORT = config.BACKEND_PORT


def port_in_use(port: int) -> bool:
    """通过 TCP 连接探测端口是否已被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        try:
            sock.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


if __name__ == "__main__":
    if port_in_use(PORT):
        print(f"端口 {PORT} 已被占用，后端可能已在运行。")
        sys.exit(1)
    # 使用绝对路径启动时，uvicorn 需要在 backend 目录下找到 app 模块
    uvicorn.run("app:app", host=HOST, port=PORT)
