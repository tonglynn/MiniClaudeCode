"""OpenAI/Anthropic native messages, SSE text/tool deltas and bounded retries."""
import asyncio
import json
import random
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


class ProviderError(RuntimeError):
    pass


def anthropic_messages(messages):
    system, result = [], []
    for m in messages:
        role = m["role"]
        if role == "system":
            system.append(m.get("content") or "")
            continue
        if role == "tool":
            blocks = [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}]
            role = "user"
        elif role == "assistant":
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for c in m.get("tool_calls", []):
                blocks.append({"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                               "input": json.loads(c["function"]["arguments"])})
        else:
            blocks = [{"type": "text", "text": m.get("content") or " "}]
        if not blocks:
            blocks = [{"type": "text", "text": " "}]
        if result and result[-1]["role"] == role:
            result[-1]["content"].extend(blocks)
        else:
            result.append({"role": role, "content": blocks})
    return "\n\n".join(system), result


def sse_events(lines):
    data = []
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n") if isinstance(raw, bytes) else raw.rstrip("\r\n")
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield "\n".join(data)


class Provider:
    def __init__(self, protocol, base_url, model, api_key, retries=3, timeout=90):
        if protocol not in ("openai", "anthropic"):
            raise ValueError("protocol must be openai or anthropic")
        if not api_key or not base_url.startswith("https://"):
            raise ValueError("Configure an API key and HTTPS base URL")
        self.protocol, self.base, self.model = protocol, base_url.rstrip("/"), model
        self.key, self.retries, self.timeout = api_key, retries, timeout
        self.usage, self.requests = [], 0

    def request(self, messages, tools, stream=True):
        headers = {"Content-Type": "application/json"}
        if self.protocol == "openai":
            url = self.base + "/chat/completions"
            headers["Authorization"] = "Bearer " + self.key
            payload = {"model": self.model, "messages": messages, "stream": stream, "temperature": 0,
                       "max_tokens": 4096}
            if tools:
                payload["tools"] = tools
            if stream:
                payload["stream_options"] = {"include_usage": True}
        else:
            url = self.base + "/messages"
            headers.update({"x-api-key": self.key, "anthropic-version": "2023-06-01"})
            system, converted = anthropic_messages(messages)
            payload = {"model": self.model, "system": system, "messages": converted,
                       "max_tokens": 4096, "stream": stream, "temperature": 0}
            if tools:
                payload["tools"] = [{"name": t["function"]["name"],
                                     "description": t["function"]["description"],
                                     "input_schema": t["function"]["parameters"]} for t in tools]
        if urlparse(self.base).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}
        return urllib.request.Request(url, json.dumps(payload).encode(), headers=headers)

    async def complete(self, messages, tools=(), on_text=None, on_tool=None):
        loop = asyncio.get_running_loop()
        def text_callback(s):
            if on_text:
                loop.call_soon_threadsafe(on_text, s)
        def tool_callback(c):
            if on_tool:
                loop.call_soon_threadsafe(on_tool, c)
        return await asyncio.to_thread(self._complete, messages, tools, text_callback, tool_callback)

    def _complete(self, messages, tools, on_text, on_tool):
        req = self.request(messages, tools)
        for attempt in range(self.retries):
            emitted = [False]
            def text(s):
                emitted[0] = True
                on_text(s)
            def tool(c):
                emitted[0] = True
                on_tool(c)
            try:
                self.requests += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    if "text/event-stream" not in response.headers.get("Content-Type", ""):
                        obj = json.load(response)
                        return self._nonstream(obj, text)
                    return self._stream(response, text, tool)
            except urllib.error.HTTPError as exc:
                retryable = exc.code in (408, 409, 429) or exc.code >= 500
                if not retryable or attempt + 1 == self.retries or emitted[0]:
                    raise ProviderError(f"HTTP {exc.code}; request failed") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                # A streamed tool may already have executed: never replay that request.
                if emitted[0] or attempt + 1 == self.retries:
                    raise ProviderError(f"Network error ({type(exc).__name__}); not replayed") from None
            time.sleep(min(8, 2 ** attempt) + random.uniform(0, .25))
        raise ProviderError("Retry budget exhausted")

    def _nonstream(self, obj, on_text):
        self.usage.append(obj.get("usage", {}))
        if self.protocol == "openai":
            msg = obj["choices"][0]["message"]
            result = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
        else:
            content = "".join(x["text"] for x in obj["content"] if x["type"] == "text")
            calls = [{"id": x["id"], "type": "function", "function": {
                "name": x["name"], "arguments": json.dumps(x["input"])}}
                for x in obj["content"] if x["type"] == "tool_use"]
            result = {"role": "assistant", "content": content, "tool_calls": calls}
        if result.get("content"):
            on_text(result["content"])
        return result

    def _stream(self, response, on_text, on_tool):
        content, calls, usage = [], {}, {}
        ended = False
        for event in sse_events(response):
            if event == "[DONE]":
                ended = True
                break
            obj = json.loads(event)
            if self.protocol == "openai":
                if obj.get("error"):
                    raise ProviderError("Provider reported a streaming error")
                if obj.get("usage"):
                    usage.update(obj["usage"])
                for choice in obj.get("choices", []):
                    delta = choice.get("delta", {})
                    if delta.get("content"):
                        content.append(delta["content"]); on_text(delta["content"])
                    for fragment in delta.get("tool_calls", []):
                        c = calls.setdefault(fragment["index"], {"id": "", "type": "function",
                                                               "function": {"name": "", "arguments": ""}})
                        c["id"] += fragment.get("id", "")
                        for key in ("name", "arguments"):
                            c["function"][key] += fragment.get("function", {}).get(key, "")
                    if choice.get("finish_reason"):
                        ended = True
            else:
                typ = obj.get("type")
                if typ == "error":
                    raise ProviderError("Anthropic stream reported an error")
                if typ == "message_start":
                    usage.update(obj.get("message", {}).get("usage", {}))
                if typ == "message_delta":
                    usage.update(obj.get("usage", {}))
                if typ == "message_stop":
                    ended = True
                if typ == "content_block_start" and obj["content_block"]["type"] == "tool_use":
                    b = obj["content_block"]
                    calls[obj["index"]] = {"id": b["id"], "type": "function",
                                           "function": {"name": b["name"], "arguments": ""}}
                if typ == "content_block_delta":
                    delta = obj["delta"]
                    if delta["type"] == "text_delta":
                        content.append(delta["text"]); on_text(delta["text"])
                    elif delta["type"] == "input_json_delta":
                        calls[obj["index"]]["function"]["arguments"] += delta["partial_json"]
                if typ == "content_block_stop" and obj["index"] in calls:
                    c = calls[obj["index"]]
                    if not c["function"]["arguments"]:
                        c["function"]["arguments"] = "{}"
                    on_tool(c)
        if not ended:
            raise ProviderError("Incomplete SSE stream; request not replayed")
        self.usage.append(usage)
        return {"role": "assistant", "content": "".join(content) or None,
                "tool_calls": [calls[k] for k in sorted(calls)]}
