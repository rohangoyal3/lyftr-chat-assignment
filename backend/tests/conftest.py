import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class Provider(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), ProviderRequest)
        self.calls = []
        self.failures = {}

    @property
    def api_base(self):
        return f"http://127.0.0.1:{self.server_port}/v1"


class ProviderRequest(BaseHTTPRequestHandler):
    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        key = self.headers["Authorization"].removeprefix("Bearer ")
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        messages = payload["messages"]
        self.server.calls.append((key, messages))
        time.sleep(0.035)
        failure = self.server.failures.get(key)
        if failure:
            status, code = failure
            self.respond(status, {"error": {"message": code, "type": code, "code": code}})
            return

        user_inputs = [message["content"] for message in messages if message["role"] == "user"]
        self.respond(200, {
            "id": "example-completion",
            "object": "chat.completion",
            "created": 1760000000,
            "model": "gpt-4o-mini",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": f"You asked: {' / '.join(user_inputs)}"},
            }],
            "usage": {"prompt_tokens": 10 + 7 * len(messages), "completion_tokens": 6, "total_tokens": 16 + 7 * len(messages)},
        })

    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def provider():
    with Provider() as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture
def settings(tmp_path, provider):
    return Settings(
        api_keys=("test-first", "test-second"),
        db_path=tmp_path / "app.db",
        model="openai/gpt-4o-mini",
        api_base=provider.api_base,
        enable_failure_simulation=True,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client
