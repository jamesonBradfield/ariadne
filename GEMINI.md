# Ariadne: Surgical Code Repair Engine

Ariadne is a language-agnostic, AST-guided code repair engine designed for surgical, non-destructive modifications to large codebases. It uses a **Hierarchical Dataflow State Machine (HFSM)** to identify, extract, and splice exact byte-ranges of code using Tree-sitter.

## Architecture

Ariadne operates as a deterministic HFSM, transitioning through a series of specialized states:
1.  **TRIAGE**: Distills user intent into a precise technical objective.
2.  **DISPATCH**: Generates a test contract based on the language profile and target skeletons.
3.  **EVALUATE**: Executes the test suite and captures output (compiler/runtime errors).
4.  **THINKING**: Analyzes failures and skeletons to create a logical repair plan.
5.  **SEARCH**: Maps symbols from the plan to the codebase.
6.  **SENSE**: Acquires exact byte coordinates using Tree-sitter queries.
7.  **CODING**: Generates surgical JSON patches for specific AST nodes.
8.  **SYNTAX_GATE**: Validates generated code before disk write.
9.  **ACTUATE**: Splices patches in reverse byte-order to maintain offset integrity.

## Development Mandates
### 1. Configuration & Prompts
- **NEVER** hardcode prompts or model parameters within `states.py`.
- **ALWAYS** use `ariadne_config.json` for prompt templates, system instructions, and LLM parameters.
- Use the `ConfigManager` in `engine.py` to retrieve state-specific configurations.

### 2. Language Extensibility
- Language-specific logic (AST queries, test runners, file extensions) **MUST** reside in `ariadne/profiles/`.
- To support a new language, create a new profile class inheriting from `BaseProfile`.

### 3. State & Primitive Separation
- **Primitives (`ariadne/primitives.py`)**: Atomic, reusable operational blocks (e.g., `QueryLLM`, `ExtractAST`, `ExecuteCommand`). They should be side-effect focused and language-agnostic where possible.
- **States (`ariadne/states.py`)**: High-level logical steps in the HFSM. They orchestrate primitives and manage data flow between states via payloads.

### 4. Surgical Editing Philosophy
- Ariadne's core value is **non-destructive splicing**.
- Avoid full-file rewrites. Always prefer extracting specific nodes, modifying them, and splicing them back.
- Use Tree-sitter for all code identification and validation tasks.

### 5. Testing & Validation
- Every fix should be driven by a failing test (generated in `DISPATCH` or provided by the user).
- Use `SYNTAX_GATE` to prevent invalid code from being written to disk.

### 6. Formatting Strictness
- **CRITICAL:** Output absolutely NO Carriage Returns (`\r`).
- Always use strict Unix line endings (`\n` / LF) for all file writes, patches, and code generation. Do not use CRLF.

### 7. Shell Execution Environment (MSYS2/Zsh)
- **Context:** The host terminal is Zsh running inside MSYS2 on Windows via WezTerm.
- **CRITICAL:** Do NOT use `&&` to chain terminal commands. The CLI sub-shell routing will fail to parse it correctly in this environment.
- **MANDATE:** ALWAYS use `;` (semicolon) to separate and chain sequential commands.
- **Pathing:** Be mindful of MSYS2 path translation (e.g., `/c/` vs `C:\`) if executing raw Python scripts or Node commands.

## Key Files
- `engine.py`: Entry point and HFSM orchestrator.
- `ariadne/core.py`: Core abstractions (`State`, `EngineContext`).
- `ariadne/payloads.py`: Data structures for state transitions (`JobPayload`).
- `ariadne/components.py`: Higher-level components like `TreeSitterSensor`.
- `ariadne_config.json`: The "brain" of the engine (prompts and model settings).

## Future Architecture Target: The AST Drill-Down Protocol

Instead of a single `CODING` state, Ariadne will eventually transition to an interactive `MAPS` state where the LLM is given a gamified, tight context of its current `Depth` and navigates the AST recursively.

### The Protocol Loop
1. **Context Constriction**: The LLM is only shown the current depth level of the AST (e.g., a file skeleton, or the direct children of a specific function block), with temporary navigation IDs for each node.
2. **The Tools (Controller)**: The LLM is restricted to the following exact moves:
      - `zoom(node_id)`: Steps one layer deeper into the AST to view its contents.
      - `replace(node_id, new_code)`: Deletes the specific byte-range of that node and drops in the new text.
      - `insert_before` / `insert_after(node_id, new_code)`: Splices new code precisely at the start or end byte of the target node.
      - `delete(node_id)`: Snips the node out of the file entirely.
3. **Amnesic Execution**: Every time the LLM zooms or edits, chat history is wiped. The only input is the `INTENT` and the `CURRENT_DEPTH` view.
4. **Diff view**: As it marks or edits files/functions, we can add the context to the nav.

### Why this is the Ultimate Architecture
- **Zero Hallucination Risk**: The model cannot introduce syntax errors into surrounding code because it never generates or sees it.
- **Token Economy**: The context window never exceeds a few hundred tokens, meaning time-to-first-token is practically instant. Allows for lightning-fast edits on huge files, specifically optimal for local models like Qwen3-8B.
- **Drive-by-Wire Precision**: Replaces the 'code writer' paradigm with a 'code surgeon' paradigm, mapping perfectly to the HFSM structure and Tree-sitter byte-offset splicing.
