import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from miniclaudecode.context import Context, size
from miniclaudecode.memory import Memory
from miniclaudecode.permissions import Policy, Denied, DANGEROUS, MODES
from miniclaudecode.prompts import Prompts
from miniclaudecode.runtime import Runtime
from miniclaudecode.sessions import Sessions
from miniclaudecode.tools import Tools, REGISTRY
from helpers import FakeProvider, assistant, tool


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def tools(tmp_path):
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    return Tools(tmp_path, Policy("auto"), Memory(tmp_path / ".miniclaude"))


def test_13_tools_and_deferred_discovery(tools):
    assert len(REGISTRY) == 13 and len(tools.schemas()) == 5
    assert run(tools.execute("search_text", {"query": "value"}))["status"] == "blocked"
    found = run(tools.execute("discover_tools", {"query": "search_text"}))
    assert found["result"]["activated"] == ["search_text"]
    assert run(tools.execute("search_text", {"query": "value"}))["result"][0]["line"] == 1


@pytest.mark.parametrize("path", ["../outside.txt", ".provider_private.json", ".miniclaude/memory.sqlite3", ".env", ".env.local"])
def test_protected_paths(tools, path):
    assert run(tools.execute("read_file", {"path": path}))["status"] == "blocked"


def test_current_read_and_syntax_validation(tools):
    assert run(tools.execute("write_file", {"path": "app.py", "content": "value = 2"}))["status"] == "error"
    run(tools.execute("read_file", {"path": "app.py"}))
    (tools.root / "app.py").write_text("value = 3", encoding="utf-8")
    assert run(tools.execute("write_file", {"path": "app.py", "content": "value = 2"}))["status"] == "error"
    run(tools.execute("read_file", {"path": "app.py"}))
    assert run(tools.execute("write_file", {"path": "app.py", "content": "def invalid("}))["status"] == "error"
    assert (tools.root / "app.py").read_text() == "value = 3"
    assert run(tools.execute("write_file", {"path": "app.py", "content": "value = 2"}))["status"] == "ok"


def test_contract_protects_tests_from_edits(tools):
    tools.editable_paths = ["app.py"]
    assert run(tools.execute("write_file", {"path": "test_app.py", "content": "assert True"}))["status"] == "blocked"
    assert not (tools.root / "test_app.py").exists()


def test_combined_directory_instructions(tmp_path):
    folders = [tmp_path / "a", tmp_path / "b"]
    for folder in folders:
        folder.mkdir()
        (folder / "CLAUDE.md").write_text("rule for " + folder.name, encoding="utf-8")
    prompt = Prompts(tmp_path).build_many(folders)
    assert "rule for a" in prompt and "rule for b" in prompt


def test_edit_exact_once_and_revalidation(tools):
    run(tools.execute("discover_tools", {"query": "edit_file"}))
    run(tools.execute("read_file", {"path": "app.py"}))
    assert run(tools.execute("edit_file", {"path": "app.py", "old": "value = 1", "new": "value = 2"}))["status"] == "ok"
    assert run(tools.execute("edit_file", {"path": "app.py", "old": "value = 2", "new": "value = 3"}))["status"] == "error"


@pytest.mark.parametrize("name,args", [("missing", {}), ("read_file", {}), ("read_file", {"path": 1}),
                                     ("read_file", {"path": "app.py", "start": True}), ("list_files", None)])
def test_tool_argument_validation(tools, name, args):
    assert run(tools.execute(name, args))["status"] in ("error", "blocked")


@pytest.mark.parametrize("mode", MODES)
def test_five_modes(mode):
    async def check():
        policy = Policy(mode)
        await policy.check("read_file", {"path": "a"}, "read")
        if mode in ("auto", "auto_edit"):
            await policy.check("write_file", {"path": "a", "content": "x"}, "write")
        else:
            with pytest.raises(Denied):
                await policy.check("write_file", {"path": "a", "content": "x"}, "write")
    run(check())


def test_confirm_whitelist_and_deny_precedence():
    answers = []
    async def confirm(name, args):
        answers.append(name); return "always"
    async def exercise():
        p = Policy("ask", confirm=confirm)
        await p.check("write_file", {"path": "a"}, "write")
        await p.check("write_file", {"path": "a"}, "write")
        assert len(answers) == 1
        p.rules["deny"] = ["write_file:*"]
        with pytest.raises(Denied):
            await p.check("write_file", {"path": "a"}, "write")
    run(exercise())


