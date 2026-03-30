# Objective
Replace the `CODING` state with a new `MAPS` state (Micro AST Procedural Surgeon) that implements the "AST Drill-Down Protocol".

# Background & Motivation
The `CODING` state currently asks the LLM to rewrite an entire extracted AST node (e.g., a full function). This can be slow and error-prone for large functions because the LLM must generate the entire function body. The `MAPS` state allows the LLM to navigate the AST of the extracted node step-by-step and make precise byte-level edits (zoom, replace, insert_before, insert_after, delete) to specific sub-nodes, saving tokens and eliminating hallucination risk in untouched code.

# Scope & Impact
*   **`ariadne/states.py`**: Add `MAPS(State)` and remove `CODING(State)`. Change `SENSE` transition from `CODING` to `MAPS`. Change `MAPS` to transition to `SYNTAX_GATE` when finished.
*   **`ariadne_config.json`**: Add `MAPS` prompt configuration. Remove `CODING`.
*   **`engine.py`**: Replace `CODING` with `MAPS` in `states_registry`.

# Implementation Steps
1.  **Define `MAPS` in `ariadne/states.py`**:
    *   Initialize tracking state in `job` (e.g., `job.maps_state` dict) to track the current symbol index and node navigation history (stack of `(start_byte, end_byte)`).
    *   Re-parse the target file. Find the AST node matching the current navigation state (starting at the `extracted_node` boundary from `SENSE`).
    *   Render the node's named children with integer IDs (`[0] type: snippet...`).
    *   Query the LLM with the intent, error feedback, and the rendered node view.
    *   The LLM must output a JSON action: `{"action": "zoom", "target": <id>}`, `{"action": "replace", "target": <id>, "code": "..."}`, `{"action": "up"}`, or `{"action": "done"}`.
    *   If `zoom`, push the target's `(start_byte, end_byte)` to the history stack and return `("MAPS", job)`.
    *   If `up`, pop the history stack and return `("MAPS", job)`.
    *   If an edit (`replace`, `insert_before`, `insert_after`, `delete`), append to `job.fixed_code["edits"]` (using the target node's byte offsets) and return `("MAPS", job)` so it can continue editing if needed.
    *   If `done`, move to the next extracted symbol. If all symbols are done, return `("SYNTAX_GATE", job)`.

2.  **Update `ariadne_config.json`**:
    *   Create `MAPS` system and user prompts.
    *   System Prompt: "You are the Micro AST Procedural Surgeon (MAPS). Navigate the AST to apply surgical edits. Valid actions: 'zoom', 'up', 'replace', 'insert_before', 'insert_after', 'delete', 'done'. Output a SINGLE JSON object: {\"reasoning\": \"...\", \"action\": \"...\", \"target\": 0, \"code\": \"...\"}"

3.  **Update `engine.py`**:
    *   Replace `CODING` with `MAPS`.

# Verification & Testing
1.  Run the engine on `test_contract.rs`.
2.  Observe the LLM looping through `MAPS`, zooming into the `take_damage` block, and performing a `replace` or `insert_after` to add `self.is_dead = true;`.