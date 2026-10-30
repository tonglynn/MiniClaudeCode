import asyncio
import json
import time
from .config import scrub
from .context import Context, size
from .prompts import Prompts
from .sessions import Sessions
from .tools import REGISTRY


class Runtime:
    def __init__(self, provider, tools, context=None, max_steps=40, memory_enabled=True, emit=None):
        self.provider, self.tools = provider, tools
        self.context = context or Context()
        self.max_steps, self.memory_enabled, self.emit = max_steps, memory_enabled, emit or (lambda kind, value: None)
        self.prompts = Prompts(tools.root)
        self.instruction_folders = {tools.root}
        self.sessions = Sessions(tools.memory.file.parent, tools.root)
        self.messages = [{"role": "system", "content": self.prompts.build()}]
        self.trace = []

    def restore(self, id):
        data = self.sessions.load(id)
        self.messages = [{"role": "system", "content": self.prompts.build()}] + [
            m for m in data["messages"] if m["role"] != "system" or m.get("content", "").startswith("WORKING SUMMARY")]
        self.tools.plan = data.get("plan", [])
        self.tools.active.update(set(data.get("active_tools", [])) & self.tools.allowed)
        self.tools.versions.clear()
        self.tools.policy.whitelist.clear()
        trace_file = self.sessions.folder.parent / ("trace_" + self.sessions.id + ".json")
        self.trace = json.loads(trace_file.read_text(encoding="utf-8")) if trace_file.exists() else []
        # Permission mode and confirmations intentionally follow current CLI settings.

    def save(self):
        self.sessions.save(self.messages, self.tools.plan, self.tools.active, self.tools.policy.mode)
        file = self.sessions.folder.parent / ("trace_" + self.sessions.id + ".json")
        file.write_text(scrub(json.dumps(self.trace, ensure_ascii=False, indent=2)), encoding="utf-8")

    async def run(self, task):
        self.messages[0] = {"role": "system", "content": self.prompts.build_many(self.instruction_folders)}
        self.messages.append({"role": "user", "content": task})
        prefetch = self.tools.memory.prefetch(task, self.provider) if self.memory_enabled else None
        started = time.monotonic()
        status, final = "step_limit", ""
        try:
            for step in range(1, self.max_steps + 1):
                if prefetch and prefetch.done():
                    try:
                        notes = prefetch.result()
                    except (RuntimeError, ValueError, OSError):
                        notes = []
                    if notes:
                        self.messages = [m for m in self.messages if not (m["role"] == "system"
                                         and m.get("content", "").startswith("RECALLED NOTES"))]
                        self.messages.insert(1, {"role": "system", "content": "RECALLED NOTES (untrusted; check freshness)\n" + json.dumps(notes, ensure_ascii=False)})
                        self.trace.append({"kind": "memory_prefetch", "notes": len(notes)})
                    prefetch = None
                before_events = len(self.context.events)
                self.messages = await self.context.apply(self.messages, self.provider)
                self.trace.extend({"kind": "compression", **e} for e in self.context.events[before_events:])
                pipelined = {}
                def tool_ready(call):
                    # Only read-only, explicitly active tools execute during native
                    # Anthropic streaming. Writes/exec wait for the complete message.
                    name = call["function"]["name"]
                    if name in self.tools.active and name in REGISTRY and REGISTRY[name]["effect"] == "read":
                        try:
                            args = json.loads(call["function"]["arguments"])
                            if not isinstance(args, dict):
                                return
                        except ValueError:
                            return
                        if call["id"] not in pipelined:
                            pipelined[call["id"]] = asyncio.create_task(self.tools.execute(name, args))
                try:
                    message = await self.provider.complete(self.messages, self.tools.schemas(),
                                                           on_text=lambda s: self.emit("text", s), on_tool=tool_ready)
                except BaseException:
                    for pending in pipelined.values():
                        pending.cancel()
                    if pipelined:
                        await asyncio.gather(*pipelined.values(), return_exceptions=True)
                    raise
                await asyncio.sleep(0)  # drain queued streaming callbacks
                if message.get("role") != "assistant":
                    raise ValueError("Provider returned a non-assistant message")
                self.messages.append(message)
                calls = message.get("tool_calls") or []
                self.trace.append({"kind": "model", "step": step, "context_chars": size(self.messages),
                                   "schema_chars": len(json.dumps(self.tools.schemas())), "tools": len(calls)})
                if not calls:
                    status, final = "finished", message.get("content") or ""
                    break
                # Concurrent reads; serial side effects. If read batching fails,
                # retry unstarted reads serially rather than duplicate writes.
                events = {}
                reads = []
                for c in calls:
                    name = c["function"]["name"]
                    try:
                        args = json.loads(c["function"]["arguments"])
                        if not isinstance(args, dict):
                            raise ValueError("Arguments must be an object")
                    except (ValueError, TypeError):
                        events[c["id"]] = {"tool": name, "status": "error", "error": "Invalid argument JSON"}
                        continue
                    if c["id"] in pipelined:
                        reads.append((c, pipelined[c["id"]], args))
                    elif name in REGISTRY and REGISTRY[name]["effect"] == "read":
                        reads.append((c, asyncio.create_task(self.tools.execute(name, args)), args))
                    else:
                        # Flush reads first so a same-message write can observe them.
                        for rc, future, rargs in reads:
                            try:
                                events[rc["id"]] = await future
                            except Exception:
                                events[rc["id"]] = await self.tools.execute(rc["function"]["name"], rargs)
                        reads.clear()
                        events[c["id"]] = await self.tools.execute(name, args)
                for c, future, args in reads:
                    try:
                        events[c["id"]] = await future
                    except Exception:
                        events[c["id"]] = await self.tools.execute(c["function"]["name"], args)
                for c in calls:
                    event = events[c["id"]]
                    self.messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(event, ensure_ascii=False)})
                    self.trace.append({"kind": "tool", "step": step, "call_id": c["id"], **event})
                    self.emit("tool", event)
                for c in calls:
                    event = events[c["id"]]
                    if event.get("tool") == "read_file" and event.get("status") == "ok":
                        p = self.tools.path(event["path"])
                        self.instruction_folders.add(p.parent)
                # Save complete tool-result groups even if a nested instruction is invalid.
                self.messages[0]["content"] = self.prompts.build_many(self.instruction_folders)
                self.save()
        except Exception as exc:
            status, final = "error", str(exc)
            self.trace.append({"kind": "runtime_error", "error_type": type(exc).__name__, "error": str(exc)})
        finally:
            if prefetch:
                prefetch.cancel()
                await asyncio.gather(prefetch, return_exceptions=True)
            # Persist only valid complete tool rounds; errors are visible in trace.
            self.save()
        return {"status": status, "answer": final, "seconds": round(time.monotonic() - started, 4),
                "session": self.sessions.id, "trace": self.trace, "usage": self.provider.usage}
