from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def chat(client, session="s-original", message="What is the capital of France?", header=None, **extra):
    return client.post(
        "/chat",
        headers={"X-Simulate-Failure": header} if header else {},
        json={"session_id": session, "message": message, **extra},
    )


def test_health_unknown_session_and_cors(client):
    assert client.get("/health").json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}
    missing = client.get("/sessions/missing/messages")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "session not found"}
    preflight = client.options("/chat", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-simulate-failure",
    })
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_exact_cache_match_across_sessions(client, provider):
    first = chat(client).json()
    cached = chat(client, session="s-cache").json()
    different = chat(client, session="s-different", message="What is the capital of Greece?").json()
    assert first["metadata"] == {
        "resolution_source": "LIVE_INFERENCE", "model": "openai/gpt-4o-mini",
        "latency_ms": first["metadata"]["latency_ms"], "input_tokens": 24, "output_tokens": 6,
        "key_id": "key_1", "fallback_attempts": 0,
    }
    assert cached["reply"] == first["reply"]
    assert cached["metadata"]["resolution_source"] == "LLM_CACHE"
    assert cached["metadata"]["key_id"] is None
    assert cached["metadata"]["fallback_attempts"] == 0
    assert cached["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert cached["metadata"]["output_tokens"] == first["metadata"]["output_tokens"]
    assert 0 <= cached["metadata"]["latency_ms"] < first["metadata"]["latency_ms"]
    assert different["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert different["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert len(provider.calls) == 2


def test_history_and_prompt_persist_after_restart(client, settings, provider):
    first = chat(client, message="  My city is Pune.  ", system_prompt="Be concise.").json()
    with TestClient(create_app(settings)) as restarted:
        second = chat(restarted, message="What city did I mention?").json()
        assert second["reply"] == "You asked: My city is Pune. / What city did I mention?"
        assert second["metadata"]["input_tokens"] == 38
        assert second["metadata"]["output_tokens"] == 6
        assert provider.calls[-1][1][0] == {"role": "system", "content": "Be concise."}
        history = restarted.get("/sessions/s-original/messages").json()
        assert history == {"session_id": "s-original", "messages": [
            {"role": "user", "content": "My city is Pune."},
            {"role": "assistant", "content": first["reply"], "metadata": first["metadata"]},
            {"role": "user", "content": "What city did I mention?"},
            {"role": "assistant", "content": second["reply"], "metadata": second["metadata"]},
        ]}


def test_system_prompt_and_full_history_participate_in_cache_key(client, provider):
    assert chat(client, session="one", message="Same", system_prompt="First").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert chat(client, session="two", message="Same", system_prompt="Second").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert chat(client, session="three", message="Same", system_prompt="First").json()["metadata"]["resolution_source"] == "LLM_CACHE"
    assert chat(client, session="one", message="Same", system_prompt="").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert provider.calls[-1][1][0]["content"] != "First"
    assert chat(client, session="two", message="Same").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert len(provider.calls) == 4


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_simulation_uses_second_key_even_if_cache_is_warm(client, provider, status):
    assert chat(client).status_code == 200
    response = chat(client, session="simulated", header=f"key_1={status}")
    assert response.status_code == 200
    assert response.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert response.json()["metadata"]["fallback_attempts"] == 1
    assert [key for key, _ in provider.calls] == ["test-first", "test-second"]


@pytest.mark.parametrize("failure", [(429, "rate_limit_exceeded"), (400, "insufficient_quota"), (500, "server_error"), (502, "bad_gateway"), (503, "unavailable")])
def test_router_fails_over_on_upstream_errors(client, provider, failure):
    provider.failures["test-first"] = failure
    response = chat(client)
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert response.json()["metadata"]["fallback_attempts"] == 1
    assert [key for key, _ in provider.calls] == ["test-first", "test-second"]


@pytest.mark.parametrize("header", ["*=429", "key_1=429,key_2=500"])
def test_all_simulated_keys_fail_without_storage(client, provider, header):
    assert chat(client).status_code == 200
    rejected = chat(client, session="s-rejected", header=header)
    assert rejected.status_code == 503
    assert rejected.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-rejected/messages").status_code == 404
    assert chat(client, message="Failed follow-up", header=header, system_prompt="Discard this").status_code == 503
    assert len(client.get("/sessions/s-original/messages").json()["messages"]) == 2
    assert len(provider.calls) == 1


def test_upstream_exhaustion_returns_clean_error(client, provider):
    provider.failures.update({"test-first": (429, "rate_limit_exceeded"), "test-second": (503, "unavailable")})
    response = chat(client)
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-original/messages").status_code == 404
    assert [key for key, _ in provider.calls] == ["test-first", "test-second"]


def test_mixed_simulated_and_upstream_failures_use_third_key(settings, provider):
    provider.failures["test-second"] = (502, "bad_gateway")
    expanded = replace(settings, api_keys=(*settings.api_keys, "test-third"))
    with TestClient(create_app(expanded)) as client:
        response = chat(client, header="key_1=429")
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_3"
    assert response.json()["metadata"]["fallback_attempts"] == 2
    assert [key for key, _ in provider.calls] == ["test-second", "test-third"]


def test_simulation_is_ignored_when_disabled(settings, provider):
    with TestClient(create_app(replace(settings, enable_failure_simulation=False))) as client:
        response = chat(client, header="*=429")
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_1"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("payload", [
    {}, {"session_id": "bad"}, {"session_id": "bad", "message": " \t"},
    {"session_id": "bad", "message": "a" * 4001}, {"session_id": "", "message": "hello"},
    {"session_id": "s" * 129, "message": "hello"}, {"session_id": "bad", "message": 7},
])
def test_invalid_payload_does_not_write(client, provider, payload):
    response = client.post("/chat", json=payload)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert client.get("/sessions/bad/messages").status_code == 404
    assert not provider.calls


def test_malformed_json_and_session_with_encoded_slash(client):
    malformed = client.post("/chat", content="{", headers={"Content-Type": "application/json"})
    assert malformed.status_code == 422
    assert "detail" in malformed.json()
    assert chat(client, session="a/b", message=" " + "x" * 4000 + " ").status_code == 200
    assert client.get("/sessions/a%2Fb/messages").json()["session_id"] == "a/b"


def test_concurrent_requests_preserve_both_turns(client, provider):
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda text: chat(client, message=text), ["One", "Two"]))
    assert all(response.status_code == 200 for response in responses)
    assert [len(messages) for _, messages in provider.calls] == [2, 4]
    assert [row["role"] for row in client.get("/sessions/s-original/messages").json()["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]
