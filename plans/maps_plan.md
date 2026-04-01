# Objective
Upgrade the `MAPS` (Micro AST Procedural Surgeon) state into a 3-phase **Deterministic Ghost AST Pipeline** utilizing `jonrad/lsp-mcp` for ambient diagnostics and shadow-buffer validation.

# Background & Motivation
Local 8B models suffer from attention drift and overconfidence when forced to navigate an AST, reason about compiler errors, and format strict JSON edits simultaneously. Furthermore, relying on standard `cargo test` execution for feedback creates a slow, delayed "Fail-Fast" loop that causes the model to lose context. 

By splitting the surgical process into strict Single Responsibility states (NAV, THINK, SURGEON) and validating edits in an in-memory shadow buffer against a live Language Server *before* writing to disk, we eliminate "Ghost AST" desyncs and force the LLM to achieve mathematical correctness deterministically.

# Architecture Overview: The Ghost AST Pipeline

### Layer 1: The Ambient Environment (`lsp-mcp`)
Ariadne integrates `jonrad/lsp-mcp` to run continuously. The Python engine intercepts state transitions to invisibly paint the LLM's prompt with real-time `workspace/diagnostics` and `textDocument/hover` data. The LLM does not explicitly "call" tools; it operates in an LSP-aware environment.

### Layer 2: The 3-Phase Surgical Loop (Strict SRP)
* **1. MAPS_NAV (The Bloodhound):** * *Input:* Text-based AST view annotated with live LSP diagnostics.
    * *Role:* Pure navigation. Uses `zoom` and `up`.
    * *Exit:* Locks onto the exact integer ID of the broken node (`{"action": "select", "target_id": X}`).
* **2. MAPS_THINK (The Diagnostician):**
    * *Input:* The locked node, the error, and the injected LSP type signature (`textDocument/hover`).
    * *Role:* Sanity check on NAV and logic drafting.
    * *Exit:* Writes a plain-text markdown explanation and drafts the code fix. No strict JSON pressure. Can `abort` to kick back to NAV.
* **3. MAPS_SURGEON (The Scalpel):**
    * *Input:* The locked node and THINK's plain-text drafted fix.
    * *Role:* Data entry. Formats the draft into a strict `replace`, `insert_before`, `insert_after`, or `delete` JSON command.

### Layer 3: The Deterministic Ghost Check (Zero-Guessing)
Before writing to disk, the Python engine intercepts the Surgeon's JSON edit:
1.  **Shadow Edit:** Engine applies the edit to an in-memory virtual buffer and sends a `textDocument/didChange` notification to `lsp-mcp`.
2.  **The Math:** Engine queries `workspace/diagnostics` for the new diagnostic count.
3.  **The Route:** * *Errors hit 0:* Flawless victory. Commit to disk.
    * *Errors remain but change message:* Edit rejected. New error is fed directly back to `MAPS_THINK`.
    * *Errors multiply (Cascading failure):* Edit instantly aborted. Shadow buffer reverted. Surgeon is forced to try a new approach.

# Implementation Steps
1.  **Engine Integration (`ariadne/primitives.py` & `states.py`)**:
    * Implement an LSP-MCP wrapper capable of maintaining a shadow buffer (`textDocument/didChange`) and querying `workspace/diagnostics`.
2.  **State Refactoring (`ariadne/states.py`)**:
    * Remove monolithic `MAPS` state.
    * Implement `MAPS_NAV`, `MAPS_THINK`, and `MAPS_SURGEON` classes.
    * Implement the Ghost Check logic inside `MAPS_SURGEON`'s tick method to handle the LSP diffing math.
3.  **Config Updates (`ariadne_config.json`)**:
    * Write specific, isolated system/user prompts for `MAPS_NAV`, `MAPS_THINK`, and `MAPS_SURGEON`.
    * Remove JSON escaping requirements from the `THINK` prompt.
