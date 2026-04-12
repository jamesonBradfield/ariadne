# PROJECT KNOWLEDGE BASE

**Generated:** 2026-04-11
**Commit:** 7a3b8c1
**Branch:** main

## OVERVIEW
Ariadne is a surgical code repair engine using Hierarchical Finite State Machine (HFSM) architecture. Core stack: Python 3.12, tree-sitter parsers, local LLM (Qwen3.5-9B).

## STRUCTURE
```
./
├── ariadne/       # Core engine & language profiles
├── tests/         # Unit/integration tests with test contracts
├── scripts/       # Helper scripts (test runners)
├── benchmarks/    # Performance benchmarks
├── GEMINI.md      # Development mandates
└── ariadne_config.json  # LLM/editor/state machine config
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| State machine | `ariadne/states.py` | HFSM orchestration |
| Language profiles | `ariadne/profiles/` | Rust/Python logic |
| Test contracts | `test_contract.*` | Expected behavior specs |
| CI Pipeline | `.github/workflows/ariadne_ci.yml` | pytest + benchmarks |

## CONVENTIONS
- **Config**: `ariadne_config.json` (NO pyproject.toml/.editorconfig)
- **Line Endings**: Strict Unix (`\n`), NO `\r`
- **Command Chaining**: Use `;` NOT `&&` (MSYS2/Zsh)
- **Prompt Management**: NEVER hardcode in `states.py` - use config

## ANTI-PATTERNS (THIS PROJECT)
- Hardcoding LLM prompts in state logic
- Mixing primitives/states responsibilities
- Using carriage returns (`\r`) in files

## UNIQUE STYLES
- **Test Contracts**: `test_contract.py`/`.rs` define repair targets
- **State Machine**: 7-state HFSM (DISPATCH → THINKING → MAPS_NAV → MAPS_THINK → MAPS_SURGEON → ACTUATE → POST_MORTEM)
- **Component Tests**: Isolated unit tests for each sensor/hook
- **Batch Processing**: Discovery mode finds multiple nodes before editing
- **Amnesia Pattern**: Navigation state cleared but tracked nodes preserved

## COMMANDS
```bash
# Run tests
python -m pytest tests/

# Run benchmarks (main branch only)
python scripts/run_benchmarks.py

# Launch editor
nvim +{line} {file}
```

## NOTES
- Benchmarks require `ARIADNE_MODEL`/`API_KEY` secrets
- CI uses Python 3.12 with NO caching (slow runs)
- No linting in CI (add ruff/mypy if needed)