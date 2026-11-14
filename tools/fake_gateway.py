"""
A stand-in for a host that is having a bad day.

Answers every request with 502, 503 or 504 and a plain page, exactly as
Render's own proxy would while the service is down or restarting.

    python tools/fake_gateway.py 8000 502

Run it on the port the site normally uses, with the real server stopped. A
visitor who has been to the site before should NOT see the plain page below:
the service worker recognises the gateway status and serves our own
/error/502/ page from the cache instead, with the assistant on it.

Someone visiting for the very first time during an outage has no service
worker on their device yet, so they do see this. That limit is in the README.
"""

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATUS = 502

BODY = b"""<!doctype html>
<html><head><title>%d</title></head>
<body style="font:16px system-ui;padding:3rem">
<h1>%d</h1>
<p>This is the hosting provider's own page. If you can read it, the service
worker did not swap in our page.</p>
</body></html>
"""


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def respond(self):
        body = BODY % (STATUS, STATUS)
        self.send_response(STATUS)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = respond
    do_POST = respond
    do_HEAD = respond

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{STATUS} {self.path}\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if len(sys.argv) > 2:
        STATUS = int(sys.argv[2])
    print(f"Answering every request on port {port} with {STATUS}")
    ThreadingHTTPServer(("127.0.0.1", port), GatewayHandler).serve_forever()
