import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


BLOBS = "/api/v1/collect/blobs/"
ARTIFACTS = "/api/v1/collect/artifacts/"


class FakePlatform:
    """Answers POSTs with scripted responses, in order, and records every request. Blob HEAD/PUT answer by sha256
    instead (they run in parallel, so no order): HEAD 200 for what is in `stored`, else 404; PUT `put_status` (201 by
    default; a list answers in turn) and stores it on 2xx. `blob_delay` slows each blob request; `blob_hangup` drops
    the connection. `key_check`, when set, answers GET /collect/key. Trace HEAD/PUT on /collect/artifacts/{sha256} are
    answered the same way and recorded with `path`."""

    def __init__(self):
        self.url = ""
        self.responses = []
        self.requests = []
        self.stored = set()
        self.put_status = {}
        self.blob_delay = 0.0
        self.blob_hangup = False
        self.blob_requests = []
        self.key_check = None

    def reply(self, status, body=None, headers=None, delay=0.0):
        self.responses.append((status, {} if body is None else body, headers or {}, delay))


@pytest.fixture
def platform():
    fake = FakePlatform()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            with lock:
                fake.requests.append({"path": self.path, "headers": self.headers, "body": body})
                if fake.responses:
                    status, payload, headers, delay = fake.responses.pop(0)
                else:
                    status, payload, headers, delay = 500, {"detail": "no response scripted"}, {}, 0.0
            time.sleep(delay)
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/v1/collect/key" and fake.key_check is not None:
                self._answer(200, fake.key_check)
                return
            self.do_POST()

        def do_HEAD(self):
            self._blob("HEAD", b"")

        def do_PUT(self):
            self._blob("PUT", self.rfile.read(int(self.headers.get("Content-Length", 0))))

        def _blob(self, method, body):
            prefix = next((p for p in (BLOBS, ARTIFACTS) if self.path.startswith(p)), None)
            sha = self.path[len(prefix):] if prefix else ""
            with lock:
                fake.blob_requests.append({"method": method, "sha": sha, "headers": self.headers, "body": body,
                                           "path": self.path})
            time.sleep(fake.blob_delay)
            if fake.blob_hangup:
                self.close_connection = True
                return
            with lock:
                if method == "HEAD":
                    status = 200 if sha in fake.stored else 404
                else:
                    status = fake.put_status.get(sha, 201)
                    if isinstance(status, list):  # answers in turn; the last one repeats
                        status = status.pop(0) if len(status) > 1 else status[0]
                    if status in (200, 201):
                        fake.stored.add(sha)
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _answer(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            pass  # the client hung up first (the timeout tests do that on purpose)

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
