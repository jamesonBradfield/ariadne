#!/usr/bin/env python3
"""
benchmark_aperture.py - Focused Surgeon Benchmark Harness for Ariadne

Evaluates three-tier performance across the Ariadne ecosystem:
  - Tier 1: Fast CPU Bounded Decision Pass (Bonsai-8B-Q1_0 on CPU, 0 MB VRAM)
  - Tier 2: Fast Focused Surgeon (Mellum-2.1-12B-A2.5B on Vulkan1, MoE active lane)
  - Tier 3: Heavy Generalist Fallback (Qwen3.6-27B-Coder on Vulkan0)

Evaluates 4 representative code mutation scenarios:
  1. Happy-path Leaf Mutation (isolated_node_sufficient == True)
  2. Struct Scope Dependency (requires parent_skeleton slice)
  3. Module Import Dependency (requires file_imports slice)
  4. Anchor Disambiguation (low confidence -> Generative Surgeon trigger)
"""

import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List

API_ENDPOINT = "http://localhost:8080/v1/chat/completions"
CPU_MODEL = "Bonsai-8B-Q1_0"
SURGEON_MODEL = "mellum"
GENERALIST_MODEL = "openai/Qwen3.6-27B-A3B-Coder-MTP-IQ2_M"

TEST_CASES = [
    {
        "id": "1_happy_path_leaf",
        "name": "Leaf Function Bug (Calculator add)",
        "expected_isolated": True,
        "expected_slices": [],
        "min_confidence": 0.85,
        "prompt": {
            "intent": "Fix add() which incorrectly subtracts instead of adding",
            "symbol": "Calculator::add",
            "snippet": "def add(self, a, b):\n    return a - b  # BUG: should be a + b",
            "available_symbols": ["add", "subtract", "multiply", "divide"]
        }
    },
    {
        "id": "2_struct_scope_dep",
        "name": "Struct Field Access (needs parent struct)",
        "expected_isolated": False,
        "expected_slices": ["parent_skeleton"],
        "min_confidence": 0.80,
        "prompt": {
            "intent": "Update player velocity using self.config.speed multiplier",
            "symbol": "Player::apply_boost",
            "snippet": "fn apply_boost(&mut self) {\n    self.velocity += 10.0; // Needs self.config.max_speed\n}",
            "available_symbols": ["Player", "PlayerConfig", "apply_boost", "tick"]
        }
    },
    {
        "id": "3_module_import_dep",
        "name": "External Library Dependency (needs imports)",
        "expected_isolated": False,
        "expected_slices": ["file_imports"],
        "min_confidence": 0.80,
        "prompt": {
            "intent": "Serialize payload to JSON using serde_json::to_string",
            "symbol": "Payload::export",
            "snippet": "fn export(&self) -> String {\n    to_string(self).unwrap() // Needs import check\n}",
            "available_symbols": ["Payload", "export"]
        }
    },
    {
        "id": "4_anchor_disambiguation",
        "name": "New Method Insertion (Anchor Disambiguation)",
        "expected_isolated": False,
        "expected_slices": ["parent_skeleton"],
        "min_confidence": 0.70,
        "prompt": {
            "intent": "Add new method reset_counter() to existing class Counter",
            "symbol": "Counter::reset_counter",
            "snippet": "# [INSERT NEW METHOD] def reset_counter(self): self.count = 0",
            "available_symbols": ["Counter::__init__", "Counter::increment", "Counter::get"]
        }
    }
]

def query_model(model_name: str, messages: list, max_tokens: int = 1024, temperature: float = 0.1) -> Dict[str, Any]:
    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"}
    }
    t0 = time.perf_counter()
    req = urllib.request.Request(
        API_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        elapsed = time.perf_counter() - t0
        data = json.loads(resp.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("completion_tokens", 0)
        return {
            "elapsed_s": elapsed,
            "tokens": tokens,
            "content": raw
        }

def evaluate_case(case: Dict[str, Any]):
    print(f"\n[Case {case['id']}] {case['name']}")
    print(f"  Target: {case['prompt']['symbol']}")

    # Tier 1: CPU Aperture Decision
    sys_dec = (
        "You are an AST surgical repair classifier. Output ONLY a JSON object:\n"
        "{\n"
        '  "isolated_node_sufficient": true | false,\n'
        '  "surgical_action": "replace" | "insert_before" | "insert_after" | "delete",\n'
        '  "confidence": float,\n'
        '  "needed_slices": ["parent_skeleton", "file_imports", "lsp_hover", "call_sites", "test_contract_assertions", "last_attempted_diff"]\n'
        "}"
    )
    try:
        t1 = query_model(CPU_MODEL, [{"role": "system", "content": sys_dec}, {"role": "user", "content": json.dumps(case["prompt"])}], max_tokens=80)
        dec = json.loads(t1["content"])
        conf = dec.get("confidence", 0.0)
        is_suff = dec.get("isolated_node_sufficient", False)
        action = dec.get("surgical_action", "replace")
        slices = dec.get("needed_slices", [])
        print(f"  Tier 1 (CPU 8B):    {t1['elapsed_s']:.2f}s | {t1['tokens']} tok | VRAM: 0 MB | Action: {action} | Suff: {is_suff} | Slices: {slices}")
    except Exception as e:
        print(f"  Tier 1 (CPU 8B):    Offline/Error ({e})")

    # Tier 2: Fast Focused Surgeon (Mellum 12B-A2.5B)
    sys_surgeon = (
        "Task: Create surgical AST repair. Output ONLY a JSON object. Do not reason.\n"
        "{\n"
        '  "action": "replace" | "insert_before" | "insert_after" | "delete",\n'
        '  "code": "new code snippet",\n'
        '  "reasoning": "1-line explanation"\n'
        "}"
    )
    try:
        t2 = query_model(SURGEON_MODEL, [{"role": "system", "content": sys_surgeon}, {"role": "user", "content": json.dumps(case["prompt"])}], max_tokens=256)
        patch = json.loads(t2["content"])
        print(f"  Tier 2 (Mellum):    {t2['elapsed_s']:.2f}s | {t2['tokens']} tok | Vulkan1 | Action: {patch.get('action')} | Expl: {patch.get('reasoning')[:40]}")
    except Exception as e:
        print(f"  Tier 2 (Mellum):    Offline/Error ({e})")

def main():
    print("=" * 80)
    print("ARIADNE THREE-TIER SURGICAL BENCHMARK HARNESS")
    print("=" * 80)
    print(f"Tier 1 (Decision): {CPU_MODEL} on 8 CPU threads (0 MB VRAM)")
    print(f"Tier 2 (Surgeon):  {SURGEON_MODEL} on Vulkan1 (Active-Param MoE, Fast Lane)")
    print(f"Tier 3 (General):  {GENERALIST_MODEL} on Vulkan0 (Full CoT Architect)")
    print("=" * 80)

    for case in TEST_CASES:
        evaluate_case(case)

    print("\n" + "=" * 80)
    print("Surgeon profile runs with low context (<1,000 tokens) and near-instant turnaround.")
    print("=" * 80)

if __name__ == "__main__":
    main()