def test_command_allowlist_and_environment(tools):
    run(tools.execute("discover_tools", {"query": "run_command"}))
    assert run(tools.execute("run_command", {"argv": ["cmd", "/c", "echo", "x"]}))["status"] == "blocked"
    with patch.dict(os.environ, {"LLM_API_KEY": "test-secret"}), patch("subprocess.run") as sub:
        sub.return_value.returncode = 0
        sub.return_value.stdout = "ok"; sub.return_value.stderr = ""
        run(tools.execute("run_tests", {}))
        assert "LLM_API_KEY" not in sub.call_args.kwargs["env"]


def test_semantic_memory_cache_and_freshness(tools):
    tools.memory.put("db", "Use PostgreSQL transactions for account transfers")
    provider = FakeProvider([assistant(text='{"query":"database financial atomicity"}'), assistant(text='{"keys":["db"]}')])
    async def exercise():
        recalled = await tools.memory.recall("prevent partial payment", provider)
        assert recalled[0]["method"] == "llm_semantic_sidequery" and recalled[0]["key"] == "db"
        await tools.memory.recall("prevent partial payment", provider)
        assert provider.requests == 2
    run(exercise())
    assert Memory(tools.memory.file.parent).all()[0]["key"] == "db"


def test_hierarchical_include_and_cycles(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "CLAUDE.md").write_text("root\n@include shared.md", encoding="utf-8")
    (tmp_path / "shared.md").write_text("shared rule", encoding="utf-8")
    (tmp_path / "src/CLAUDE.md").write_text("child rule", encoding="utf-8")
    rules = tmp_path / ".agent/rules"; rules.mkdir(parents=True)
    (rules / "style.md").write_text("style rule", encoding="utf-8")
    prompt = Prompts(tmp_path).build(tmp_path / "src")
    assert all(x in prompt for x in ("root", "shared rule", "child rule", "style rule"))
    (tmp_path / "shared.md").write_text("@include CLAUDE.md", encoding="utf-8")
    with pytest.raises(ValueError, match="Cyclic"):
        Prompts(tmp_path).build()


def test_include_cannot_read_secret_or_leave_workspace(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("@include .provider_private.json", encoding="utf-8")
    (tmp_path / ".provider_private.json").write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="Markdown"):
        Prompts(tmp_path).build()
    (tmp_path / "CLAUDE.md").write_text("@include ../outside.md", encoding="utf-8")
    with pytest.raises(ValueError, match="leaves"):
        Prompts(tmp_path).build()


def test_session_restore_follows_current_policy(tools):
    provider = FakeProvider([assistant(text="done")])
    runtime = Runtime(provider, tools, memory_enabled=False)
    run(runtime.run("inspect"))
    id = runtime.sessions.id
    tools.policy.mode = "read_only"
    tools.policy.whitelist.add("old-confirmation")
    restored = Runtime(provider, tools)
    restored.restore(id)
    assert tools.policy.mode == "read_only"
    assert not tools.policy.whitelist and not tools.versions
    assert restored.trace
    assert restored.messages[-1]["content"] == "done"
    with pytest.raises(ValueError):
        restored.sessions.load("../escape")


def test_runtime_real_tool_cycle(tools):
    provider = FakeProvider([
        assistant(tool("read_file", path="app.py")),
        assistant(tool("write_file", path="app.py", content="value = 9\n")),
        assistant(text="Edited app.py")])
    runtime = Runtime(provider, tools, memory_enabled=False)
    result = run(runtime.run("change value to 9"))
    assert result["status"] == "finished"
    assert (tools.root / "app.py").read_text().strip() == "value = 9"
    assert len([e for e in result["trace"] if e["kind"] == "tool"]) == 2


def test_invalid_nested_instructions_do_not_orphan_tool_results(tools):
    folder = tools.root / "nested"; folder.mkdir()
    (folder / "app.py").write_text("value = 1", encoding="utf-8")
    (folder / "CLAUDE.md").write_text("@include CLAUDE.md", encoding="utf-8")
    a = tool("read_file", path="nested/app.py")
    b = tool("list_files")
    runtime = Runtime(FakeProvider([assistant(a,b)]), tools, memory_enabled=False)
    result = run(runtime.run("read nested file and list files"))
    assert result["status"] == "error"
    supplied = {m["tool_call_id"] for m in runtime.messages if m["role"] == "tool"}
    assert {a["id"],b["id"]}.issubset(supplied)


def test_anthropic_read_starts_before_stream_finishes(tools):
    class StreamProvider(FakeProvider):
        async def complete(self, messages, schemas=(), on_text=None, on_tool=None):
            if self.requests:
                return assistant(text="done")
            self.requests += 1
            c = tool("read_file", path="app.py")
            on_tool(c)
            for _ in range(100):
                if tools.events:
                    break
                await asyncio.sleep(.001)
            assert tools.events, "tool should execute while response is still streaming"
            return assistant(c)
    result = run(Runtime(StreamProvider(), tools, memory_enabled=False).run("read"))
    assert result["status"] == "finished"
    assert len(tools.events) == 1


