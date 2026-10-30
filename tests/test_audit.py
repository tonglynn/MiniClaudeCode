import asyncio
import json
from pathlib import Path

import pytest

from audit.__main__ import ROOT, aggregate, evaluate, independent_verify, load_contracts
from helpers import FakeProvider, assistant


def test_contracts_and_independent_verifier_ignores_faked_tests(tmp_path):
    contracts = load_contracts(ROOT / "benchmarks/tasks.json")
    assert len(contracts) == 26
    workspace = tmp_path / "workspace"; workspace.mkdir()
    c = contracts[0]
    (workspace / "app.py").write_text("def clamp(x, low, high): return 0", encoding="utf-8")
    (workspace / "test_app.py").write_text("def test_fake(): assert True", encoding="utf-8")
    verifier = tmp_path / "verifier.json"; verifier.write_text(json.dumps(c["verifier"]), encoding="utf-8")
    assert independent_verify(workspace, verifier)[0] is False
    (workspace / "app.py").write_text(c["reference"], encoding="utf-8")
    assert independent_verify(workspace, verifier)[0] is True


def test_evaluator_rejects_unverified_self_report(tmp_path):
    contracts = load_contracts(ROOT / "benchmarks/tasks.json")
    def fake(**kwargs):
        return FakeProvider([assistant(text="Everything is fixed, all tests passed")])
    result = asyncio.run(evaluate(contracts[0], "default", tmp_path, provider_factory=fake))
    assert not result["passed"] and result["failure_class"] == "verification"


def test_aggregation_actual_usage_and_ablations():
    base = {"variant": "default", "passed": True, "tool_calls": 2, "blocked_calls": 0,
            "compression_char_rate": .2, "seconds": 2, "failure_class": None,
            "usage": [{"prompt_tokens": 10, "completion_tokens": 2}]}
    variant = {**base, "variant": "no_memory", "passed": False, "failure_class": "verification",
               "seconds": 3, "usage": [{"input_tokens": 20, "output_tokens": 3}]}
    result = aggregate([base,variant])
    assert result["default"]["reported_input_tokens"] == 10
    assert result["no_memory"]["reported_input_tokens"] == 20
    assert result["no_memory"]["difference_from_default"]["pass_rate"] == -1
