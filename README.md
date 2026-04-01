# Ariadne: Surgical Code Repair Engine

Ariadne is a language-agnostic, AST-guided code repair engine designed for surgical, non-destructive modifications to large codebases. Unlike traditional LLM coding agents that rewrite entire files, Ariadne uses a **Hierarchical Dataflow State Machine (HFSM)** to identify, extract, and splice exact byte-ranges of code using Tree-sitter.

## 🚀 Key Features

- **Surgical Splicing**: Edits only the specific AST nodes (functions, structs, etc.) requested, preserving file integrity and formatting.
- **Multi-Edit Protocol**: Orchestrates multiple simultaneous edits across different files in a single execution loop.
- **Cognitive Feedback Loop**: Automatically runs compilers/test-runners and feeds errors back to the LLM for autonomous self-correction.
- **Language Agnostic**: Modular "Language Profiles" (Rust, Python, etc.) allow for universal support with minimal configuration.
- **Decoupled Configuration**: Control model selection, prompt templates, and post-processing per-state via `ariadne_config.json`.

## 🏗️ Architecture: The Self-Healing Cycle

Ariadne operates as a deterministic **Hierarchical Finite State Machine (HFSM)**:
1.  **TRIAGE**: Distills raw user intent into a precise technical objective.
2.  **DISPATCH**: Generates a test contract that defines the expected behavior and failure state.
3.  **EVALUATE**: Executes the test suite and captures the compiler or runtime output.
4.  **THINKING (Architect)**: Analyzes the test failure and source skeletons to create a logical repair plan (resolving naming mismatches like `Hero` vs `Entity`).
5.  **SEARCH**: Map the plan's symbols to the codebase.
6.  **SENSE**: Acquires exact byte coordinates using Tree-sitter queries.
7.  **CODING (Coder)**: Generates a surgical JSON patch for the specific AST nodes.
8.  **SYNTAX_GATE**: Validates the generated code before it touches the disk.
9.  **ACTUATE**: Splices the patch in reverse byte-order to maintain offset integrity.

## 🛠️ Configuration & LLMs

Ariadne is optimized for local `llama-server` and `Ollama` setups. Configure your models and prompts in `ariadne_config.json`:
```json
{
  "default": {
    "model": "openai/llama-cpp",
    "api_base": "http://localhost:8080/v1"
  }
}
```
The engine is resilient to LLM "yapping" and thinking tokens (e.g., DeepSeek/Qwen), using robust JSON extraction logic to ensure reliable structured output.

## 📖 Usage

Run the engine from the root of your target project:

```bash
python engine.py --targets src/main.rs --intent "Add error handling to the process_data function"
```

### Advanced Flags
- `--initial-state`: Start the engine from a specific point (e.g., `EVALUATE`).
- `--config`: Point to a custom LLM configuration file.
- `--profile`: Specify the language profile (default: `rust`).

## 📜 License
GPL v3

---

## 📝 Recent Development Notes (Session Summary)

### **Headless & MCP-Augmented Infrastructure**
This session evolved Ariadne into a **headless-capable, MCP-augmented framework** suited for small-context models like Qwen 2.5 (9b).

1.  **Headless RPC Intervention**:
    *   `INTERVENE` state now supports external editors via **Neovim RPC** (`nvim --server 127.0.0.1:6666 --remote`).
    *   Execution pauses in the terminal to allow manual file edits in a remote editor instance.
2.  **Agnostic Documentation (DOCS State)**:
    *   Added a `DOCS` state and `QueryMCP` primitive using the official `mcp` SDK.
    *   Supports retrieving context via local MCP servers or falling back to raw `cargo doc` HTML.
3.  **MAPS Navigation Fixes**:
    *   **Loop Prevention**: Added feedback loops to prevent the LLM from attempting to navigate beyond the current AST symbol root.
    *   **ID Mapping Fix**: Resolved a critical type mismatch between string IDs from LLMs and integer keys in the Tree-sitter `id_map`.
4.  **Rust Project Support**:
    *   Upgraded `scripts/run_rust_tests.py` to use `cargo test` within the target project directory, correctly resolving Godot-Rust crate dependencies.

### **3-Phase Ghost AST Pipeline & LSP Integration**
This session overhauled the `MAPS` state into a deterministic surgical pipeline using `jonrad/lsp-mcp` for ambient diagnostics.

1.  **3-Phase Surgical Loop**:
    *   `MAPS_NAV`: Pure AST navigation (zoom/up) to lock onto a specific node ID.
    *   `MAPS_THINK`: Diagnosis phase using plain-text markdown to draft fixes with LSP hover/type data.
    *   `MAPS_SURGEON`: Final data entry phase to format the draft into a strict JSON edit.
2.  **LSP Integration (`lsp-mcp`)**:
    *   Implemented `LSPManager` to maintain a persistent connection to `rust-analyzer`.
    *   Added **Shadow Buffer Validation**: Edits are now validated in an in-memory virtual buffer against live LSP diagnostics *before* being written to disk.
    *   Implemented `find_project_root` to ensure the LSP server starts in the correct target directory (e.g., `TexelSplatting`).
3.  **Environment & Logic Fixes**:
    *   Switched toolchain to GNU to enable `rust-analyzer` support on Windows.
    *   Added explicit feedback in `MAPS_NAV` to prevent self-zooming loops.
    *   Removed the redundant `DOCS` state; real-time LSP hover data is now the primary documentation source.

**Next Steps**: Refine the Architect's (`THINKING`) ability to distinguish between `struct` and `impl` blocks in Rust to avoid structural navigation deadlocks.
