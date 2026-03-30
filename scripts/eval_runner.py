import subprocess
import time
import json
import re
import sys

BENCHMARKS = [
    {
        "name": "Rust Math Bug",
        "target": "benchmarks/rust_math/math.rs",
        "profile": "rust",
        "intent": "Fix the add function to correctly add two numbers instead of subtracting.",
        "test_contract": "benchmarks/rust_math/test_contract.rs"
    },
    {
        "name": "Rust Entity Armor",
        "target": "benchmarks/rust_state/entity.rs",
        "profile": "rust",
        "intent": "Implement armor mitigation (subtract armor from damage, minimum 0) and death state (is_dead = true when health <= 0) in take_damage.",
        "test_contract": "benchmarks/rust_state/test_contract.rs"
    },
    {
        "name": "Python Calculator Multiply",
        "target": "benchmarks/python_logic/calculator.py",
        "profile": "python",
        "intent": "Fix the multiply method to return the product of a and b instead of sum.",
        "test_contract": "benchmarks/python_logic/test_contract.py"
    }
]

def run_benchmark(bench):
    print(f"=== Running Benchmark: {bench['name']} ===")
    start_time = time.time()
    
    # We bypass TRIAGE/DISPATCH by providing the test contract directly if possible.
    # Currently engine.py takes --targets and --intent and --initial-state.
    # We'll start from THINKING, but we need to ensure the test_contract is used.
    # engine.py hardcodes test_contract.rs for DISPATCH, but let's copy the benchmark test contract to the workspace root.
    
    import shutil
    import os
    
    # Copy target file to root or just run in-place?
    # The engine creates test_contract.rs or test_contract.py in the working directory.
    ext = ".rs" if bench["profile"] == "rust" else ".py"
    test_file = f"test_contract{ext}"
    shutil.copy(bench["test_contract"], test_file)
    
    cmd = [
        sys.executable, "engine.py",
        "--targets", bench["target"],
        "--profile", bench["profile"],
        "--intent", bench["intent"],
        "--initial-state", "EVALUATE" # Start from evaluate to see it fail, then THINKING -> MAPS
    ]
    
    process = subprocess.run(cmd, capture_output=True, text=True)
    end_time = time.time()
    
    output = process.stdout + "\n" + process.stderr
    
    # Parse output
    success = "Engine dropped to terminal state: SUCCESS" in output
    
    # Extract total time from benchmarks
    benchmark_lines = re.findall(r"\[BENCHMARK\] .*? took ([\d\.]+)s", output)
    total_state_time = sum(float(t) for t in benchmark_lines)
    
    # Count retries
    retries = output.count("Tests failed. Transitioning to THINKING.")
    
    # Just basic token proxy: count LLM REQUEST/RESPONSE lines
    llm_calls = output.count("[LLM REQUEST]")
    
    result = {
        "name": bench["name"],
        "success": success,
        "time_seconds": round(end_time - start_time, 2),
        "state_time_seconds": round(total_state_time, 2),
        "retries": retries,
        "llm_calls": llm_calls,
        "log": output[-2000:] # save last 2k chars of log
    }
    
    print(f"Result: {'PASS' if success else 'FAIL'} in {result['time_seconds']}s with {retries} retries.")
    return result

def main():
    results = []
    for bench in BENCHMARKS:
        res = run_benchmark(bench)
        results.append(res)
        
    print("\n\n=== BENCHMARK REPORT ===")
    successes = sum(1 for r in results if r["success"])
    print(f"Overall Patch Success Rate: {successes}/{len(results)} ({successes/len(results)*100:.1f}%)")
    
    for r in results:
        print(f"\n- {r['name']}: {'SUCCESS' if r['success'] else 'FAILED'}")
        print(f"  Time: {r['time_seconds']}s")
        print(f"  Retries: {r['retries']}")
        print(f"  LLM Calls: {r['llm_calls']}")
        
    with open("benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)
        
    if successes < len(results):
        print("\nSome benchmarks failed!")
        sys.exit(1)
        
if __name__ == "__main__":
    main()
