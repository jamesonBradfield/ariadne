#!/usr/bin/env python3
"""Anchor-case auto-fix loop: bench -> optimize -> bench, bounded retries.

run_llm_benchmarks.py exits 0 only when all 3 anchor cases pass, so its exit
code is the verdict. On failure we invoke optimize_maps_prompts.py (textgrad
self-optimization through the local lane when no OpenRouter key is set) which
rewrites the failing state's system_prompt in ariadne_config.json, then re-run.

Writes anchor_benchmark_results.json next to benchmark_results.json so the
systems-monitor svc check can report regressions without re-running the LLM.
"""
import json
import re
import subprocess
import sys
import time

ARTIFACT = "anchor_benchmark_results.json"
MAX_ATTEMPTS = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def run_bench():
    r = subprocess.run(["python3", "scripts/run_llm_benchmarks.py"],
                      capture_output=True, text=True)
    results = []
    for line in r.stdout.splitlines():
        m = re.match(r"^\[(PASS|FAIL)\] (\S+) \((\S+)\): (.*)", line)
        if m:
            ok, cid, state, rest = m.groups()
            results.append({"id": cid, "state": state, "passed": ok == "PASS",
                            "note": rest[:200]})
        m2 = re.match(r"^\[ERROR\] (\S+): (.*)", line)
        if m2:
            results.append({"id": m2.group(1), "state": "?", "passed": False,
                            "note": m2.group(2)[:200]})
    return r.returncode, results


def write_artifact(attempt, code, results):
    payload = {
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "attempt": attempt,
        "all_passed": code == 0,
        "passed": sum(1 for x in results if x["passed"]),
        "total": len(results),
        "results": results,
    }
    with open(ARTIFACT, "w") as f:
        json.dump(payload, f, indent=1)
    print(f"[attempt {attempt}] verdict={'PASS' if code == 0 else 'FAIL'} -> {ARTIFACT}")


def run_optimize():
    # uv run resolves .venv (textgrad/litellm) — same repo uv env as pytest.
    r = subprocess.run(["uv", "run", "python", "scripts/optimize_maps_prompts.py"],
                      capture_output=True, text=True)
    print(f"[optimize] exit={r.returncode}")


def main():
    for attempt in range(1, MAX_ATTEMPTS + 1):
        code, results = run_bench()
        write_artifact(attempt, code, results)
        if code == 0:
            return 0
        if attempt == MAX_ATTEMPTS:
            return 1
        run_optimize()
    return 1


if __name__ == "__main__":
    sys.exit(main())
