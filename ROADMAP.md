# Ariadne Roadmap

## ✅ What We've Tested (Current State)

### 1. **State Machine Architecture** (VERIFIED)
| State | Status | Test Coverage |
|-------|--------|---------------|
| `DISPATCH` | ✅ Implemented | Test contract generation |
| `EVALUATE` | ✅ Implemented | Test execution & failure parsing |
| `THINKING` | ✅ Implemented | LLM repair planning with LSP reference search |
| `MAPS_NAV` | ✅ Implemented | Discovery mode with `tracked_nodes` batch processing |
| `MAPS_THINK` | ✅ Implemented | Node diagnosis & draft generation |
| `MAPS_SURGEON` | ✅ Implemented | Surgical formatting & Ghost Check validation |
| `ACTUATE` | ✅ Implemented | Block splicing with batch loop |
| `FILE_EXPLORER` | ✅ Implemented | AST-guided navigation |
| `SPAWN` | ✅ Implemented | Multi-point task dispatch |
| `INTERVENE` | ✅ Implemented | Human-in-the-loop editor |
| `POST_MORTEM` | ✅ Implemented | Self-optimization case generation |
| `ABORT/SUCCESS/FINISH` | ✅ Implemented | Terminal states |

### 2. **Batch Processing Flow** (VERIFIED)
- **Discovery Mode**: `MAPS_NAV` finds multiple nodes before editing
- **Amnesia Pattern**: Navigation stack cleared, tracked nodes preserved
- **Batch Loop**: `MAPS_NAV → MAPS_THINK → MAPS_SURGEON → ACTUATE → MAPS_NAV`
- **Multi-Position Edit**: `test_multi_position_edit` validates batch processing

### 3. **Language Profiles** (VERIFIED)
| Language | Config | Test Runner | AST Grep |
|----------|--------|-------------|----------|
| Rust | ✅ `rust.json` | `run_rust_tests.py` | ✅ |
| Python | ✅ `python.json` | `run_python_tests.py` | ✅ |

### 4. **Components** (VERIFIED)
| Component | Status | Tests |
|-----------|--------|-------|
| `TreeSitterSensor` | ✅ | AST navigation |
| `SyntaxGate` | ✅ | Ghost Check validation |
| `SubprocessSensor` | ✅ | `test_subprocess.py` |
| `CargoCheckHook` | ✅ | `test_cargo_check.py` |

### 5. **Services** (VERIFIED)
| Service | Status | Features |
|---------|--------|----------|
| `LSPService` | ✅ | Diagnostics, hover, `find_references()` |
| `MCP` | ✅ | Rust-analyzer integration |

### 6. **Test Coverage**
```
tests/
├── test_integration_repair.py    ✅ 3 tests (batch processing)
├── test_cargo_check.py           ✅ 1 test (hook structure)
├── test_syntax_gate.py           ✅ 2 tests (validation)
└── test_subprocess.py            ✅ 2 tests (execution)
```

---

## 🗺️ Future Roadmap

### Phase 1: **Core Enhancements** (Priority: High)
| Task | Status | Notes |
|------|--------|-------|
| LSP Reference Search | ✅ Done | `THINKING` finds all references |
| JSON Profile Migration | ✅ Done | DynamicProfile from `*.json` |
| Batch Processing | ✅ Done | `tracked_nodes` list |
| Ghost Check | ✅ Done | LSP diagnostics validation |
| Self-Optimization | ✅ Done | POST_MORTEM case generation |

### Phase 2: **Language Support** (Priority: Medium)
| Language | Config | Test Runner | Status |
|----------|--------|-------------|--------|
| TypeScript/JS | 🔄 Planned | Jest/Vitest | Needs config |
| Go | 🔄 Planned | `go test` | Needs config |
| Java | 🔄 Planned | JUnit | Needs config |
| C# | 🔄 Planned | NUnit/xUnit | Needs config |

### Phase 3: **Advanced Features** (Priority: Medium)
| Feature | Description | Complexity |
|---------|-------------|------------|
| **Multi-File Repair** | Track nodes across multiple files | Medium |
| **Incremental Processing** | Resume from checkpoint on failure | Medium |
| **Parallel Batch Processing** | Process multiple nodes concurrently | High |
| **Test-Driven Discovery** | Auto-generate test contracts from failures | High |
| **Code Smell Detection** | Pre-emptive refactoring suggestions | High |

### Phase 4: **Tooling & UX** (Priority: Low)
| Feature | Description | Status |
|---------|-------------|--------|
| **TUI Dashboard** | Real-time state visualization | `tui.py` exists |
| **CLI Interface** | `ariadne repair <intent>` | Needs implementation |
| **VS Code Extension** | Inline repair suggestions | Planned |
| **Web UI** | Collaborative repair workspace | Future |

### Phase 5: **Quality & Reliability** (Priority: High)
| Task | Description | Status |
|------|-------------|--------|
| **Integration Tests** | End-to-end Rust/Python repairs | Partial |
| **Benchmark Suite** | Performance metrics | `scripts/run_benchmarks.py` |
| **CI Pipeline** | GitHub Actions | `.github/workflows/ariadne_ci.yml` |
| **Error Recovery** | Graceful failure handling | Needs work |

---

## 🎯 Current Architecture Summary

```
DISPATCH → EVALUATE → [THINKING → MAPS_NAV → MAPS_THINK → MAPS_SURGEON → ACTUATE] → POST_MORTEM
                              ↑                                    ↓
                              └────────── Batch Loop ────────────────┘
```

### Key Patterns Implemented:
1. **Amnesia Pattern**: Clear `navigation_stack`, preserve `tracked_nodes`
2. **Batch Processing**: Discovery → Review → Edit → Loop
3. **Ghost Check**: LSP diagnostics before/after edit
4. **LSP Reference Search**: Find all symbol usages
5. **JSON Profiles**: Dynamic language configuration

---

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

---

## 🚀 Next Steps

1. **Add TypeScript/JS profile** (config + tests)
2. **Multi-file repair integration test**
3. **Benchmark suite execution**
4. **CI pipeline verification**
5. **TUI dashboard polish**

---

**Status**: ✅ Core HFSM refactoring complete. Batch processing verified. Language profiles migrated to JSON. Ready for expansion.
