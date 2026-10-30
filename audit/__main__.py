import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from time import time

from rich.console import Console

from miniclaudecode.config import ROOT, provider_config, scrub
from miniclaudecode.context import Context
from miniclaudecode.memory import Memory
from miniclaudecode.permissions import Policy
from miniclaudecode.provider import Provider
from miniclaudecode.runtime import Runtime
from miniclaudecode.tools import REGISTRY, Tools, child_env

console = Console(highlight=False)
VARIANTS = ("default", "eager_tools", "no_compression", "no_memory", "no_read_before_edit")


def load_contracts(suite):
    suite = Path(suite).resolve()
    contracts = json.loads(suite.read_text(encoding="utf-8"))
    ids = set()
    for c in contracts:
        required = {"id", "fixture", "prompt", "allowed_tools", "verifier", "max_steps", "timeout", "reference"}
        if not required.issubset(c) or c["id"] in ids or not c["id"].replace("_", "").isalnum():
            raise ValueError("Invalid/duplicate task contract")
        ids.add(c["id"])
        fixture = (suite.parent / c["fixture"]).resolve()
        if not fixture.is_relative_to(suite.parent) or not fixture.is_dir():
            raise ValueError("Fixture must be inside suite directory")
        if any(x.is_symlink() for x in fixture.rglob("*")):
            raise ValueError("Fixture symlinks are not supported")
        if not set(c["allowed_tools"]).issubset(REGISTRY):
            raise ValueError("Unknown contract tool")
        if c["max_steps"] < 1 or c["timeout"] <= 0:
            raise ValueError("Invalid execution limits")
        if not isinstance(c["verifier"].get("cases"), list) or not c["verifier"]["cases"]:
            raise ValueError("Verifier cases required")
        c["fixture_path"] = fixture
    return contracts


def fixture_hash(folder):
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(folder).as_posix().encode()); h.update(p.read_bytes())
    return h.hexdigest()


def independent_verify(workspace, snapshot, timeout=15):
    # Contract lives outside the editable workspace, and tests are not taken from agent output.
    verifier = Path(__file__).with_name("verifier.py").resolve()
    p = subprocess.run([sys.executable, "-I", str(verifier), str(workspace), str(snapshot)],
                       cwd=snapshot.parent, capture_output=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env=child_env())
    return p.returncode == 0, (p.stdout + p.stderr)[-6000:]


def failure_class(result, passed):
    if passed:
        return None
    if result["status"] in ("error", "timeout"):
        return "model_or_runtime"
    events = [e for e in result["trace"] if e.get("kind") == "tool"]
    if any(e["status"] == "blocked" for e in events):
        return "policy"
    if any(e["status"] == "error" for e in events):
        return "tool_execution"
    return "verification"


