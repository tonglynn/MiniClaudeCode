import argparse
import asyncio
import json
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from .config import provider_config
from .context import Context
from .memory import Memory
from .permissions import MODES, Policy
from .provider import Provider
from .runtime import Runtime
from .tools import Tools, INITIAL

console = Console(highlight=False)


async def confirm(name, args):
    console.print(f"Permission request: {name}", style="yellow")
    console.print(json.dumps(args, ensure_ascii=False)[:3000], markup=False)
    return await asyncio.to_thread(Prompt.ask, "Allow?", choices=["yes", "no", "always"], default="no")


async def ask(question):
    return await asyncio.to_thread(Prompt.ask, question)


def emit(kind, value):
    if kind == "text":
        console.print(value, end="", markup=False)
    else:
        status = value["status"]
        console.print(f"\n[{value['tool']}] {status}", style="green" if status == "ok" else "yellow", markup=False)
        if status != "ok":
            console.print(value.get("error", ""), markup=False)
        elif value["tool"] in ("run_tests", "run_command"):
            console.print(json.dumps(value["result"], ensure_ascii=False), markup=False)


async def run_cli(args):
    root = Path(args.workspace).resolve()
    state = root / ".miniclaude"
    config = provider_config()
    if args.protocol:
        config["protocol"] = args.protocol
        if args.protocol == "anthropic" and config["base_url"] == "https://api.deepseek.com":
            config["base_url"] += "/anthropic"
    provider = Provider(**config)
    rules_file = root / ".miniclaude_permissions.json"
    rules = json.loads(rules_file.read_text(encoding="utf-8")) if rules_file.exists() else None
    tools = Tools(root, Policy(args.mode, rules, confirm), Memory(state), provider,
                  eager=args.eager_tools, read_before_edit=not args.no_read_before_edit, ask=ask)
    runtime = Runtime(provider, tools, Context(args.context_chars, enabled=not args.no_compression),
                      max_steps=args.max_steps, memory_enabled=not args.no_memory, emit=emit)
    if args.resume:
        runtime.restore(args.resume)
    console.print(f"MiniClaudeCode | {config['protocol']} | {config['model']} | {args.mode}", style="bold")
    console.print(f"Workspace: {root}\nSession: {runtime.sessions.id}", markup=False)
    async def execute(task):
        result = await runtime.run(task)
        console.print(f"\nStatus: {result['status']} | {result['seconds']}s | session {result['session']}")
        if result["status"] != "finished":
            console.print(result["answer"], style="red", markup=False)
        return result
    if args.task:
        result = await execute(args.task)
        return 0 if result["status"] == "finished" else 1
    console.print("/help /new /sessions /resume ID /save /mode MODE /memory QUERY /plan /tools /exit")
    while True:
        try:
            text = await asyncio.to_thread(Prompt.ask, "You")
        except (EOFError, KeyboardInterrupt):
            runtime.save()
            return 0
        if not text.strip():
            continue
        command, _, arg = text.partition(" ")
        if command == "/exit":
            runtime.save(); return 0
        if command == "/help":
            console.print("/new: new session; /sessions: list; /resume ID; /save; /mode " + "|".join(MODES)
                          + "; /memory QUERY; /plan; /tools; /exit")
        elif command == "/new":
            runtime.save()
            tools.events.clear(); tools.versions.clear(); tools.policy.whitelist.clear(); tools.plan = []
            tools.active = tools.allowed.copy() if args.eager_tools else INITIAL & tools.allowed
            runtime = Runtime(provider, tools, Context(args.context_chars, enabled=not args.no_compression),
                              args.max_steps, not args.no_memory, emit)
            console.print("New session: " + runtime.sessions.id)
        elif command == "/sessions":
            console.print(runtime.sessions.list())
        elif command == "/resume":
            try:
                runtime.restore(arg)
                console.print("Restored " + arg)
            except (OSError, ValueError, KeyError) as exc:
                console.print(str(exc), style="red", markup=False)
        elif command == "/save":
            runtime.save(); console.print("Saved " + runtime.sessions.id)
        elif command == "/mode":
            if arg not in MODES:
                console.print("Valid modes: " + ", ".join(MODES))
            else:
                tools.policy.mode = arg; console.print("Mode: " + arg)
        elif command == "/memory":
            console.print(await tools.memory.recall(arg, provider))
        elif command == "/plan":
            console.print(tools.plan)
        elif command == "/tools":
            console.print("Active tools: " + ", ".join(sorted(tools.active)))
        elif text.startswith("/"):
            console.print("Unknown slash command; use /help")
        else:
            await execute(text)


def main():
    p = argparse.ArgumentParser(description="MiniClaudeCode: real API agent, 13 tools, persistent sessions")
    p.add_argument("--workspace", required=True)
    p.add_argument("--task")
    p.add_argument("--mode", choices=MODES, default="ask")
    p.add_argument("--protocol", choices=["openai", "anthropic"])
    p.add_argument("--resume")
    p.add_argument("--max-steps", type=int, default=40)
    p.add_argument("--context-chars", type=int, default=48000)
    p.add_argument("--eager-tools", action="store_true")
    p.add_argument("--no-compression", action="store_true")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--no-read-before-edit", action="store_true", help="controlled ablation only")
    args = p.parse_args()
    if args.max_steps < 1 or args.context_chars < 1000:
        p.error("max-steps >=1 and context-chars >=1000 required")
    return asyncio.run(run_cli(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        console.print(str(exc), style="red", markup=False)
        raise SystemExit(1)
