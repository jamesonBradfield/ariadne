# Ariadne: LLM Orchestration Layer (ECU)

Ariadne is a lightweight, decentralized alternative to the Model Context Protocol (MCP). It replaces stochastic "chat-to-diff" agents with a deterministic **Entity-Component-System (ECS)** and **Hierarchical Finite State Machine (HFSM)** architecture in Python.

## Project Overview

- **Purpose:** A high-performance, token-efficient orchestration layer for LLM-driven coding tasks.
- **Key Paradigm:** Strips the heavy LLM of autonomy, using it as a "Pure Function" for code generation, while a smaller, faster LLM (the ECU) handles routing and prompt compilation.
- **Core Technologies:**
  - **Python:** The main engine and state management.
  - **Tree-sitter:** Used for AST-level "Drive-by-Wire" splicing and syntax validation.
  - **LiteLLM:** Unified interface for connecting to various LLM backends (Ollama, OpenAI, etc.).
  - **Language Profiles:** Python-based configurations for language-specific logic (Queries, Parsing, Tooling).

## Architecture & Components

### Language Profile System
Ariadne is language-agnostic. Language-specific logic is defined in `profiles/`:
- `profiles/base.py`: The `LanguageProfile` abstract base class.
- `profiles/rust_profile.py`: Profile for Rust (Tree-sitter queries, `cargo check` integration).
- New languages can be added by implementing a new `LanguageProfile` and registering it in `engine.py:ProfileLoader`.

### The Engine (HFSM)
The execution flow is managed by a state machine (see `engine.py` and `core.py`):
1.  **SEARCH:** Uses the LLM to determine if the intent is already satisfied or what symbol needs editing. Uses `profile.parse_search_result`.
2.  **SENSE:** Uses `TreeSitterSensor` with `profile.get_query` to find the exact byte coordinates.
3.  **CODING:** Compiles a strict prompt and uses `LiteLLMProvider` to generate raw code.
4.  **SYNTAX_GATE:** Validates the generated code using Tree-sitter before any disk write.
5.  **ACTUATE:** Surgically splices the new code into the file using `DriveByWireActuator`.

### Key Files
- `engine.py`: The main entry point, profile loader, and engine runner.
- `core.py`: Definitions for `EngineContext` (storing the active `profile`) and `State`.
- `components.py`: Implementation of `LiteLLMProvider`, `TreeSitterSensor`, `SyntaxGate`, and `DriveByWireActuator`.
- `profiles/`: Directory for language-specific configuration files.

## Building and Running

### Prerequisites
- Python 3.10+
- `pip install tree-sitter litellm`
- Language-specific tree-sitter parsers (e.g., `pip install tree-sitter-rust`).
- An LLM backend (e.g., Ollama running locally).

### Configuration
Set the following environment variables to configure the LLM:
- `ARIADNE_MODEL`: The model to use (default: `ollama/llama3`).
- `ARIADNE_API_BASE`: (Optional) The API base URL for the LLM provider.

### Execution
To run the main engine loop:
```bash
python engine.py
```

## Development Conventions

- **Language Agnosticism:** Never hardcode language-specific logic in `engine.py` or `components.py`. Use the `profile` object.
- **LiteLLM:** Use `LiteLLMProvider` for all LLM interactions to maintain backend flexibility.
- **Surgical Edits:** Use Tree-sitter byte-level coordinates for all file modifications.
- **Profile-Driven Tooling:** Move build/lint/test commands into the language profiles.

## TODO / Roadmap
- [ ] Implement a `PythonProfile` to demonstrate multi-language support.
- [ ] Add support for "Hooks" (pre/post-execution scripts) in the profile system.
- [ ] Fully realize "The Golden DB" for storing successful prompt/code pairs.
