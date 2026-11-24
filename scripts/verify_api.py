import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


def request(base, path, expected_status=200, payload=None, simulation=None):
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    if simulation is not None:
        headers["X-Simulate-Failure"] = simulation

    outgoing = Request(f"{base}{path}", data=body, headers=headers)
    try:
        with urlopen(outgoing, timeout=120) as response:
            status, data = response.status, response.read()
    except HTTPError as error:
        status, data = error.code, error.read()
    except URLError as error:
        raise SystemExit(f"Could not reach {base}: {error.reason}") from None

    if status != expected_status:
        raise SystemExit(f"{path}: expected HTTP {expected_status}, got {status}: {data.decode(errors='replace')}")
    return json.loads(data)


def require(condition, description):
    if not condition:
        raise SystemExit(f"Check failed: {description}")


def verify(base):
    run_id = f"verify-{uuid4().hex[:12]}"
    prompt = f"What is the capital of France? Answer in one sentence. Reference: {run_id}."

    def chat(suffix, message=prompt, **kwargs):
        return request(base, "/chat", payload={"session_id": f"{run_id}-{suffix}", "message": message}, **kwargs)

    health = request(base, "/health")
    require(health["status"] == "ok" and health["keys_configured"] >= 2 and health["cache_enabled"], "health readiness")
    print("GET /health", health)

    live = chat("live")
    cache = chat("cache")
    require(live["reply"].strip() and live["metadata"]["resolution_source"] == "LIVE_INFERENCE", "live answer")
    require(cache["metadata"]["resolution_source"] == "LLM_CACHE" and cache["reply"] == live["reply"], "identical cached answer")
    require(cache["metadata"]["key_id"] is None and cache["metadata"]["fallback_attempts"] == 0, "cache routing metadata")
    for field in ("input_tokens", "output_tokens"):
        require(isinstance(live["metadata"][field], int) and cache["metadata"][field] == live["metadata"][field], f"stored {field}")
    require(cache["metadata"]["latency_ms"] < live["metadata"]["latency_ms"], "cache response is faster")
    print("POST /chat (live)", live["metadata"])
    print("POST /chat (cache)", cache["metadata"])

    follow_up = chat("live", message="Which country did I ask about in my first message?")
    history = request(base, f"/sessions/{run_id}-live/messages")["messages"]
    require([message["role"] for message in history] == ["user", "assistant", "user", "assistant"], "ordered history")
    require(history[-1]["metadata"] == follow_up["metadata"], "saved per-request metadata")
    print("GET /sessions/{session_id}/messages", [message["role"] for message in history])

    for status in (429, 500):
        fallback = chat(f"fallback-{status}", simulation=f"key_1={status}")
        metadata = fallback["metadata"]
        require(fallback["reply"].strip() and metadata["key_id"] == "key_2", f"key_2 answers after {status}")
        require(metadata["resolution_source"] == "LIVE_INFERENCE" and metadata["fallback_attempts"] == 1, "live fallback metadata")
        print(f"POST /chat (key_1={status})", metadata)

    rejected = chat("rejected", simulation="*=429", expected_status=503)
    require(rejected == {"detail": "all providers unavailable"}, "clean all-keys-failed response")
    invalid = chat("rejected", message=" ", expected_status=422)
    require("detail" in invalid, "validation error response")
    missing = request(base, f"/sessions/{run_id}-rejected/messages", expected_status=404)
    require(missing == {"detail": "session not found"}, "failed turns left no session")
    print("HTTP 503, 422 and 404 verified. Failed turns left no history.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify the Lyftr API against a running deployment.")
    parser.add_argument("--api-base", default="http://localhost:8000")
    verify(parser.parse_args().api_base.rstrip("/"))
