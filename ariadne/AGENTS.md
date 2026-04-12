# ariadne/ KNOWLEDGE BASE

## OVERVIEW
Core engine implementation and language-specific profiles.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| State machine | `states.py` | HFSM orchestration |
| Language profiles | `profiles/` | Rust/Python logic |
| Component tests | `testing/` | Isolated unit tests |

## CONVENTIONS
- **Language Logic**: MUST reside in `profiles/`
- **Primitives vs States**: Primitives = atomic, States = orchestrate
- **Prompt Management**: All prompts via `ariadne_config.json`

## ANTI-PATTERNS
- Hardcoding prompts in state logic
- Mixing language-specific logic in core engine