# Ariadne: Surgical Code Repair Engine

Ariadne is a language-agnostic, AST-guided code repair engine designed for surgical, non-destructive modifications to large codebases. Unlike traditional LLM coding agents that rewrite entire files, Ariadne uses a **Hierarchical Finite State Machine (HFSM)** to identify, extract, and splice exact byte-ranges of code using Tree-sitter.

## 🚀 Key Features

- **Batch Processing**: Discovers and processes multiple code nodes in a single session before editing.
- **Headless Event-Driven Engine**: Decoupled from the TUI; orchestrates via a central event bus (`EngineContext`).
- **Pushdown Automata AST Navigation**: 
  - **Discovery Mode**: Finds all matching symbols before navigation begins.
  - **Amnesic Execution**: Clears navigation stack but preserves tracked nodes for batch processing.
- **Surgical Splicing**: Edits only the specific AST nodes (functions, structs, etc.) requested, preserving file integrity and formatting.
- **Data-Driven Profiles**: Language logic (AST queries, test runners) is defined in portable JSON schemas (`ariadne/profiles/`).
- **Cognitive Feedback Loop**: Automatically runs compilers/test-runners and feeds errors back to the LLM for autonomous self-correction.
- **LSP Integration**: Real-time diagnostics and "Ghost Checks" to validate code before it hits the disk via `jonrad/lsp-mcp`.

## 📉 The Amnesic Token Budget (Empirically Verified)

Ariadne is engineered for extreme efficiency. Using `tiktoken` for real-time measurement, we've confirmed a **~98% reduction** in token consumption compared to standard coding agents.

| Metric | Standard Coding Agent | Ariadne (Empirical) | Savings |
| :--- | :--- | :--- | :--- |
| **Context per Turn** | 15,000 - 50,000+ tokens | **~500 - 900 tokens** | **~98%** |
| **Total Session Budget** | 500,000 - 1M+ tokens | **~21,000 tokens** | **~98%** |
| **Input Strategy** | Full File + Chat History | Amnesic (Target Node Only) | Recursive |
| **Hallucination Risk** | High (Context Poisoning) | **Zero** (Constrained View) | Surgical |
| **Inference Speed** | Slow (Time-to-First-Token) | **Instant** | High-Speed |

> **Measurement**: Figures based on a 40-transition "Cold Surgery" session using `tiktoken` (cl100k_base) on a complex Rust-Godot project.

### How we do it:
1.  **Pushdown Automata**: Instead of reading the whole file, we navigate the AST depth-by-depth.
2.  **Context Constriction**: The LLM only sees the immediate children of the current node ID.
3.  **Amnesic Execution**: Chat history is discarded between navigation steps. The model only knows its current `Intent` and its current `Depth`.

## 🏗️ Architecture: The Surgical HFSM

Ariadne operates as a deterministic **Hierarchical Finite State Machine (HFSM)**:

```
DISPATCH → EVALUATE → [THINKING → MAPS_NAV → MAPS_THINK → MAPS_SURGEON → ACTUATE] → POST_MORTEM
                              ↑                                    ↓
                              └────────── Batch Loop ────────────────┘
```

### State Flow

1.  **DISPATCH**: Generates a test contract that defines the expected behavior and failure state.
2.  **EVALUATE**: Executes the test suite and captures the compiler or runtime output.
3.  **THINKING (Architect)**: Analyzes the test failure and source skeletons to create a logical repair plan with LSP reference search.
4.  **MAPS_NAV (Discovery)**: Finds all matching symbols in the codebase before editing.
5.  **MAPS_THINK (Diagnosis)**: Reviews each tracked node and drafts repair strategies.
6.  **MAPS_SURGEON (Formatting)**: Validates edits with LSP diagnostics (Ghost Check) before applying.
7.  **ACTUATE (Splicing)**: Applies edits and loops back to process remaining tracked nodes.
8.  **POST_MORTEM**: Generates self-optimization cases on high retry counts or failures.