async def evaluate(contract, variant, run_dir, provider_factory=Provider):
    folder = run_dir / (contract["id"] + "_" + variant)
    folder.mkdir(parents=True, exist_ok=False)
    workspace = folder / "workspace"
    shutil.copytree(contract["fixture_path"], workspace, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    snapshot = folder / "verifier.json"
    snapshot.write_text(json.dumps(contract["verifier"], ensure_ascii=False, indent=2), encoding="utf-8")
    source_hash = fixture_hash(contract["fixture_path"])
    provider = provider_factory(**provider_config())
    state = workspace / ".miniclaude"
    tools = Tools(workspace, Policy("auto"), Memory(state), provider, eager=variant == "eager_tools",
                  read_before_edit=variant != "no_read_before_edit", allowed=contract["allowed_tools"],
                  editable_paths=contract.get("editable_paths", ["app.py"]))
    runtime = Runtime(provider, tools,
                      Context(contract.get("context_chars", 48000), enabled=variant != "no_compression"),
                      max_steps=contract["max_steps"], memory_enabled=variant != "no_memory")
    try:
        result = await asyncio.wait_for(runtime.run(contract["prompt"]), contract["timeout"])
    except TimeoutError:
        result = {"status": "timeout", "answer": "task timeout", "trace": runtime.trace, "seconds": contract["timeout"]}
    try:
        verified, details = await asyncio.to_thread(independent_verify, workspace, snapshot)
    except (subprocess.SubprocessError, OSError) as exc:
        verified, details = False, type(exc).__name__
    passed = verified and result["status"] == "finished"
    changed = fixture_hash(contract["fixture_path"]) != source_hash
    if changed:
        raise RuntimeError("Original fixture unexpectedly changed")
    events = [e for e in result["trace"] if e.get("kind") == "tool"]
    compression = [e for e in result["trace"] if e.get("kind") == "compression"]
    before = sum(e["before_chars"] for e in compression)
    saved = sum(max(0, e["before_chars"] - e["after_chars"]) for e in compression)
    row = {"task": contract["id"], "variant": variant, "passed": passed, "status": result["status"],
           "failure_class": failure_class(result, passed), "verification": details,
           "fixture_sha256": source_hash, "verifier_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
           "tool_calls": len(events), "blocked_calls": sum(e["status"] == "blocked" for e in events),
           "tool_errors": sum(e["status"] == "error" for e in events),
           "compression_events": len(compression), "removed_context_chars": saved,
           "compression_char_rate": saved / before if before else 0,
           "seconds": result["seconds"], "usage": provider.usage, "trace": result["trace"]}
    (folder / "result.json").write_text(scrub(json.dumps(row, ensure_ascii=False, indent=2)), encoding="utf-8")
    return row


def aggregate(rows):
    variants = {}
    for name in dict.fromkeys(r["variant"] for r in rows):
        sample = [r for r in rows if r["variant"] == name]
        total_tools = sum(r["tool_calls"] for r in sample)
        variants[name] = {"runs": len(sample), "passed": sum(r["passed"] for r in sample),
                          "pass_rate": sum(r["passed"] for r in sample) / len(sample),
                          "tool_calls": total_tools,
                          "safety_block_rate": sum(r["blocked_calls"] for r in sample) / total_tools if total_tools else 0,
                          "mean_compression_char_rate": sum(r["compression_char_rate"] for r in sample) / len(sample),
                          "mean_seconds": sum(r["seconds"] for r in sample) / len(sample),
                          "failure_counts": {k: sum(r["failure_class"] == k for r in sample) for k in
                                             ("model_or_runtime", "policy", "tool_execution", "verification")}}
        usage = [u for r in sample for u in r["usage"]]
        variants[name]["reported_input_tokens"] = sum(u.get("prompt_tokens", u.get("input_tokens", 0)) for u in usage)
        variants[name]["reported_output_tokens"] = sum(u.get("completion_tokens", u.get("output_tokens", 0)) for u in usage)
    if "default" in variants:
        baseline = variants["default"]
        for name, metrics in variants.items():
            if name != "default":
                metrics["difference_from_default"] = {
                    "pass_rate": metrics["pass_rate"] - baseline["pass_rate"],
                    "mean_seconds": metrics["mean_seconds"] - baseline["mean_seconds"]}
    return variants


def offline_check(contracts, destination):
    # This validates the suite and trusted verifier, not an Agent or model.
    results = []
    for c in contracts:
        folder = destination / c["id"]
        folder.mkdir()
        workspace = folder / "workspace"
        shutil.copytree(c["fixture_path"], workspace)
        snapshot = folder / "verifier.json"
        snapshot.write_text(json.dumps(c["verifier"]), encoding="utf-8")
        broken, _ = independent_verify(workspace, snapshot)
        (workspace / "app.py").write_text(c["reference"], encoding="utf-8")
        for cache in workspace.glob("__pycache__/*"):
            cache.unlink()
        reference, detail = independent_verify(workspace, snapshot)
        results.append({"task": c["id"], "rejects_broken": not broken, "accepts_reference": reference,
                        "detail": detail})
    payload = {"mode": "offline_suite_validation_NOT_agent_benchmark", "results": results}
    (destination / "offline_check.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return all(r["rejects_broken"] and r["accepts_reference"] for r in results)


async def main_async(args):
    contracts = load_contracts(args.suite)
    if args.task:
        contracts = [c for c in contracts if c["id"] == args.task]
        if not contracts:
            raise ValueError("No matching task")
    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="audit_", dir=runs))
    if args.offline_check:
        ok = await asyncio.to_thread(offline_check, contracts, run)
        console.print(f"Offline contract/verifier validation: {'PASS' if ok else 'FAIL'}; {len(contracts)} tasks")
        console.print(str(run / "offline_check.json"), markup=False)
        return 0 if ok else 1
    variants = args.variants.split(",")
    if any(v not in VARIANTS for v in variants) or len(set(variants)) != len(variants):
        raise ValueError("Unknown/duplicate ablation variant")
    console.print(f"REAL API evaluation: {len(contracts)} tasks x {len(variants)} variants x {args.repeat} repeats. API charges apply.")
    rows = []
    for repeat in range(args.repeat):
        group = run / f"repeat_{repeat+1}"
        group.mkdir()
        for variant in variants:
            for c in contracts:
                console.print(f"Running {c['id']} / {variant} / repeat {repeat+1} ...", markup=False)
                row = await evaluate(c, variant, group)
                row["repeat"] = repeat + 1
                rows.append(row)
                console.print("PASS" if row["passed"] else f"FAIL ({row['failure_class']})")
                metadata = {"model": provider_config()["model"], "protocol": provider_config()["protocol"],
                            "created_unix": time(), "variants": aggregate(rows), "results": rows}
                (run / "report.json").write_text(scrub(json.dumps(metadata, ensure_ascii=False, indent=2)), encoding="utf-8")
    console.print_json(json.dumps(aggregate(rows)))
    console.print("Report: " + str(run / "report.json"), markup=False)
    return 0 if all(r["passed"] for r in rows) else 1


def main():
    p = argparse.ArgumentParser(description="Audit real coding-agent evaluation and ablation CLI")
    p.add_argument("--suite", default=str(ROOT / "benchmarks" / "tasks.json"))
    p.add_argument("--task")
    p.add_argument("--variants", default="default")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--offline-check", action="store_true")
    args = p.parse_args()
    if args.repeat < 1:
        p.error("repeat must be positive")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        console.print(str(exc), style="red", markup=False)
        raise SystemExit(1)
