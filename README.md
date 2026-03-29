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
