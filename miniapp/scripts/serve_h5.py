"""本地预览 H5 构建产物（支持 Taro history 路由的 SPA 回退）。

用法：python3 scripts/serve_h5.py [dist目录] [端口]
"""
import http.server
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "dist-h5"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 10087


class SpaHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def send_head(self):
        target = self.translate_path(self.path)
        if not os.path.exists(target) and "." not in os.path.basename(target):
            # 只对无扩展名的路由回退到 index.html，避免把缺失的 js/css 伪装成 200
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), SpaHandler) as httpd:
        print(f"H5 预览: http://127.0.0.1:{PORT}  (root={ROOT})")
        httpd.serve_forever()