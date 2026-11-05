from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from app.services.hermes_ai_service import (
    HermesCancelledError,
    HermesResponseError,
    reset_hermes_circuit,
    stream_hermes_chat,
)


class FakeResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None) -> None:
        self.chunks = chunks
        self.headers = headers or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def __iter__(self):
        return iter(self.chunks)

    def close(self) -> None:
        self.closed = True


class SlowResponse(FakeResponse):
    def __iter__(self):
        time.sleep(0.04)
        return super().__iter__()


def _data(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _settings():
    return (
        patch("app.services.hermes_ai_service.settings.hermes_api_base_url", "https://provider.invalid/v1"),
        patch("app.services.hermes_ai_service.settings.hermes_api_key", "test-key"),
        patch("app.services.hermes_ai_service.settings.hermes_model", "GLM-5.2"),
        patch("app.services.hermes_ai_service.settings.hermes_request_timeout_seconds", 30),
    )


def test_stream_parses_fragmented_utf8_deltas_usage_and_done() -> None:
    reset_hermes_circuit()
    first = _data({"choices": [{"delta": {"content": "库存异常"}}]})
    split_at = first.index("库".encode()) + 1
    response = FakeResponse(
        [
            first[:split_at],
            first[split_at:],
            _data({"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}}),
            b"data: [DONE]\n\n",
        ],
        {"x-request-id": "provider/request-1"},
    )
    patches = _settings()
    with patches[0], patches[1], patches[2], patches[3], patch(
        "app.services.hermes_ai_service.urlopen", return_value=response
    ):
        events = list(stream_hermes_chat([{"role": "user", "content": "test"}]))
    assert events == [
        {"type": "metadata", "provider_request_id": "provider/request-1"},
        {"type": "delta", "text": "库存异常"},
        {"type": "usage", "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}},
        {"type": "done"},
    ]
    assert response.closed is True


@pytest.mark.parametrize(
    "chunks",
    [
        [_data({"choices": [{"delta": {"content": "有内容"}}]})],
        [b"data: {not-json}\n\n", b"data: [DONE]\n\n"],
        [b"data: \xff\n\n", b"data: [DONE]\n\n"],
    ],
)
def test_stream_rejects_missing_done_malformed_json_and_invalid_utf8(chunks: list[bytes]) -> None:
    reset_hermes_circuit()
    patches = _settings()
    with patches[0], patches[1], patches[2], patches[3], patch(
        "app.services.hermes_ai_service.urlopen", return_value=FakeResponse(chunks)
    ):
        with pytest.raises(HermesResponseError):
            list(stream_hermes_chat([{"role": "user", "content": "test"}]))


def test_stream_cancellation_closes_provider_response() -> None:
    reset_hermes_circuit()
    response = FakeResponse([_data({"choices": [{"delta": {"content": "第一段"}}]}), b"data: [DONE]\n\n"])
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    patches = _settings()
    with patches[0], patches[1], patches[2], patches[3], patch(
        "app.services.hermes_ai_service.urlopen", return_value=response
    ):
        with pytest.raises(HermesCancelledError):
            list(stream_hermes_chat([{"role": "user", "content": "test"}], cancel_requested=cancelled))
    assert response.closed is True


def test_stream_emits_heartbeat_while_provider_is_idle() -> None:
    reset_hermes_circuit()
    response = SlowResponse([_data({"choices": [{"delta": {"content": "延迟回答"}}]}), b"data: [DONE]\n\n"])
    patches = _settings()
    with patches[0], patches[1], patches[2], patches[3], patch(
        "app.services.hermes_ai_service._CHAT_STREAM_HEARTBEAT_SECONDS", 0.01
    ), patch("app.services.hermes_ai_service.urlopen", return_value=response):
        events = list(stream_hermes_chat([{"role": "user", "content": "test"}]))
    assert {"type": "heartbeat"} in events
    assert events[-1] == {"type": "done"}
