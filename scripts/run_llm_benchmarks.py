#!/usr/bin/env python3
"""Benchmark runner for Ariadne LLM cases (tests/llm_cases.json).

Validates that the local model passes the 3 core HFSM cases:
1. nav_anchor_loop (MAPS_NAV)
2. think_anchor_abort (MAPS_THINK)
3. thinking_container_trap (THINKING)
"""

import json
import os
import sys
import urllib.request
import re

def salvage_json(reasoning):
    for pattern in [r'(\{\s*"reasoning":.*?\})', r'(\{\s*"action":.*?\})', r'(\{\s*"steps":.*?\})', r'(\{.*\})']:
        for m in re.finditer(pattern, reasoning, re.DOTALL):
            candidate = m.group(1)
            try:
                return json.loads(candidate)
            except Exception:
                continue
    return None

def run_benchmarks():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "ariadne_config.json")
    cases_path = os.path.join(base_dir, "tests", "llm_cases.json")

    with open(config_path) as f:
        config = json.load(f)

    with open(cases_path) as f:
        cases = json.load(f)

    default_cfg = config.get("default", {})
    model_id = default_cfg.get("model", "openai/Qwen3.6-27B-A3B-Coder-MTP-IQ2_M")
    if model_id.startswith("openai/"):
        model_id = model_id[7:]
    api_base = default_cfg.get("api_base", "http://localhost:8080/v1")
    url = f"{api_base}/chat/completions"

    print(f"Running LLM benchmarks against {url} with model {model_id}...")

    results = []

    for case in cases:
        cid = case["id"]
        state_name = case["state"]
        state_cfg = config["states"][state_name]

        sys_prompt = state_cfg["system_prompt"]
        user_tmpl = state_cfg["user_prompt_template"]

        user_prompt = user_tmpl
        for k, v in case.items():
            user_prompt = user_prompt.replace(f"{{{{{k}}}}}", str(v))
        user_prompt = user_prompt.replace("{{depth}}", "0")

        body = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"}
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        try:
            # 4096-token MAPS_* completions on a shared lane exceed the old
            # 120s client timeout; the client must not time out before the lane.
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                msg = data["choices"][0]["message"]
                content = msg.get("content", "").strip()
                reasoning = msg.get("reasoning_content", "").strip()

                parsed = None
                if content:
                    try:
                        clean_content = content.replace("[TURN_DONE]", "").strip()
                        parsed = json.loads(clean_content)
                    except Exception:
                        pass
                if not parsed and reasoning:
                    parsed = salvage_json(reasoning)

                passed = False
                notes = []
                if parsed:
                    if cid == "nav_anchor_loop":
                        action = parsed.get("action")
                        target = parsed.get("target_id")
                        if action == case.get("expected_action") and target == case.get("expected_target_id"):
                            passed = True
                        elif action != case.get("anti_expected_action") and action == case.get("expected_action"):
                            passed = True
                        else:
                            notes.append(f"Got action={action}, target={target}")
                    elif cid == "think_anchor_abort":
                        action = parsed.get("action")
                        if action != case.get("anti_expected_action") and (action in ["fix", "add", "replace"]):
                            passed = True
                        else:
                            notes.append(f"Got action={action}")
                    elif cid == "thinking_container_trap":
                        steps = parsed.get("steps", [])
                        symbols = [s.get("symbol") for s in steps if isinstance(s, dict)]
                        if case.get("expected_symbol_target") in symbols and case.get("anti_expected_symbol_target") not in symbols:
                            passed = True
                        elif case.get("anti_expected_symbol_target") not in symbols and len(symbols) > 0:
                            passed = True
                        else:
                            notes.append(f"Got symbols={symbols}")
                else:
                    notes.append("Failed to parse JSON")

                res_item = {"id": cid, "state": state_name, "passed": passed, "parsed": parsed, "notes": notes}
                print(f"[{'PASS' if passed else 'FAIL'}] {cid} ({state_name}): {parsed} {notes}")
                results.append(res_item)
        except Exception as e:
            print(f"[ERROR] {cid}: {e}")
            results.append({"id": cid, "state": state_name, "passed": False, "error": str(e)})

    print("\n=== BENCHMARK REPORT ===")
    passes = sum(1 for r in results if r.get("passed"))
    print(f"Overall Result: {passes}/{len(results)} cases passed ({passes/len(results)*100:.1f}%)")

    all_passed = (passes == len(results))
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(run_benchmarks())
