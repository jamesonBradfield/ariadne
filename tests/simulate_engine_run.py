import sys
from unittest.mock import MagicMock, patch
import os
import tempfile
import json
import logging

# Add project root to sys.path
sys.path.append(os.getcwd())

# Import engine after path setup
from engine import main

def test_full_engine_run():
    # Setup temporary file
    # fn add(a: i32, b: i32) -> i32 { a - b }
    # named_children: 
    # 0: identifier (add)
    # 1: parameters
    # 2: i32 (return type)
    # 3: block
    content = b"fn add(a: i32, b: i32) -> i32 {\n    a - b\n}\n"
    with tempfile.NamedTemporaryFile(suffix=".rs", delete=False) as tf:
        tf.write(content)
        target_path = tf.name

    # Mock LLM Responses in sequence
    # Note: QueryLLM.tick is called in many states. 
    # TRIAGE, DISPATCH, THINKING, ROUTER, MAPS
    
    responses = [
        # 1. TRIAGE
        ("SUCCESS", "Fix the add function to correctly add two numbers instead of subtracting."),
        # 2. DISPATCH
        ("SUCCESS", "fn main() { assert_eq!(add(2, 2), 4); }"),
        # 3. EVALUATE (triggered by engine loop) - ExecuteCommand is mocked separately
        
        # 4. THINKING
        ("SUCCESS", {"reasoning": "Need to change - to +", "steps": [{"symbol": "add"}]}),
        
        # 5. ROUTER (from THINKING -> SEARCH)
        ("SUCCESS", {"next_state": "SEARCH", "reasoning": "Plan ready"}),
        
        # 6. SENSE (no LLM call)
        
        # 7. MAPS (1: zoom into block)
        # function_item named_children: identifier, parameters, (optional) return_type, block
        # For 'fn add(a: i32, b: i32) -> i32 { ... }', 
        # index 0: add, 1: parameters, 2: i32, 3: block
        ("SUCCESS", {"action": "zoom", "target_id": 3}), 
        
        # 8. MAPS (2: replace expression)
        # block named_children: binary_expression (0)
        ("SUCCESS", {"action": "replace", "target_id": 0, "code": "    a + b"}),
        
        # 9. MAPS (3: done)
        ("SUCCESS", {"action": "done"}),
        
        # 10. SYNTAX_GATE (no LLM call)
        # 11. ACTUATE (no LLM call)
        # 12. SENSE (checks for more steps, but idx=1 >= steps=1, so goes to EVALUATE)
        # 13. EVALUATE (Success!)
        
        # 14. POST_MORTEM (actually not called if we end at SUCCESS)
        # Wait, the engine loop continues until context.current_state == "FINISH"
        # ROUTER is called if EVALUATE is success? No, EVALUATE success -> SUCCESS state -> POST_MORTEM -> FINISH
    ]
    
    responses_iter = iter(responses)

    def mock_tick(mock_self, prompt_data):
        try:
            val = next(responses_iter)
            print(f"MOCK LLM ({prompt_data.get('system', 'No System')[:30]}...): {val[1]}")
            return val
        except StopIteration:
            print("MOCK LLM: No more responses, returning FINISH")
            return ("SUCCESS", {"next_state": "FINISH", "reasoning": "Out of mock responses"})

    # Patch QueryLLM.tick and PromptUser.tick (to auto-approve DISPATCH)
    with patch("ariadne.states.QueryLLM.tick", side_effect=mock_tick, autospec=True):
        with patch("ariadne.primitives.PromptUser.tick", return_value=("SUCCESS", True)):
            # Patch ExecuteCommand to simulate test success (after repair)
            # 1st call: Failure (EVALUATE before repair)
            # 2nd call: Success (EVALUATE after repair)
            with patch("ariadne.primitives.ExecuteCommand.tick") as mock_exec:
                mock_exec.side_effect = [
                    ("ERROR", "test failed: 2 - 2 != 4"), # 1st EVALUATE
                    ("SUCCESS", "test passed!")            # 2nd EVALUATE
                ]
                
                # Mock sys.argv
                sys.argv = [
                    "engine.py",
                    "--targets", target_path,
                    "--profile", "rust",
                    "--intent", "fix add",
                    "--initial-state", "TRIAGE",
                    "--headless", # Skip editor
                    "--log-level", "ERROR" # Keep it quiet
                ]
                
                print(f"\n--- SIMULATING ENGINE RUN ON {target_path} ---")
                main()
                
    # Verify file content
    with open(target_path, "r") as f:
        final_code = f.read()
    
    print("\n--- FINAL CODE ON DISK ---")
    print(final_code)
    
    if "a + b" in final_code:
        print("\n✅ SUCCESS: Engine correctly orchestrated the repair.")
    else:
        print("\n❌ FAILURE: Engine did not modify the file correctly.")
        
    os.remove(target_path)
    if os.path.exists("test_contract.rs"):
        os.remove("test_contract.rs")

if __name__ == "__main__":
    test_full_engine_run()
