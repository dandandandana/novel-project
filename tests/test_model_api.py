from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from novel_rag.model_api import ModelAPIError, OpenAICompatibleModel


class FakeResponse:
    def __init__(self, value: dict):
        self.data = json.dumps(value, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int) -> bytes:
        return self.data[:size]


def test_responses_api_request_and_json_output() -> None:
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["auth"] = request.get_header("Authorization")
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"output_text": '{"status":"pass"}'})

    model = OpenAICompatibleModel(
        "https://example.test/v1", "writer", api_key="secret", opener=opener, sleeper=lambda _delay: None
    )
    result = model("validate", {"instruction": "check", "text": "正文"})

    assert result == {"status": "pass"}
    assert seen["url"] == "https://example.test/v1/responses"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"]["model"] == "writer"
    assert '"stage":"validate"' in seen["body"]["input"]


def test_chat_api_supports_content_parts_and_json_mode() -> None:
    seen = {}

    def opener(request, timeout):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({
            "choices": [{"message": {"content": [{"type": "text", "text": "```json\n"},
                                                      {"type": "text", "text": '{"outline":"ok"}\n```'}]}}]
        })

    model = OpenAICompatibleModel(
        "http://localhost:1234/v1", "local", mode="chat", opener=opener, sleeper=lambda _delay: None
    )
    assert model("normalize", {"instruction": "normalize"}) == {"outline": "ok"}
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_retryable_http_error_retries_without_exposing_body() -> None:
    attempts = 0

    def opener(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(request.full_url, 429, "limited", {}, io.BytesIO(b"sensitive response"))
        return FakeResponse({"output_text": "正文"})

    model = OpenAICompatibleModel(
        "http://localhost:1234/v1", "local", retries=1, opener=opener, sleeper=lambda _delay: None
    )
    assert model("render_prose", {"instruction": "write"}) == "正文"
    assert attempts == 2


def test_non_object_json_model_output_is_rejected() -> None:
    model = OpenAICompatibleModel(
        "http://localhost:1234/v1", "local",
        opener=lambda *_args, **_kwargs: FakeResponse({"output_text": "[1, 2]"}),
    )
    with pytest.raises(ModelAPIError, match="必须是对象"):
        model("validate", {"instruction": "check"})
def test_model_repr_does_not_expose_api_key() -> None:
    model = OpenAICompatibleModel(base_url="http://localhost/v1", model="writer", api_key="SECRET")
    assert "SECRET" not in repr(model)


