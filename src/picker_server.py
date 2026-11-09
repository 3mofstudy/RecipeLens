"""僅綁定本機回環位址，將 Google 官方網頁 Picker 的結果傳回桌面程式。"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import socket
import time
import webbrowser


class LocalPickerServer(HTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def pick_folder_in_browser(access_token, app_id, *, timeout=300, opener=None):
    nonce = secrets.token_urlsafe(32)
    result = None
    config = {"access_token": access_token, "app_id": app_id}
    page = Path(__file__).with_name("picker_page.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body, content_type="text/plain; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") != authority:
                self.reply(403, b"Forbidden")
            elif self.path == f"/{nonce}/":
                self.reply(200, page, "text/html; charset=utf-8")
            elif self.path == f"/{nonce}/config":
                self.reply(200, json.dumps(config).encode(), "application/json")
            else:
                self.reply(404, b"Not found")

        def do_POST(self):
            nonlocal result
            if (self.path != f"/{nonce}/result" or self.headers.get("Host") != authority
                    or self.headers.get("Origin") != origin):
                self.reply(403, b"Forbidden")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("Invalid response size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or data.get("action") not in {"picked", "cancel", "error"}:
                    raise ValueError("Invalid picker response")
                if data["action"] == "picked" and not isinstance(data.get("folder_id"), str):
                    raise ValueError("Missing folder ID")
            except (ValueError, TypeError):
                self.reply(400, b"Invalid response")
                return
            self.reply(200, b"OK")
            result = data

    with LocalPickerServer(("127.0.0.1", 0), Handler) as server:
        authority = f"127.0.0.1:{server.server_port}"
        origin = f"http://{authority}"
        url = f"{origin}/{nonce}/"
        if (opener or webbrowser.open)(url) is False:
            raise RuntimeError("無法開啟系統瀏覽器。")
        deadline = time.monotonic() + timeout
        while result is None and time.monotonic() < deadline:
            server.timeout = min(0.5, max(0.01, deadline - time.monotonic()))
            server.handle_request()
    if result is None:
        raise TimeoutError("Google 資料夾選擇逾時，本機檔案已保留。")
    if result["action"] == "cancel":
        return None
    if result["action"] == "error":
        raise RuntimeError(f"Google 選擇器未完成：{result.get('message', '未知錯誤')}")
    return result["folder_id"]
