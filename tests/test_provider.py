import asyncio
import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from miniclaudecode.provider import Provider, ProviderError, anthropic_messages, sse_events
from helpers import assistant, tool


class Response(io.BytesIO):
    headers = {"Content-Type": "text/event-stream"}


def stream(*events):
    data = "".join("data: " + (e if isinstance(e, str) else json.dumps(e)) + "\n\n" for e in events)
    return Response(data.encode())


def provider(protocol="openai"):
    return Provider(protocol, "https://example.org/v1", "test-model", "test-only-key")


def test_openai_text_tool_fragments_and_usage():
    response = stream(
        {"choices": [{"delta": {"content": "Inspect "}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_", "arguments": '{"path":'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "file", "arguments": '"app.py"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}, "[DONE]")
    p = provider(); text = []
    with patch("urllib.request.urlopen", return_value=response):
        result = asyncio.run(p.complete([{"role": "user", "content": "read"}], on_text=text.append))
    assert result["tool_calls"][0]["function"] == {"name": "read_file", "arguments": '{"path":"app.py"}'}
    assert "".join(text) == "Inspect "
    assert p.usage == [{"prompt_tokens": 10, "completion_tokens": 5}]


def test_anthropic_streaming_tool_complete_callback():
    response = stream(
        {"type": "message_start", "message": {"usage": {"input_tokens": 20}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "a1", "name": "list_files", "input": {}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{}"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "usage": {"output_tokens": 3}}, {"type": "message_stop"})
    p = provider("anthropic"); ready = []
    with patch("urllib.request.urlopen", return_value=response):
        result = asyncio.run(p.complete([{"role": "user", "content": "list"}], on_tool=ready.append))
    assert ready[0] == result["tool_calls"][0]
    assert p.usage == [{"input_tokens": 20, "output_tokens": 3}]


def test_anthropic_conversion_groups_tool_results():
    a, b = tool("read_file", path="a"), tool("read_file", path="b")
    b["id"] = "b"
    system, messages = anthropic_messages([
        {"role": "system", "content": "rules"}, {"role": "user", "content": "read"}, assistant(a,b),
        {"role": "tool", "tool_call_id": a["id"], "content": "a"},
        {"role": "tool", "tool_call_id": b["id"], "content": "b"}])
    assert system == "rules" and len(messages[-1]["content"]) == 2
    assert messages[-1]["content"][0]["type"] == "tool_result"


def test_retry_before_any_output():
    error = urllib.error.HTTPError("https://example.org", 429, "rate limit", {}, None)
    response = stream({"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}, "[DONE]")
    p = provider()
    with patch("urllib.request.urlopen", side_effect=[error,response]) as call, patch("time.sleep"):
        result = asyncio.run(p.complete([{"role": "user", "content": "hi"}]))
    assert result["content"] == "done" and call.call_count == 2


def test_partial_stream_never_replayed():
    response = stream({"choices": [{"delta": {"content": "partial"}}]})
    with patch("urllib.request.urlopen", return_value=response) as call:
        with pytest.raises(ProviderError, match="Incomplete"):
            asyncio.run(provider().complete([{"role": "user", "content": "hi"}]))
    assert call.call_count == 1


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
def test_real_request_protocol_headers(protocol):
    p = provider(protocol)
    request = p.request([{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}], [])
    payload = json.loads(request.data)
    assert payload["stream"] and payload["temperature"] == 0
    if protocol == "openai":
        assert request.get_header("Authorization") == "Bearer test-only-key"
    else:
        assert request.get_header("X-api-key") == "test-only-key"
        assert payload["system"] == "rules"


def test_deepseek_disables_reasoning():
    p = Provider("openai", "https://api.deepseek.com", "deepseek-flash", "test-only-key")
    assert json.loads(p.request([{"role": "user", "content": "hi"}], []).data)["thinking"]["type"] == "disabled"
