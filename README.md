# Ariadne: Surgical Code Repair Engine

Ariadne is a language-agnostic, AST-guided code repair engine designed for surgical, non-destructive modifications to large codebases. Unlike traditional LLM coding agents that rewrite entire files, Ariadne uses a **Hierarchical Dataflow State Machine (HFSM)** to identify, extract, and splice exact byte-ranges of code using Tree-sitter.

## 🚀 Key Features

- **Surgical Splicing**: Edits only the specific AST nodes (functions, structs, etc.) requested, preserving file integrity and formatting.
- **Multi-Edit Protocol**: Orchestrates multiple simultaneous edits across different files in a single execution loop.
- **Cognitive Feedback Loop**: Automatically runs compilers/test-runners and feeds errors back to the LLM for autonomous self-correction.
- **Language Agnostic**: Modular "Language Profiles" (Rust, Python, etc.) allow for universal support with minimal configuration.
- **Decoupled Configuration**: Control model selection, prompt templates, and post-processing per-state via `ariadne_config.json`.

## 🏗️ Architecture

Ariadne operates as a state machine:
1.  **TRIAGE**: Analyzes user intent.
2.  **DISPATCH**: Generates a test contract to define the failure state.
3.  **EVALUATE**: Runs the project's test suite and captures compiler/runtime errors.
4.  **SEARCH**: Identifies the specific symbols (nodes) causing the failure.
5.  **SENSE**: Acquires the exact byte coordinates of the target nodes.
6.  **CODING**: Uses an LLM to generate surgical JSON-formatted patches.
7.  **ACTUATE**: Splices the patches in reverse byte-order to maintain offset integrity.

## 🛠️ Setup

1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
2.  Configure your LLM endpoints in `ariadne_config.json`.
3.  Ensure you have your language-specific compilers (e.g., `rustc`, `python`) in your PATH.

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
MIT
