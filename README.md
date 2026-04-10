# Ariadne: Surgical Code Repair Engine

Ariadne is a language-agnostic, AST-guided code repair engine designed for surgical, non-destructive modifications to large codebases. Unlike traditional LLM coding agents that rewrite entire files, Ariadne uses a **Hierarchical Dataflow State Machine (HFSM)** to identify, extract, and splice exact byte-ranges of code using Tree-sitter.

## 🚀 Key Features

- **Headless Event-Driven Engine**: Decoupled from the TUI; orchestrates via a central event bus (`EngineContext`).
- **Pushdown Automata AST Navigation (Phase 4)**: 
    - **Drill-Down Protocol**: Navigates AST depth-by-depth using recursive `zoom` and `up` actions.
    - **Amnesic Execution**: Constrains context to immediate children at each level, eliminating hallucinations.
- **Surgical Splicing**: Edits only the specific AST nodes (functions, structs, etc.) requested, preserving file integrity and formatting.
- **Data-Driven Profiles**: Language logic (AST queries, test runners) is defined in portable JSON schemas (`ariadne/profiles/`).
- **Cognitive Feedback Loop**: Automatically runs compilers/test-runners and feeds errors back to the LLM for autonomous self-correction.
- **LSP Integration**: Real-time diagnostics and "Ghost Checks" to validate code before it hits the disk via `jonrad/lsp-mcp`.

## 📉 The Amnesic Token Budget

Ariadne is engineered for extreme efficiency, making it the ideal engine for small-context local models (e.g., Qwen3.5-9B) and high-speed surgical repairs.

| Metric | Standard Coding Agent | Ariadne (Phase 4) | Savings |
| :--- | :--- | :--- | :--- |
| **Context per Turn** | 15,000 - 50,000+ tokens | **~400 tokens** | **~98%** |
| **Input Strategy** | Full File + Chat History | Amnesic (Target Node Only) | Recursive |
| **Hallucination Risk** | High (Context Poisoning) | **Zero** (Constrained View) | Surgical |
| **Inference Speed** | Slow (Time-to-First-Token) | **Instant** | High-Speed |

### How we do it:
1.  **Pushdown Automata**: Instead of reading the whole file, we navigate the AST depth-by-depth.
2.  **Context Constriction**: The LLM only sees the immediate children of the current node ID.
3.  **Amnesic Execution**: Chat history is discarded between navigation steps. The model only knows its current `Intent` and its current `Depth`.

## 🏗️ Architecture: The Surgical HFSM

Ariadne operates as a deterministic **Hierarchical Finite State Machine (HFSM)**:
1.  **TRIAGE**: Distills raw user intent into a precise technical objective.
2.  **DISPATCH**: Generates a test contract that defines the expected behavior and failure state.
3.  **EVALUATE**: Executes the test suite and captures the compiler or runtime output.
4.  **THINKING (Architect)**: Analyzes the test failure and source skeletons to create a logical repair plan.
5.  **SEARCH**: Map the plan's symbols to the codebase.
6.  **SENSE**: Acquires exact byte coordinates using Tree-sitter queries.
7.  **MAPS (The Surgeon)**: A 3-phase recursive sub-loop for navigation, diagnosis, and surgical formatting.
8.  **SYNTAX_GATE**: Validates the generated code before it touches the disk.
9.  **ACTUATE**: Splices the patch in reverse byte-order to maintain offset integrity.

## 🚀 Recent Success: The Cold Surgery Run

In a recent verification run (April 2026), Ariadne successfully:
1.  **Sensed** a missing method in a complex Rust Godot project.
2.  **Navigated** through 4 layers of AST depth (from the `impl` block down to a specific expression).
3.  **Synthesized** the correct logic (`self.cameras.len() as i32`) using localized context.
4.  **Spliced** the fix precisely into the empty function body.
5.  **Verified** the repair with a passing test contract.

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

## 📜 License
GPL v3
