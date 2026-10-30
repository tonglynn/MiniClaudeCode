import asyncio
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .permissions import Denied


def definition(name, description, properties, required, effect):
    return {"schema": {"type": "function", "function": {
        "name": name, "description": description, "parameters": {
            "type": "object", "properties": properties, "required": required,
            "additionalProperties": False}}}, "effect": effect}


S = {"type": "string"}
I = {"type": "integer"}
REGISTRY = {
    x["schema"]["function"]["name"]: x for x in [
        definition("list_files", "List project files, optionally matching a glob", {"pattern": S}, [], "read"),
        definition("read_file", "Read UTF-8 text; use line ranges for large files",
                   {"path": S, "start": I, "end": I}, ["path"], "read"),
        definition("write_file", "Create or overwrite text. Existing file must be read at current version",
                   {"path": S, "content": S}, ["path", "content"], "write"),
        definition("edit_file", "Replace one exact occurrence in a previously read file",
                   {"path": S, "old": S, "new": S}, ["path", "old", "new"], "write"),
        definition("search_text", "Search project text by literal substring or regular expression",
                   {"query": S, "pattern": S, "regex": {"type": "boolean"}}, ["query"], "read"),
        definition("run_command", "Run approved argv without a shell. Allowed: git status/diff/log; Python -m pytest/unittest",
                   {"argv": {"type": "array", "items": S}}, ["argv"], "exec"),
        definition("run_tests", "Execute project tests; runner is pytest or unittest",
                   {"runner": {"type": "string", "enum": ["pytest", "unittest"]}}, [], "exec"),
        definition("remember", "Save project knowledge across sessions", {"key": S, "value": S}, ["key", "value"], "write"),
        definition("recall", "Semantic side-query retrieval with freshness metadata", {"query": S}, ["query"], "read"),
        definition("update_plan", "Track explicit task steps and completion state",
                   {"steps": {"type": "array", "items": S}}, ["steps"], "internal"),
        definition("discover_tools", "Find and activate deferred capabilities by name or description", {"query": S}, ["query"], "internal"),
        definition("git_status", "Read git porcelain status without modifying repository", {}, [], "read"),
        definition("ask_user", "Ask the human a necessary clarification", {"question": S}, ["question"], "internal"),
    ]}
INITIAL = {"list_files", "read_file", "write_file", "run_tests", "discover_tools"}
PROTECTED = {".miniclaude", ".git", ".env", ".provider_private.json", ".deepseek_private.json", ".ssh", ".aws",
             ".miniclaude_permissions.json"}


def child_env():
    # This removes configured credentials from the test process environment;
    # it is not an operating-system sandbox or a defense against arbitrary code.
    return {k: v for k, v in os.environ.items()
            if not any(part in k.upper() for part in ("API_KEY", "AUTH_TOKEN", "ACCESS_TOKEN", "SECRET"))}