def test_async_prefetch_overlaps_main_request_and_injects_notes(tools):
    tools.memory.put("db", "Use transactions for atomic financial updates")
    async def exercise():
        started, ranked = asyncio.Event(), asyncio.Event()
        class SemanticProvider(FakeProvider):
            async def complete(self, messages, schemas=(), on_text=None, on_tool=None):
                system = messages[0]["content"]
                if system.startswith("Generate a short semantic"):
                    await started.wait()
                    return assistant(text='{"query":"database transactions"}')
                if system.startswith("Rank stored notes"):
                    ranked.set()
                    return assistant(text='{"keys":["db"]}')
                if not started.is_set():
                    started.set()
                    await ranked.wait()
                    return assistant(tool("read_file", path="app.py"))
                assert any(m["content"].startswith("RECALLED NOTES") for m in messages if m["role"] == "system")
                return assistant(text="done")
        result = await Runtime(SemanticProvider(), tools).run("avoid partial money update")
        assert result["status"] == "finished"
        assert any(e["kind"] == "memory_prefetch" for e in result["trace"])
    run(exercise())


def test_cli_slash_session_flow_without_model_calls(tmp_path):
    from argparse import Namespace
    from miniclaudecode.__main__ import run_cli
    args = Namespace(workspace=str(tmp_path), protocol=None, mode="ask", eager_tools=False,
                     no_read_before_edit=False, no_compression=False, no_memory=False,
                     context_chars=48000, max_steps=10, resume=None, task=None)
    with patch("miniclaudecode.__main__.Provider", return_value=FakeProvider()), \
         patch("miniclaudecode.__main__.Prompt.ask", side_effect=["/mode plan", "/plan", "/new", "/sessions", "/save", "/exit"]):
        assert run(run_cli(args)) == 0
    assert len(list((tmp_path / ".miniclaude/sessions").glob("*.json"))) == 2


def test_read_batch_fallback_does_not_duplicate_writes(tools):
    real = tools.execute
    calls = {"read": 0, "write": 0}
    async def flaky(name, args):
        if name == "read_file":
            calls["read"] += 1
            if calls["read"] == 1:
                raise RuntimeError("temporary read scheduling failure")
        if name == "write_file":
            calls["write"] += 1
        return await real(name, args)
    tools.execute = flaky
    provider = FakeProvider([assistant(tool("read_file", path="app.py"),
                                       tool("write_file", path="app.py", content="value = 5\n")),
                             assistant(text="done")])
    result = run(Runtime(provider, tools, memory_enabled=False).run("edit"))
    assert result["status"] == "finished" and calls == {"read": 2, "write": 1}


@pytest.mark.parametrize("seed", range(18))
def test_18_long_context_workloads(seed):
    messages = [{"role": "system", "content": "Root instructions"}, {"role": "user", "content": f"current task {seed}"}]
    for i in range(12):
        c = tool("read_file", path="app.py")
        c["id"] = "c" + str(i)
        messages += [assistant(c), {"role": "tool", "tool_call_id": c["id"], "content": json.dumps({
            "tool": "read_file", "status": "ok", "path": f"f{i%3}.py", "text": ("useful " + str(seed)) * (700+seed)})}]
    # An oversized current instruction forces the final summarization stage.
    messages[0]["content"] += " policy" * 200
    context = Context(budget=2000, tool_limit=2000)
    output = run(context.apply(messages, FakeProvider()))
    assert size(output) < size(messages)
    stages = {e["stage"] for e in context.events}
    assert stages == {"budget_truncation", "stale_snip", "microcompact", "auto_compact"}
    ids = {c["id"] for m in output for c in m.get("tool_calls", [])}
    assert all(m["tool_call_id"] in ids for m in output if m["role"] == "tool")
    assert any(m["role"] == "user" and m["content"] == f"current task {seed}" for m in output)


@pytest.mark.parametrize("i", range(20))
def test_20_stale_edit_ablation_cases(tmp_path, i):
    original = tmp_path / "app.py"; original.write_text(f"value = {i}\n", encoding="utf-8")
    async def exercise():
        guarded = Tools(tmp_path, Policy("auto"), Memory(tmp_path / ".miniclaude"))
        await guarded.execute("read_file", {"path": "app.py"})
        original.write_text(f"value = {i+100}\n", encoding="utf-8")
        assert (await guarded.execute("write_file", {"path": "app.py", "content": "value = 0"}))["status"] == "error"
        unguarded = Tools(tmp_path, Policy("auto"), guarded.memory, read_before_edit=False)
        assert (await unguarded.execute("write_file", {"path": "app.py", "content": "value = 0"}))["status"] == "ok"
    run(exercise())
