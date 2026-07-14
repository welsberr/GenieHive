import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke_foundation_archive.py"


class _SmokeHandler(BaseHTTPRequestHandler):
    response_status = 200
    response_body = {
        "choices": [{"message": {"role": "assistant", "content": "OK"}}]
    }
    received: dict = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        length = int(self.headers["Content-Length"])
        self.__class__.received = {
            "path": self.path,
            "headers": dict(self.headers),
            "body": json.loads(self.rfile.read(length).decode("utf-8")),
        }
        payload = json.dumps(self.response_body).encode("utf-8")
        self.send_response(self.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args) -> None:
        return


def _run_smoke(server: ThreadingHTTPServer, **overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("GENIEHIVE_BASE_URL", None)
    env.pop("GENIEHIVE_API_KEY", None)
    env.pop("GENIEHIVE_MODEL", None)
    env.update(
        {
            "GENIEHIVE_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            "GENIEHIVE_API_KEY": "test-client-key",
            **overrides,
        }
    )
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SmokeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_archive_smoke_client_sends_role_and_geniehive_key() -> None:
    server, thread = _server()
    try:
        result = _run_smoke(server)
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
    assert _SmokeHandler.received["path"] == "/v1/chat/completions"
    assert _SmokeHandler.received["headers"]["X-Api-Key"] == "test-client-key"
    assert _SmokeHandler.received["body"]["model"] == "archive_migrator"


def test_archive_smoke_client_reports_missing_configuration() -> None:
    env = os.environ.copy()
    env.pop("GENIEHIVE_BASE_URL", None)
    env.pop("GENIEHIVE_API_KEY", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "GENIEHIVE_BASE_URL" in result.stderr
    assert "GENIEHIVE_API_KEY" in result.stderr


def test_archive_smoke_client_reports_http_failure() -> None:
    _SmokeHandler.response_status = 503
    server, thread = _server()
    try:
        result = _run_smoke(server)
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        _SmokeHandler.response_status = 200

    assert result.returncode == 1
    assert "HTTP 503" in result.stderr
