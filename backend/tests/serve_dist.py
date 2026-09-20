"""
静态文件服务器（仅用于验证前端构建产物）
=====================================
Vite 的 dev server 在受限沙箱下无法使用（esbuild 加载配置时用管道 stdio 启动子进程，
会命中 "spawn EPERM"）。本脚本用纯标准库把 `dist/` 目录伺服起来，
配合已启动的后端（8124）即可验证生产构建产物与后端接口是否连通。

用法：
    python tests/serve_dist.py [port]
然后浏览器访问 http://localhost:5177

注意：这只是验证工具，不是项目的一部分。
"""
import http.server
import os
import socketserver
import sys

DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "frontend", "dist",
)
DIST = os.path.abspath(DIST)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5177


class SpaHandler(http.server.SimpleHTTPRequestHandler):
    """支持 history 模式的 SPA：找不到的路径回退到 index.html。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIST, **kwargs)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} - {fmt % args}", flush=True)

    def do_GET(self):
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            index = os.path.join(DIST, "index.html")
            if os.path.exists(index):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                with open(index, "rb") as fh:
                    body = fh.read()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        return super().do_GET()


if __name__ == "__main__":
    if not os.path.isdir(DIST):
        raise SystemExit(f"未找到构建产物目录: {DIST}\n请先在 frontend 下执行 npm run build")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), SpaHandler) as httpd:
        print(f"静态服务已启动: http://localhost:{PORT}  (root = {DIST})", flush=True)
        httpd.serve_forever()
