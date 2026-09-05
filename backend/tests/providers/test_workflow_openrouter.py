from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from interview_api.workflow.errors import WorkflowProviderError
from interview_api.workflow.openrouter import OpenRouterWorkflowAI


class Response:
    def __init__(self, payload: dict, *, status: int = 200, retry_after: str | None = None):
        self.status = status
        self.data = json.dumps(payload).encode()
        self.headers = {"Retry-After": retry_after} if retry_after is not None else {}


class Pool:
    def __init__(self, responses: list[Response]):
        self.responses = iter(responses)
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return next(self.responses)


def gateway(pool, *, retries: int = 3) -> OpenRouterWorkflowAI:
    return OpenRouterWorkflowAI(
        api_key="test-key", chat_model="openai/gpt-5.6-luna", stt_model="stt", tts_model="tts",
        pool=pool, max_retries=retries,
    )


def completion() -> Response:
    return Response({"choices": [{"message": {"content": '{"text":"Company context"}'}}]})


@pytest.mark.parametrize("http_status", [200, 429])
def test_rate_limit_body_retries_before_structured_output_parsing(monkeypatch, http_status):
    pool = Pool([
        Response({"error": {"code": 429}}, status=http_status, retry_after="7"),
        completion(),
    ])
    delays = []
    monkeypatch.setattr("interview_api.workflow.openrouter.time.sleep", delays.append)
    value, _ = asyncio.run(gateway(pool)._chat_json(
        schema_name="company_context_section", schema={"type": "object"}, system="Test", user={},
    ))
    assert value == {"text": "Company context"}
    assert pool.calls == 2
    assert delays == [7.0]


def test_http_200_rate_limit_exhaustion_preserves_cause_without_upstream_content(monkeypatch):
    pool = Pool([Response({"error": {"code": 429, "message": "PRIVATE DOCUMENT"}})] * 4)
    delays = []
    monkeypatch.setattr("interview_api.workflow.openrouter.time.sleep", delays.append)
    with pytest.raises(WorkflowProviderError) as caught:
        gateway(pool)._request("chat/completions", b"{}", {})
    assert caught.value.details == {"status": 429, "endpoint": "chat/completions"}
    assert "PRIVATE DOCUMENT" not in str(caught.value)
    assert "invalid structured output" not in str(caught.value)
    assert pool.calls == 4
    assert delays == [5.0, 10.0, 20.0]


@pytest.mark.parametrize("code", [400, 401, 402, 403])
def test_permanent_error_inside_http_200_is_not_retried(code):
    pool = Pool([Response({"error": {"code": code}})])
    with pytest.raises(WorkflowProviderError) as caught:
        gateway(pool)._request("chat/completions", b"{}", {})
    assert caught.value.details["status"] == code
    assert pool.calls == 1


def test_http_200_provider_error_retries_for_pdf_path_too(monkeypatch):
    pool = Pool([Response({"error": {"code": "503"}}), completion()])
    monkeypatch.setattr("interview_api.workflow.openrouter.time.sleep", lambda _: None)
    response = gateway(pool)._request("chat/completions", b'{"plugins":[{"id":"file-parser"}]}', {})
    assert "choices" in json.loads(response.data)
    assert pool.calls == 2


@pytest.mark.parametrize("pdf", [False, True])
def test_luna_routing_keeps_schema_privacy_and_document_settings(pdf):
    body = {
        "model": "openai/gpt-5.6-luna",
        "provider": {"require_parameters": True, "data_collection": "deny", "zdr": True},
        "response_format": {"type": "json_schema"},
    }
    if pdf:
        body["plugins"] = [{"id": "file-parser"}]

    class InspectingPool:
        def request(self, *args, **kwargs):
            sent = json.loads(kwargs["body"])
            assert sent["provider"].pop("order") == ["openai", "azure/eu"]
            assert sent == body
            return completion()

    gateway(InspectingPool())._request("chat/completions", json.dumps(body).encode(), {})


@pytest.mark.parametrize("value", ["garbage", "NaN", "Infinity", "-1"])
def test_invalid_retry_after_uses_bounded_backoff(value):
    assert OpenRouterWorkflowAI._retry_delay(Response({}, retry_after=value), 2.0) == 2.0


def test_chat_fanout_is_limited_across_the_shared_gateway():
    release = Event()
    first_started = Event()
    second_started = Event()
    lock = Lock()

    class ConcurrentPool:
        active = 0
        maximum = 0

        def request(self, *args, **kwargs):
            with lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                first_started.set()
                if self.active > 1:
                    second_started.set()
            try:
                assert release.wait(5)
                return completion()
            finally:
                with lock:
                    self.active -= 1

    pool = ConcurrentPool()
    ai = gateway(pool)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(ai._request, "chat/completions", b"{}", {}) for _ in range(6)]
        try:
            assert first_started.wait(5)
            assert not second_started.wait(0.1)
        finally:
            release.set()
        assert all(future.result().status == 200 for future in futures)
    assert pool.maximum == 1
