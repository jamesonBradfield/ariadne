# Plan: Project Context & Godot-Rust Finalization (4/2/2026)

## Objective
Eliminate all directory-related friction by introducing a formal `--project-dir` (CD) flag and finalizing the specialized logic required for Godot-Rust (GDExtension) symbols.

## Phase 1: The `--project-dir` (CD) Integration
* **Engine Update**: Add a `--project-dir` argument to `engine.py`. When provided, the engine will `os.chdir()` into that directory immediately after loading configuration and profiles.
* **Path Normalization**: Ensure all `--targets` passed to the engine are resolved relative to this project directory so the LLM receives clean, local paths (e.g., `src/realtime_probe.rs` instead of `TexelSplatting/.rust/src/...`).
* **LSP Alignment**: Automatically pass the project directory to `LSPManager` as the workspace root, ensuring `rust-analyzer` picks up the correct `Cargo.toml` and dependencies. This replaces the heuristic `find_project_root` function with explicit user intent.

## Phase 2: Godot-Rust (GDExtension) Specialization
* **Architectural Nuance**: Update the `THINKING` prompt in `ariadne_config.json` to understand the relationship between `struct` and `impl` blocks in Rust. The Architect must learn to target the **container** (the `impl` block or the `Struct` symbol) when adding new methods, not the hypothetical new method name itself, so `SENSE` can find it.
* **Test Contract Robustness**: Update the `DISPATCH` prompt for Rust to explicitly instruct the LLM to include necessary crate imports (like `use godot::prelude::*;`) if the target code uses them. Alternatively, add a feature to `BaseProfile` to inject standard headers into generated tests.

## Phase 3: Language Agnosticism Check
* **Validation**: Ensure the new `--project-dir` logic doesn't break the Python profile tests in `benchmarks/`. It should cleanly handle both Rust and Python targets.
* **Profile Expansion**: Prepare `base.py` to allow profiles to define "Standard Header Includes" for test generation, solving the missing import issue consistently across different languages.

## Phase 4: The "TexelSplatting" Victory Run
* **Final Test**: Autonomously implement `get_total_cameras` in `TexelSplatting/.rust/src/realtime_probe.rs`, verify it passes `cargo test`, and ensure `MAPS_SURGEON` correctly splices the code into the `impl` block without user intervention or loops.