import json


def tool(name, **args):
    return {"id": "call_" + name, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def assistant(*calls, text=None):
    return {"role": "assistant", "content": text, "tool_calls": list(calls)}


class FakeProvider:
    """Test fixture only: never exposed as the project's CLI/backend."""
    def __init__(self, answers=(), **kwargs):
        self.answers = list(answers)
        self.usage = []
        self.requests = 0
        self.messages = []

    async def complete(self, messages, tools=(), on_text=None, on_tool=None):
        self.requests += 1
        self.messages.append(messages)
        if self.answers:
            response = self.answers.pop(0)
        else:
            response = assistant(text="Preserved task, paths, constraints, failures and next actions.")
        if on_text and response.get("content"):
            on_text(response["content"])
        return response