### Out-of-Band States (Not in Main Flow)

- **FILE_EXPLORER**: An interactive exploration tool for manual codebase navigation. Use `cd`, `ls`, `preview`, and `spawn` to investigate before starting repairs. Not integrated into the automated repair loop - the HFSM is still taking shape.
- **SPAWN**: Converts `FILE_EXPLORER` investigation points into a repair plan for the main HFSM flow.

### Removed States (v2)
- **TRIAGE**: Intent is now passed directly to THINKING
- **ROUTER/SEARCH/SENSE**: Replaced by deterministic batch discovery in MAPS_NAV
- **SYNTAX_GATE**: Redundant with LSP diagnostics

## 🚀 Recent Success: Batch Processing Refactor (April 2026)

Ariadne's HFSM architecture was refactored to implement batch processing:

1.  **Removed Redundant States**: Eliminated TRIAGE, ROUTER, SEARCH, SENSE, and SYNTAX_GATE states.
2.  **Implemented Discovery Mode**: `MAPS_NAV` now finds all matching symbols before navigation begins.
3.  **Amnesia Pattern**: Navigation stack cleared but tracked nodes preserved for batch processing.
4.  **JSON Profile Migration**: Language profiles moved from Python to portable JSON schemas.
5.  **LSP Reference Search**: `THINKING` state now finds all references to a symbol before repair.
6.  **Batch Loop**: `MAPS_NAV → MAPS_THINK → MAPS_SURGEON → ACTUATE` processes multiple nodes deterministically.
7.  **Ghost Check**: LSP diagnostics validated before edits hit disk.
8.  **Self-Optimization**: `POST_MORTEM` generates optimization cases on high retry counts.

All 8 integration tests passing, including `test_multi_position_edit` for batch processing validation.

> **Note**: The HFSM architecture is still evolving. We're intentionally keeping states like `FILE_EXPLORER` (an interactive exploration tool) separate from the automated repair loop, as the core state machine is still taking shape. Integration decisions will be guided by empirical results, not premature optimization.

## 🛠️ Configuration & LLMs

Ariadne is optimized for local `llama-server` and `Ollama` setups (e.g., Qwen3.5-9B). Configure your models and prompts in `ariadne_config.json`:

```json
{
  "default": {
    "model": "openai/Qwen3.5-9B-Q6_K.gguf",
    "api_base": "http://localhost:8080/v1"
  }
}
```

The engine uses **Pydantic models** for strict structured output and implements **Stop Sequences** (`[TURN_DONE]`) to prevent model yapping and infinite reasoning loops.

## 📖 Usage

Run the engine from the root of your target project:

```bash
python engine.py --targets src/main.rs --intent "Add error handling to the process_data function" --tui
```

### Advanced Flags
- `--tui`: Launch the interactive Aider-style interface.
- `--initial-state`: Start the engine from a specific point (e.g., `EVALUATE`).
- `--max-turns`: Set the maximum number of state transitions (default: 40).

## 📊 Test Results

```
pytest tests/ ──────────────────────────────────────────────────────────────── ✅ 8 passed
├── test_integration_repair.py::test_rust_batch_processing ──────────────── ✅
├── test_integration_repair.py::test_maps_batch_processing ───────────────── ✅
├── test_integration_repair.py::test_multi_position_edit ─────────────────── ✅
├── test_cargo_check.py::test_cargo_check_hook_structure ─────────────────── ✅
├── test_syntax_gate.py::test_syntax_gate_valid_rust ─────────────────────── ✅
├── test_syntax_gate.py::test_syntax_gate_invalid_rust ───────────────────── ✅
├── test_subprocess.py::test_subprocess_sensor_success ───────────────────── ✅
└── test_subprocess.py::test_subprocess_sensor_fail ──────────────────────── ✅
```

See [ROADMAP.md](ROADMAP.md) for detailed test coverage and future plans.

## 📜 License
GPL v3
