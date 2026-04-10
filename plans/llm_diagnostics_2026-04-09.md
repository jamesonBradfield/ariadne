# LLM Diagnostic Observations (2026-04-09)

## Context
Testing Ariadne with a local **Qwen3.5-9B-Q6_K.gguf** model via `llama-cpp-python` (OpenAI-compatible server).

## Critical Findings

### 1. The "Combined Mode" Failure
- **Issue**: Previously, Ariadne merged `SYSTEM` and `USER` prompts into a single `USER` message for local servers to improve compatibility with simpler models.
- **Result**: Qwen3.5 returned **empty strings** when prompts were combined.
- **Fix**: Reverted to separate `SYSTEM` and `USER` messages in `ariadne/primitives.py`. Connectivity is now stable.

### 2. Token Debt & Reasoning Chatter
- **Issue**: Qwen3.5 is highly analytical but extremely "chatty" in its internal thinking process.
- **Symptom**: In the `THINKING` and `TRIAGE` states, the model hits the `max_tokens` limit (currently 512 for triage, 2048 for thinking) while still explaining the problem to itself.
- **Result**: The model is cut off by the server before it can output the final JSON payload required by the state machine, leading to `json_invalid` errors.
- **Observation**: The reasoning content shows the model *correctly* diagnosed the `Base::new` hallucination, but failed to act on it before running out of "runway".

### 3. Godot-Rust API Hallucinations
- **Issue**: The model frequently tries to use `Base::new::<T>()` or `RealtimeProbe::init(base)` in unit tests.
- **Reality**: In modern `godot-rust`, `Base<T>` is often handled differently (e.g., `Gd::from_init`), and `init` is an internal trait method.
- **Impact**: Generates "noisy" test failures (30+ errors) that require a strong `THINKING` state to prune.

## Recommended Architectural Adjustments
1. **Aggressive JSON Extraction**: Update `QueryLLM` to search for JSON blocks specifically, potentially ignoring everything else (including trailing chatter).
2. **Token Limit Increase**: Boost `THINKING` to at least 4096 tokens for local runs.
3. **Reasoning Stripping**: If the model uses `<think>` tags, Ariadne should strip them before trying to parse the payload to save context and prevent parsing logic from getting confused.