class Tools:
    def __init__(self, root, policy, memory, provider=None, eager=False, read_before_edit=True, allowed=None, ask=None,
                 editable_paths=None):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("Workspace does not exist")
        self.policy, self.memory, self.provider, self.ask = policy, memory, provider, ask
        self.allowed = set(allowed) if allowed is not None else set(REGISTRY)
        self.active = self.allowed.copy() if eager else INITIAL & self.allowed
        self.read_before_edit = read_before_edit
        self.editable_paths = editable_paths
        self.versions, self.events, self.plan = {}, [], []
        self.lock = threading.RLock()

    def schemas(self):
        return [REGISTRY[n]["schema"] for n in sorted(self.active)]

    def path(self, value):
        p = (self.root / value).resolve()
        if not p.is_relative_to(self.root):
            raise Denied("path_outside_workspace")
        rel = p.relative_to(self.root)
        if any(part.casefold() in {x.casefold() for x in PROTECTED} for part in rel.parts):
            raise Denied("protected_path")
        if p.name.casefold().startswith(".env."):
            raise Denied("protected_path")
        return p

    def files(self, pattern="*"):
        # No symlink traversal; capped inventory and no secret/state files.
        found = []
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(n for n in dirs if n not in PROTECTED and n not in ("__pycache__", ".venv", ".pytest_cache")
                             and not (Path(directory) / n).is_symlink())
            for name in sorted(names):
                p = Path(directory) / name
                if p.is_symlink():
                    continue
                try:
                    self.path(str(p.relative_to(self.root)))
                except Denied:
                    continue
                relative = p.relative_to(self.root).as_posix()
                if fnmatch.fnmatchcase(relative, pattern):
                    found.append(relative)
                    if len(found) >= 1000:
                        return found
        return found

    def validate(self, name, args):
        if name not in REGISTRY or name not in self.allowed:
            raise Denied("tool_not_allowed")
        if name not in self.active:
            raise Denied("tool_deferred: call discover_tools first")
        p = REGISTRY[name]["schema"]["function"]["parameters"]
        if not isinstance(args, dict) or set(args) - set(p["properties"]) or not set(p["required"]).issubset(args):
            raise ValueError("Invalid/missing tool arguments")
        types = {"string": str, "integer": int, "boolean": bool, "array": list}
        for key, value in args.items():
            prop = p["properties"][key]
            if type(value) is not types[prop["type"]]:
                raise ValueError("Wrong parameter type: " + key)
            if "enum" in prop and value not in prop["enum"]:
                raise ValueError("Invalid enum: " + key)
            if isinstance(value, list) and (len(value) > 100 or any(not isinstance(x, str) for x in value)):
                raise ValueError("Expected a short string array")

    async def execute(self, name, args):
        started = time.monotonic()
        try:
            self.validate(name, args)
            await self.policy.check(name, args, REGISTRY[name]["effect"])
            if name == "recall":
                result = await self.memory.recall(args["query"], self.provider)
            elif name == "ask_user":
                if not self.ask:
                    raise Denied("human_input_unavailable")
                result = await self.ask(args["question"])
            elif name == "discover_tools":
                query = args["query"].casefold()
                matches = [n for n in sorted(self.allowed) if query in n.casefold()
                           or query in REGISTRY[n]["schema"]["function"]["description"].casefold()]
                if not matches:
                    result = {"available_names": sorted(self.allowed), "activated": []}
                else:
                    self.active.update(matches)
                    result = {"activated": matches, "schemas": [REGISTRY[n]["schema"] for n in matches]}
            else:
                result = await asyncio.to_thread(self._execute, name, args)
            event = {"tool": name, "status": "ok", "result": result}
        except (Denied, OSError, ValueError, SyntaxError, UnicodeError, subprocess.SubprocessError) as exc:
            event = {"tool": name, "status": "blocked" if isinstance(exc, Denied) else "error", "error": str(exc)}
        event["seconds"] = round(time.monotonic() - started, 5)
        if isinstance(args, dict) and "path" in args:
            event["path"] = args["path"]
        self.events.append(event)
        return event

    def _write(self, path, text):
        relative = path.relative_to(self.root).as_posix()
        if self.editable_paths is not None and not any(fnmatch.fnmatchcase(relative, p) for p in self.editable_paths):
            raise Denied("task_contract_file_write_denied")
        if len(text.encode()) > 500000:
            raise ValueError("Write exceeds 500 KB")
        with self.lock:
            if self.read_before_edit and path.exists():
                if path not in self.versions or hashlib.sha256(path.read_bytes()).hexdigest() != self.versions[path]:
                    raise ValueError("read_before_edit: read current complete file version first")
            if path.suffix == ".py":
                compile(text, str(path), "exec")  # validate syntax before modifying original
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            self.versions.pop(path, None)
        return {"written": path.relative_to(self.root).as_posix(), "bytes": len(text.encode())}

    def _run(self, argv):
        if not argv:
            raise ValueError("Empty argv")
        executable = Path(argv[0]).name.casefold()
        git = executable in ("git", "git.exe") and len(argv) >= 2 and argv[1] in ("status", "diff", "log")
        python = executable in ("python", "python.exe", "python3", Path(sys.executable).name.casefold())
        tests = python and len(argv) >= 3 and argv[1] == "-m" and argv[2] in ("pytest", "unittest")
        if not (git or tests):
            raise Denied("command_not_in_allowlist")
        if git and any(x.startswith(("--output", "--ext-diff", "--textconv")) for x in argv):
            raise Denied("unsafe_git_option")
        if git:
            trusted_git = shutil.which("git")
            if not trusted_git:
                raise ValueError("Git executable not available")
            argv = [trusted_git, *argv[1:]]
        if tests:
            argv = [sys.executable, *argv[1:]]
        proc = subprocess.run(argv, cwd=self.root, shell=False, env=child_env(), capture_output=True,
                              encoding="utf-8", errors="replace", timeout=30)
        return {"exit_code": proc.returncode, "output": (proc.stdout + proc.stderr)[-24000:]}

    def _execute(self, name, args):
        if name == "list_files":
            return self.files(args.get("pattern", "*"))
        if name == "read_file":
            p = self.path(args["path"])
            with self.lock:
                data = p.read_bytes()
                if len(data) > 1000000:
                    raise ValueError("File exceeds 1 MB")
                self.versions[p] = hashlib.sha256(data).hexdigest()
            lines = data.decode("utf-8").splitlines(keepends=True)
            start, end = args.get("start", 1), args.get("end", len(lines))
            if start < 1 or end < start:
                raise ValueError("Invalid 1-based line range")
            return {"text": "".join(lines[start-1:end]), "lines": len(lines), "start": start, "end": end}
        if name == "write_file":
            return self._write(self.path(args["path"]), args["content"])
        if name == "edit_file":
            p = self.path(args["path"])
            with self.lock:
                text = p.read_text(encoding="utf-8")
                if not args["old"] or text.count(args["old"]) != 1:
                    raise ValueError("old text must match exactly once")
                return self._write(p, text.replace(args["old"], args["new"], 1))
        if name == "search_text":
            hits = []
            pattern = re.compile(args["query"]) if args.get("regex") else None
            for relative in self.files(args.get("pattern", "*")):
                file = self.path(relative)
                if file.stat().st_size > 500000:
                    continue
                try:
                    lines = file.read_text(encoding="utf-8").splitlines()
                except UnicodeError:
                    continue
                for i, line in enumerate(lines, 1):
                    if (pattern.search(line) if pattern else args["query"] in line):
                        hits.append({"path": relative, "line": i, "text": line[:1000]})
                        if len(hits) >= 100:
                            return hits
            return hits
        if name == "run_tests":
            runner = args.get("runner", "pytest")
            return self._run([sys.executable, "-m", runner, *(["-q"] if runner == "pytest" else ["discover", "-s", "."])])
        if name == "run_command":
            return self._run(args["argv"])
        if name == "git_status":
            return self._run(["git", "status", "--porcelain"])
        if name == "remember":
            self.memory.put(args["key"], args["value"])
            return {"saved": args["key"]}
        if name == "update_plan":
            self.plan = args["steps"]
            return {"steps": self.plan}
        raise ValueError("Unknown implementation")
