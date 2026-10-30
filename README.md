# MiniClaudeCode

[![Tests](https://img.shields.io/badge/local_tests-122_passed-brightgreen)](VERIFICATION.md)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A local coding-agent CLI for exploring repositories, planning changes, editing files, running tests, and resuming work across sessions. Built with Python, AsyncIO, Rich, SQLite, and native OpenAI-compatible / Anthropic-compatible HTTP APIs.

The focus is the **harness around the model**: when tools become available, how context stays useful, which operations require approval, and how an independent evaluator checks the result.

[中文说明](docs/README.zh-CN.md) · [Design](docs/design.md) · [Verification](VERIFICATION.md)

## Capabilities

- **Agent loop:** streaming text and tool calls, exponential backoff with jitter, and no request replay after visible output or tool dispatch.
- **13 tools with deferred activation:** five schemas initially; the model discovers additional capabilities when needed. Read-only calls can run concurrently. Anthropic tool blocks can dispatch reads before the entire response finishes; writes wait for the complete response.
- **Four-stage context compression:** oversized-output truncation → stale-read removal → microcompaction → model-generated working summary. System instructions, the current task, and tool-call/result pairing are preserved.
- **Persistent memory:** SQLite notes, side-query expansion, model-assisted semantic ranking, asynchronous prefetch, and age reminders. A labeled lexical fallback works when semantic ranking fails.
- **Permission controls:** five modes, declarative allow/deny rules, 16 dangerous-command patterns, exact-argument approval whitelists, workspace boundaries, and protected state/configuration paths.
- **Validated edits:** read-before-edit, file-digest checks against stale writes, exact-match replacement, and Python syntax validation before writing.
- **Resumable sessions:** atomic JSON saves, slash commands, hierarchical `CLAUDE.md`, recursive `@include`, and `.agent/rules/*.md` loading.
- **Audit evaluator:** copied task fixtures, independent verification, execution traces, failure classification, metrics, and strategy ablations.

## Quick start

Requires Python 3.12+ and Git. Model calls require your own API key; tests and offline contract checks do not.

```bash
git clone https://github.com/tonglynn/MiniClaudeCode.git
cd MiniClaudeCode
python -m venv .venv
```

Activate the environment on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on Linux/macOS:

```bash
source .venv/bin/activate
```

Install from the checkout:

```bash
python -m pip install -e .
```

Configure an OpenAI-compatible endpoint in PowerShell:

```powershell
$env:LLM_PROTOCOL = 'openai'
$env:LLM_BASE_URL = 'https://api.deepseek.com'
$env:LLM_MODEL = '<your-provider-model-id>'
$env:LLM_API_KEY = '<your-api-key>'
miniclaudecode --workspace 'C:\path\to\your\repo'
```

On Linux/macOS, use `export LLM_PROTOCOL=openai` and the corresponding `export NAME=value` assignments. `LLM_BASE_URL` is the API prefix, without `/chat/completions` or `/messages`.

For Anthropic-compatible endpoints set `LLM_PROTOCOL=anthropic`, the provider's API prefix (for example `https://api.anthropic.com/v1`), and a model ID available to your account.

Alternatively, copy `.provider.example.json` to `.provider_private.json` in the checkout and fill it locally. Environment variables override that file. The private file is ignored by Git. No key is bundled, and `.env` files are not automatically loaded.

Run a task with approval prompts:

```bash
miniclaudecode --workspace /path/to/repo --task "Find the failing test, fix its cause, and rerun the tests."
```

`ask` is the default mode. For a disposable, trusted checkout, `--mode auto` allows the supported edits and commands after built-in policy checks. Commands are limited to Git status/diff/log and Python pytest/unittest runners; this is deliberately a constrained coding workflow.

## Interactive use

`/help`, `/new`, `/sessions`, `/resume ID`, `/save`, `/mode MODE`, `/memory QUERY`, `/plan`, `/tools`, `/exit`.

Session and memory files live in `<workspace>/.miniclaude/`. Resume with `--resume ID`; approvals are evaluated using the current policy.

Permission modes:

- `read_only`: inspect files and recall knowledge; reject writes and process execution.
- `plan`: inspect and plan; reject writes and process execution.
- `ask`: ask before writes and execution unless a declarative allow rule applies.
- `auto_edit`: allow file writes; ask before process execution.
- `auto`: allow supported operations after deny rules and built-in checks.

Copy `.miniclaude_permissions.example.json` into your workspace as `.miniclaude_permissions.json` to customize rules. Explicit denials take priority; “always” approvals match the exact tool name and arguments for the current session.

Available tools: `list_files`, `read_file`, `write_file`, `edit_file`, `search_text`, `run_command`, `run_tests`, `remember`, `recall`, `update_plan`, `discover_tools`, `git_status`, `ask_user`.

## Verify locally

```bash
python -m pytest -q
miniclaude-audit --offline-check
```

A ready-to-use [GitHub Actions template](docs/ci.yml) covers Windows/Ubuntu and Python 3.12/3.13. To enable CI, place it at `.github/workflows/ci.yml` using credentials with workflow-write permission. Automated GitHub runs are not enabled in this release.

The offline check verifies that each of the **26 reconstructed contracts** rejects its broken fixture and accepts its reference implementation. It makes no model calls and **is not an agent completion benchmark**. The fixtures intentionally contain bugs, so run the project tests in `tests/` rather than treating fixture tests as project regressions.

Run one real model evaluation after configuring your provider:

```bash
miniclaude-audit --task t01_clamp
```

Run strategy comparisons:

```bash
miniclaude-audit --variants default,eager_tools,no_compression,no_memory,no_read_before_edit --repeat 3
```

The latter runs 390 task attempts and incurs API charges. Results go into `runs/audit_*/`, including traces, verifier results, timing, reported token usage, and aggregate metrics. The evaluator classifies failures as `model_or_runtime`, `policy`, `tool_execution`, or `verification`.

## Project layout

```text
miniclaudecode/
  provider.py       Native protocol adapters, SSE parsing, retries
  runtime.py        Agent loop, concurrent reads, memory prefetch
  tools.py          Tool schemas, discovery, execution, edit checks
  context.py        Four-stage history compression
  memory.py         SQLite notes and semantic side queries
  permissions.py   Modes, allow/deny rules, dangerous patterns
  prompts.py        Hierarchical project instructions
  sessions.py      Session persistence and recovery
audit/             Evaluation runner and independent verifier
benchmarks/        Reconstructed contracts and intentionally broken fixtures
tests/             Runtime, protocol, policy, and evaluator tests
```

## Evidence and limitations

This public implementation reconstructs the capabilities described in my CV. Original source code, historical benchmark inputs, and experiment logs are unavailable. Consequently, the CV's historical improvement percentages and token savings are **not claimed as reproduced results** here. See [VERIFICATION.md](VERIFICATION.md) for checks actually performed on this release.

Context budgets use characters, not exact tokenizer counts. Memory uses LLM ranking over lexical/recent candidates rather than an embedding database. Compression and memory side queries can incur additional API calls. Model-generated summaries and recalled notes remain fallible.

Application permission checks are **not an OS sandbox**. Running tests executes repository code; use disposable isolated environments for untrusted projects. The independent verifier checks separate assertions in a subprocess, but does not provide adversarial code isolation. Avoid passing credentials or personal data to untrusted repositories or model providers.

MIT licensed. This is an independent project, with no affiliation to Anthropic or OpenAI.
