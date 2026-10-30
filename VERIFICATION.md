# Release verification

Checks performed on 2026-10-30 for this public reconstruction. These results describe this implementation, not the unavailable historical CV experiments.

## Automated checks

- Clean Windows virtual environment; editable installation through `pip install -e .` succeeded.
- `python -m pytest -q`: **122 passed**.
- `miniclaudecode --help`: installed CLI entry point works.
- `miniclaude-audit --offline-check`: **26/26 contract/verifier checks passed**.
- A distribution wheel built successfully and includes all 26 benchmark fixtures.
- GitHub Actions is enabled in `.github/workflows/ci.yml` for Windows/Ubuntu and Python 3.12/3.13. It runs the unit suite, CLI smoke check, and offline contract validation. See the [CI runs](https://github.com/tonglynn/MiniClaudeCode/actions/workflows/ci.yml) for remote results.

Tests exercise protocol conversion and streaming parsers, retry behavior, deferred activation, schema validation, concurrent reads and fallback, context stages, persistent memory, session recovery, hierarchical instructions, permission modes, dangerous-command checks, stale-edit protection, independent verification, and metric aggregation. They include 18 context scenarios, 40 risky-command cases, and 20 stale-edit comparison scenarios using controlled providers.

Offline contract validation confirms that broken implementations fail and reference implementations pass. It does not run an agent or measure model completion rate. Machine-readable results: [offline-contracts.json](evidence/offline-contracts.json).

## Live model smoke test

A fresh single-task run used the OpenAI-compatible protocol and `deepseek-flash` on `t01_clamp`:

- Agent repaired the fixture and passed the separate verifier.
- Six tool calls; 6.578 seconds measured by the evaluator.
- Provider-reported usage: 5,797 input tokens and 509 output tokens.

These observations are one run, not average performance or a general success rate. The credentials and private execution traces are excluded from the repository. Sanitized metrics: [live-smoke.json](evidence/live-smoke.json).

## Limits

The full 26-task live benchmark, repeated strategy ablations, and original CV performance claims were not reproduced. Native Anthropic streaming is covered by controlled protocol tests; this release's live smoke run used the OpenAI-compatible path only.

Context size is measured in characters; memory candidate retrieval is lexical/recent-note retrieval followed by LLM ranking. Permissions and subprocess verification are application controls, not isolation from malicious project code. Use an external OS or container boundary for untrusted repositories.
