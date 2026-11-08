"""Authenticated, narrow HTTP gateway for the Brev-hosted Anytime Nemotron demo."""

import hmac
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


TOKEN_PATH = os.environ.get("ANYTIME_NIM_TOKEN_FILE", "/home/ubuntu/.anytime-nim-token")
with open(TOKEN_PATH, encoding="utf-8") as token_file:
    TOKEN = token_file.read().strip()
if len(TOKEN) < 32:
    raise RuntimeError("Gateway token must contain at least 32 characters")


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, b'{"ready":true}')
        self.respond(404, b'{"error":"Not found"}')

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self.respond(404, b'{"error":"Not found"}')
        provided = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(provided, TOKEN):
            return self.respond(401, b'{"error":"Unauthorized"}')
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 100_000:
            return self.respond(413, b'{"error":"Request too large"}')
        request = urllib.request.Request(
            "http://127.0.0.1:8000/v1/chat/completions",
            data=self.rfile.read(length),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                self.respond(response.status, response.read(500_000))
        except urllib.error.HTTPError as error:
            self.respond(error.code, error.read(2000))
        except Exception:
            self.respond(502, b'{"error":"Nemotron unavailable"}')


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8001), Handler).serve_forever()
