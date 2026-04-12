# Work Plan: HFSM Architecture Refactoring

## TL;DR

> **Goal**: Refactor Ariadne's architecture so LSP and analysis checks run as concurrent services accessible to all states, not as separate HFSM states.
> 
> **Approach**: Keep LSPManager as a background service, remove LSP state transitions, make analysis services directly callable from any state.
> 
> **Deliverables**: 
> - New service layer architecture in `ariadne/services/`
> - Updated states.py with direct service calls
> - Backward-compatible API for existing code
> 
> **Estimated Effort**: Short (2-3 hours)
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Design → Core Services → State Updates

---

## Context

### Original Request
> "we should ensure our engine is agnostic, and languages are configured via json profiles!" (via /simplify command)
> 
> "now let's test it with some file edits, and build a progressively harder sandboxed edit env (and python scripts to replace the ones we allow ariadne to edit, and a folder we keep the clean ones)..."
> 
> **Follow-up**: "ok can we take a minute and pow wow, at least in my mind as the end user, maybe we need to close the loop, so to speak, so the engine goes back to the beginning and checks. IE I see lsp and other checks running concurrently to the hfsm, not as separate states, but accessible data at both the maps level, and the explorer level, removing the need for other states."

### Interview Summary
**Key Discussions**:
- LSP and analysis checks should run concurrently at "map/explorer level"
- Analysis data should be accessible to all states as services, not as separate HFSM states
- Hybrid approach: Core services always running, on-demand services per state

**Research Findings**:
- Current LSP usage: `MAPS_NAV` (line 713), `MAPS_THINK` (line 839), `MAPS_SURGEON` (line 968)
- LSPManager already exists as a singleton in `ariadne/lsp.py`
- LSP provides: diagnostics, hover info, did_change notifications
- 10 HFSM states currently: TRIAGE → DISPATCH → EVALUATE → THINKING → ROUTER → SEARCH → SENSE → MAPS_NAV → MAPS_THINK → MAPS_SURGEON → SYNTAX_GATE → ACTUATE → POST_MORTEM

### Metis Review
**Identified Gaps** (addressed):
- **Gap**: How to handle LSP lifecycle? → **Resolved**: LSPManager stays as singleton with start/stop methods
- **Gap**: How should states access analysis data? → **Resolved**: Direct method calls on service layer
- **Gap**: What about performance? → **Resolved**: Core services run continuously, on-demand services cache results

---

## Work Objectives

### Core Objective
Refactor Ariadne's architecture to make LSP and analysis checks concurrent services accessible to all states, removing the need for separate HFSM states for analysis.

### Concrete Deliverables
- [ ] `ariadne/services/` directory with service layer architecture
- [ ] `ariadne/services/lsp.py` - LSP service wrapper
- [ ] `ariadne/services/analysis.py` - Analysis service wrapper
- [ ] Updated `ariadne/states.py` - Replace LSP state transitions with direct service calls
- [ ] `ariadne/engine.py` - Service initialization and lifecycle management
- [ ] Backward-compatible API for existing code

### Definition of Done
- [ ] LSP runs as background service (not a state)
- [ ] All states can call `lsp.get_diagnostics(filepath)` directly
- [ ] No state transitions for LSP-related logic
- [ ] All existing tests pass
- [ ] Engine starts and runs end-to-end with new architecture

### Must Have
- LSPManager remains singleton with persistent connection
- States can call analysis services directly without state transitions
- Backward compatibility with existing code
- No functionality loss

### Must NOT Have (Guardrails)
- No new LSP-related states added
- No LSP state transitions in HFSM
- No hardcoding of analysis logic in states
- No breaking changes to public API

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.
> Acceptance criteria requiring "user manually tests/confirms" are FORBIDDEN.

### Test Decision
- **Infrastructure exists**: YES (pytest in tests/)
- **Automated tests**: TDD - Each task includes test cases
- **Framework**: pytest
- **If TDD**: Each task follows RED (failing test) → GREEN (minimal impl) → REFACTOR

### QA Policy
Every task MUST include agent-executed QA scenarios (see TODO template below).
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Frontend/UI**: Use Playwright (playwright skill) - Navigate, interact, assert DOM, screenshot
- **TUI/CLI**: Use interactive_bash (tmux) - Run command, send keystrokes, validate output
- **API/Backend**: Use Bash (curl) - Send requests, assert status + response fields
- **Library/Module**: Use Bash (bun/node REPL) - Import, call functions, compare output

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - service layer foundation):
├── Task 1: Create services directory structure [quick]
├── Task 2: Extract LSP service wrapper [quick]
├── Task 3: Create analysis service wrapper [quick]
├── Task 4: Service initialization in engine.py [quick]
└── Task 5: Backward compatibility layer [quick]

Wave 2 (After Wave 1 - state updates):
├── Task 6: Update MAPS_NAV to use service calls [unspecified-high]
├── Task 7: Update MAPS_THINK to use service calls [unspecified-high]
├── Task 8: Update MAPS_SURGEON to use service calls [unspecified-high]
├── Task 9: Update FILE_EXPLORER to use service calls [unspecified-high]
└── Task 10: Remove LSP-related state transitions [unspecified-high]

Wave 3 (After Wave 2 - validation):
├── Task 11: Run existing tests [quick]
├── Task 12: End-to-end test with sandbox files [unspecified-high]
├── Task 13: Performance benchmark comparison [unspecified-high]
└── Task 14: Documentation update [writing]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 2 → Task 6 → Task 11 → F1-F4 → user okay
Parallel Speedup: ~70% faster than sequential
Max Concurrent: 4 (Waves 1 & 2)
```

### Dependency Matrix

- **1-5**: - - 6-10, 1
- **6**: 2 - 11, 2
- **7**: 2 - 11, 2
- **8**: 2 - 11, 2
- **9**: 2 - 11, 2
- **10**: 2, 6, 7, 8, 9 - 11, 3
- **11**: 1-5, 6-10 - 12, 3
- **12**: 11 - 14, 3
- **13**: 11 - 14, 3
- **14**: 11 - F1-F4, 3

### Agent Dispatch Summary

- **1**: **5** - T1-T5 → `quick`
- **2**: **5** - T6-T10 → `unspecified-high`
- **3**: **4** - T11-T14 → `quick/unspecified-high/writing`
- **FINAL**: **4** - F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.
> **A task WITHOUT QA Scenarios is INCOMPLETE. No exceptions.**

- [ ] 1. Create services directory structure

  **What to do**:
  - Create `ariadne/services/` directory
  - Create `ariadne/services/__init__.py` with exports
  - Create `ariadne/services/base.py` with Service base class
  - Create `ariadne/services/lsp.py` with LSPService wrapper
  - Create `ariadne/services/analysis.py` with AnalysisService wrapper

  **Must NOT do**:
  - Do not modify existing LSPManager class
  - Do not add state transitions
  - Do not hardcode analysis logic

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `quick`
    - Reason: Straightforward file creation and basic class structure
  - **Skills**: []
    - No special skills needed for directory/file creation
  - **Skills Evaluated but Omitted**:
    - `lsp`: Domain doesn't overlap - this is just structure

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4, 5)
  - **Blocks**: Tasks 6-10 (state updates depend on service layer)
  - **Blocked By**: None (can start immediately)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/lsp.py` - LSPManager class for reference
  - `ariadne/profiles/base.py` - Base class pattern for services

  **Test References** (testing patterns to follow):
  - `tests/test_lsp_manager.py` - LSPManager tests (if exists)
  - `tests/test_profiles.py` - Profile tests for service pattern

  **Acceptance Criteria**:
  - [ ] `ariadne/services/` directory created
  - [ ] `ariadne/services/__init__.py` exports LSPService and AnalysisService
  - [ ] `ariadne/services/base.py` defines Service base class
  - [ ] `ariadne/services/lsp.py` wraps LSPManager
  - [ ] `ariadne/services/analysis.py` defines analysis service interface

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: Services directory structure created
    Tool: Bash (ls)
    Preconditions: New project state
    Steps:
      1. Run: ls ariadne/services/
      2. Assert: __init__.py, base.py, lsp.py, analysis.py exist
    Expected Result: All 4 files present
    Failure Indicators: Any file missing
    Evidence: .sisyphus/evidence/task-1-structure.{txt}

  Scenario: Services can be imported
    Tool: Bash (python -c)
    Preconditions: Services directory created
    Steps:
      1. Run: python -c "from ariadne.services import LSPService, AnalysisService"
      2. Assert: Import succeeds without errors
    Expected Result: Import successful
    Failure Indicators: ImportError or ModuleNotFoundError
    Evidence: .sisyphus/evidence/task-1-import.{txt}
  ```

  **Evidence to Capture**:
  - [ ] Directory listing showing all files
  - [ ] Python import test output

  **Commit**: YES (with Task 2)
  - Message: `feat: add services layer architecture`
  - Files: `ariadne/services/__init__.py`, `ariadne/services/base.py`, `ariadne/services/lsp.py`, `ariadne/services/analysis.py`
  - Pre-commit: `python -c "from ariadne.services import LSPService, AnalysisService"`

- [ ] 2. Extract LSP service wrapper

  **What to do**:
  - Read `ariadne/lsp.py` LSPManager class
  - Create `ariadne/services/lsp.py` with LSPService class
  - Wrap LSPManager methods: get_diagnostics, get_hover, did_change
  - Add lifecycle management: start(), stop(), is_running()
  - Add caching layer for diagnostics (optional optimization)

  **Must NOT do**:
  - Do not modify LSPManager class
  - Do not add state transitions
  - Do not change LSP behavior

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to understand LSPManager internals and create clean wrapper
  - **Skills**: []
    - Python knowledge sufficient for this task
  - **Skills Evaluated but Omitted**:
    - `lsp`: Not needed - just wrapping existing code

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4, 5)
  - **Blocks**: Tasks 6-10 (state updates depend on service wrapper)
  - **Blocked By**: Task 1 (services directory must exist)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/lsp.py:1-116` - LSPManager class to wrap
  - `ariadne/services/base.py` - Service base class pattern

  **API/Type References** (contracts to implement against):
  - `LSPManager.get_diagnostics(filepath)` - Returns List[Dict]
  - `LSPManager.get_hover(filepath, line, char)` - Returns str
  - `LSPManager.did_change(filepath, content)` - Returns None

  **Acceptance Criteria**:
  - [ ] LSPService class defined in `ariadne/services/lsp.py`
  - [ ] LSPService.start() calls LSPManager.start()
  - [ ] LSPService.get_diagnostics(filepath) calls LSPManager.get_diagnostics()
  - [ ] LSPService.get_hover(filepath, line, char) calls LSPManager.get_hover()
  - [ ] LSPService.did_change(filepath, content) calls LSPManager.did_change()
  - [ ] LSPService.stop() calls LSPManager.stop()

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: LSPService wraps LSPManager correctly
    Tool: Bash (python -c)
    Preconditions: LSPService created, LSPManager exists
    Steps:
      1. Run: python -c "from ariadne.services.lsp import LSPService; s = LSPService(); print(type(s))"
      2. Assert: LSPService instance created
    Expected Result: LSPService instance
    Failure Indicators: TypeError or ImportError
    Evidence: .sisyphus/evidence/task-2-service-instance.{txt}

  Scenario: LSPService methods delegate to LSPManager
    Tool: Bash (python -c)
    Preconditions: LSPService created
    Steps:
      1. Run: python -c "from ariadne.services.lsp import LSPService; s = LSPService(); print(hasattr(s, 'get_diagnostics'))"
      2. Assert: get_diagnostics method exists
      3. Run: python -c "from ariadne.services.lsp import LSPService; s = LSPService(); print(hasattr(s, 'start'))"
      4. Assert: start method exists
    Expected Result: All methods exist
    Failure Indicators: AttributeError
    Evidence: .sisyphus/evidence/task-2-methods.{txt}
  ```

  **Evidence to Capture**:
  - [ ] Method existence test output
  - [ ] Service instantiation test output

  **Commit**: YES (with Task 1)
  - Message: `feat: add services layer architecture`
  - Files: `ariadne/services/__init__.py`, `ariadne/services/base.py`, `ariadne/services/lsp.py`, `ariadne/services/analysis.py`
  - Pre-commit: `python -c "from ariadne.services import LSPService, AnalysisService"`

- [ ] 3. Create analysis service wrapper

  **What to do**:
  - Create `ariadne/services/analysis.py` with AnalysisService class
  - Define analysis methods: syntax_check, type_check, code_quality
  - Each method accepts filepath and returns analysis results
  - Add caching layer for expensive operations
  - Define AnalysisResult dataclass for consistent output

  **Must NOT do**:
  - Do not implement full analysis logic
  - Do not add state transitions
  - Do not hardcode specific analysis tools

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to design service interface and data structures
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4, 5)
  - **Blocks**: Tasks 6-10 (state updates depend on analysis service)
  - **Blocked By**: Task 1 (services directory must exist)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/services/lsp.py` - LSPService pattern for reference
  - `ariadne/services/base.py` - Service base class pattern

  **Acceptance Criteria**:
  - [ ] AnalysisService class defined in `ariadne/services/analysis.py`
  - [ ] AnalysisService.syntax_check(filepath) returns AnalysisResult
  - [ ] AnalysisService.type_check(filepath) returns AnalysisResult
  - [ ] AnalysisService.code_quality(filepath) returns AnalysisResult
  - [ ] AnalysisResult dataclass defined with consistent fields

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: AnalysisService methods defined
    Tool: Bash (python -c)
    Preconditions: AnalysisService created
    Steps:
      1. Run: python -c "from ariadne.services.analysis import AnalysisService; s = AnalysisService(); print(hasattr(s, 'syntax_check'))"
      2. Assert: syntax_check method exists
      3. Run: python -c "from ariadne.services.analysis import AnalysisService; s = AnalysisService(); print(hasattr(s, 'type_check'))"
      4. Assert: type_check method exists
    Expected Result: All methods exist
    Failure Indicators: AttributeError
    Evidence: .sisyphus/evidence/task-3-methods.{txt}

  Scenario: AnalysisResult dataclass defined
    Tool: Bash (python -c)
    Preconditions: AnalysisService created
    Steps:
      1. Run: python -c "from ariadne.services.analysis import AnalysisResult; r = AnalysisResult(success=True, message='test')"
      2. Assert: AnalysisResult instance created
    Expected Result: AnalysisResult instance
    Failure Indicators: TypeError or ImportError
    Evidence: .sisyphus/evidence/task-3-dataclass.{txt}
  ```

  **Evidence to Capture**:
  - [ ] Method existence test output
  - [ ] Dataclass instantiation test output

  **Commit**: YES (with Task 1)
  - Message: `feat: add services layer architecture`
  - Files: `ariadne/services/__init__.py`, `ariadne/services/base.py`, `ariadne/services/lsp.py`, `ariadne/services/analysis.py`
  - Pre-commit: `python -c "from ariadne.services import LSPService, AnalysisService"`

- [ ] 4. Service initialization in engine.py

  **What to do**:
  - Read current `ariadne/engine.py` (or create if doesn't exist)
  - Add service initialization in EngineContext.__init__()
  - Add service lifecycle management (start/stop)
  - Ensure services are accessible from states

  **Must NOT do**:
  - Do not modify existing state logic
  - Do not add state transitions
  - Do not change engine behavior

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to understand engine architecture and integrate services
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 5)
  - **Blocks**: Tasks 6-10 (state updates depend on service initialization)
  - **Blocked By**: Tasks 1, 2, 3 (service classes must exist)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/core.py` - EngineContext class for reference
  - `ariadne/engine.py` - Existing engine initialization pattern

  **Acceptance Criteria**:
  - [ ] EngineContext has services attribute
  - [ ] Services initialized in EngineContext.__init__()
  - [ ] Services.start() called when engine starts
  - [ ] Services.stop() called when engine stops
  - [ ] States can access services via context.services

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: EngineContext has services
    Tool: Bash (python -c)
    Preconditions: Engine context created
    Steps:
      1. Run: python -c "from ariadne.core import EngineContext; c = EngineContext(); print(hasattr(c, 'services'))"
      2. Assert: services attribute exists
    Expected Result: True
    Failure Indicators: AttributeError
    Evidence: .sisyphus/evidence/task-4-context-services.{txt}

  Scenario: Services accessible from states
    Tool: Bash (python -c)
    Preconditions: Engine context with services
    Steps:
      1. Run: python -c "from ariadne.core import EngineContext; from ariadne.states import TRIAGE; c = EngineContext(); s = TRIAGE(None); print(c.services)"
      2. Assert: Services object accessible
    Expected Result: Services object printed
    Failure Indicators: AttributeError or None
    Evidence: .sisyphus/evidence/task-4-state-access.{txt}
  ```

  **Evidence to Capture**:
  - [ ] Context services test output
  - [ ] State access test output

  **Commit**: YES (with Task 1)
  - Message: `feat: add services layer architecture`
  - Files: `ariadne/services/__init__.py`, `ariadne/services/base.py`, `ariadne/services/lsp.py`, `ariadne/services/analysis.py`
  - Pre-commit: `python -c "from ariadne.services import LSPService, AnalysisService"`

- [ ] 5. Backward compatibility layer

  **What to do**:
  - Create `ariadne/services/backward_compat.py` 
  - Add backward_compat.get_lsp_manager() that returns LSPService
  - Ensure existing code using `get_lsp_manager()` still works
  - Add deprecation warnings for old usage patterns

  **Must NOT do**:
  - Do not remove old LSPManager usage yet
  - Do not break existing code
  - Do not add breaking changes

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `quick`
    - Reason: Straightforward wrapper function
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 4)
  - **Blocks**: Tasks 6-10 (state updates can use either old or new API)
  - **Blocked By**: Tasks 1, 2, 3, 4 (service classes must exist)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/services/lsp.py` - LSPService pattern for reference
  - `ariadne/states.py:662-673` - Current get_lsp_manager() function

  **Acceptance Criteria**:
  - [ ] backward_compat.get_lsp_manager() returns LSPService
  - [ ] Existing code using get_lsp_manager() still works
  - [ ] Deprecation warnings logged for old usage

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: Backward compatibility works
    Tool: Bash (python -c)
    Preconditions: Backward compat module created
    Steps:
      1. Run: python -c "from ariadne.services.backward_compat import get_lsp_manager; m = get_lsp_manager(); print(type(m))"
      2. Assert: Returns LSPService instance
    Expected Result: LSPService instance
    Failure Indicators: TypeError or ImportError
    Evidence: .sisyphus/evidence/task-5-backward-compat.{txt}
  ```

  **Evidence to Capture**:
  - [ ] Backward compatibility test output

  **Commit**: YES (with Task 1)
  - Message: `feat: add services layer architecture`
  - Files: `ariadne/services/__init__.py`, `ariadne/services/base.py`, `ariadne/services/lsp.py`, `ariadne/services/analysis.py`
  - Pre-commit: `python -c "from ariadne.services import LSPService, AnalysisService"`

- [ ] 6. Update MAPS_NAV to use service calls

  **What to do**:
  - Read current MAPSNAV.tick() method (lines 686-813 in states.py)
  - Replace LSPManager calls with service calls
  - Remove get_lsp_manager() call, use context.services.lsp
  - Update diagnostics injection (lines 713-715)
  - Add service call caching if needed

  **Must NOT do**:
  - Do not change MAPSNAV state logic
  - Do not add state transitions
  - Do not change LSP behavior

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to understand MAPSNAV logic and update LSP calls
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 8, 9, 10)
  - **Blocks**: Task 11 (tests depend on updated states)
  - **Blocked By**: Tasks 1-5 (services must exist and be initialized)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/states.py:686-813` - Current MAPSNAV implementation
  - `ariadne/services/lsp.py` - LSPService pattern for reference

  **API/Type References** (contracts to implement against):
  - `LSPService.get_diagnostics(filepath)` - Returns List[Dict]
  - `LSPService.get_hover(filepath, line, char)` - Returns str
  - `LSPService.did_change(filepath, content)` - Returns None

  **Acceptance Criteria**:
  - [ ] MAPSNAV uses context.services.lsp instead of get_lsp_manager()
  - [ ] All LSP calls in MAPSNAV use service methods
  - [ ] No get_lsp_manager() calls in MAPSNAV
  - [ ] All existing tests pass

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: MAPSNAV uses service calls
    Tool: Bash (grep)
    Preconditions: MAPSNAV updated
    Steps:
      1. Run: grep -n "get_lsp_manager" ariadne/states.py | head -20
      2. Assert: No get_lsp_manager calls in MAPSNAV section
    Expected Result: No matches for MAPSNAV
    Failure Indicators: get_lsp_manager found in MAPSNAV
    Evidence: .sisyphus/evidence/task-6-no-old-api.{txt}

  Scenario: MAPSNAV diagnostics work
    Tool: Bash (pytest)
    Preconditions: Updated states.py
    Steps:
      1. Run: python -m pytest tests/test_maps_nav.py -v
      2. Assert: All tests pass
    Expected Result: All tests pass
    Failure Indicators: Test failures
    Evidence: .sisyphus/evidence/task-6-tests.{txt}
  ```

  **Evidence to Capture**:
  - [ ] No old API usage test output
  - [ ] Test results output

  **Commit**: YES (with Task 7-10)
  - Message: `refactor: use services in MAPSNAV`
  - Files: `ariadne/states.py`
  - Pre-commit: `python -m pytest tests/ -v`

- [ ] 7. Update MAPS_THINK to use service calls

  **What to do**:
  - Read current MAPS_THINK.tick() method (lines 826-901 in states.py)
  - Replace LSPManager calls with service calls
  - Remove get_lsp_manager() call, use context.services.lsp
  - Update diagnostics and hover info (lines 839-843)
  - Add service call caching if needed

  **Must NOT do**:
  - Do not change MAPS_THINK state logic
  - Do not add state transitions
  - Do not change LSP behavior

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to understand MAPS_THINK logic and update LSP calls
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 8, 9, 10)
  - **Blocks**: Task 11 (tests depend on updated states)
  - **Blocked By**: Tasks 1-5 (services must exist and be initialized)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/states.py:826-901` - Current MAPS_THINK implementation
  - `ariadne/services/lsp.py` - LSPService pattern for reference

  **Acceptance Criteria**:
  - [ ] MAPS_THINK uses context.services.lsp instead of get_lsp_manager()
  - [ ] All LSP calls in MAPS_THINK use service methods
  - [ ] No get_lsp_manager() calls in MAPS_THINK
  - [ ] All existing tests pass

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: MAPS_THINK uses service calls
    Tool: Bash (grep)
    Preconditions: MAPS_THINK updated
    Steps:
      1. Run: grep -n "get_lsp_manager" ariadne/states.py | head -20
      2. Assert: No get_lsp_manager calls in MAPS_THINK section
    Expected Result: No matches for MAPS_THINK
    Failure Indicators: get_lsp_manager found in MAPS_THINK
    Evidence: .sisyphus/evidence/task-7-no-old-api.{txt}
  ```

  **Evidence to Capture**:
  - [ ] No old API usage test output

  **Commit**: YES (with Task 6-10)
  - Message: `refactor: use services in MAPS_THINK`
  - Files: `ariadne/states.py`
  - Pre-commit: `python -m pytest tests/ -v`

- [ ] 8. Update MAPS_SURGEON to use service calls

  **What to do**:
  - Read current MAPS_SURGEON.tick() method (lines 904-999 in states.py)
  - Replace LSPManager calls with service calls
  - Remove get_lsp_manager() call, use context.services.lsp
  - Update diagnostics for Ghost Check (lines 968-995)
  - Add service call caching if needed

  **Must NOT do**:
  - Do not change MAPS_SURGEON state logic
  - Do not add state transitions
  - Do not change LSP behavior

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to understand MAPS_SURGEON logic and update LSP calls
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7, 9, 10)
  - **Blocks**: Task 11 (tests depend on updated states)
  - **Blocked By**: Tasks 1-5 (services must exist and be initialized)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/states.py:904-999` - Current MAPS_SURGEON implementation
  - `ariadne/services/lsp.py` - LSPService pattern for reference

  **Acceptance Criteria**:
  - [ ] MAPS_SURGEON uses context.services.lsp instead of get_lsp_manager()
  - [ ] All LSP calls in MAPS_SURGEON use service methods
  - [ ] No get_lsp_manager() calls in MAPS_SURGEON
  - [ ] All existing tests pass

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: MAPS_SURGEON uses service calls
    Tool: Bash (grep)
    Preconditions: MAPS_SURGEON updated
    Steps:
      1. Run: grep -n "get_lsp_manager" ariadne/states.py | head -20
      2. Assert: No get_lsp_manager calls in MAPS_SURGEON section
    Expected Result: No matches for MAPS_SURGEON
    Failure Indicators: get_lsp_manager found in MAPS_SURGEON
    Evidence: .sisyphus/evidence/task-8-no-old-api.{txt}
  ```

  **Evidence to Capture**:
  - [ ] No old API usage test output

  **Commit**: YES (with Task 6-10)
  - Message: `refactor: use services in MAPS_SURGEON`
  - Files: `ariadne/states.py`
  - Pre-commit: `python -m pytest tests/ -v`

- [ ] 9. Update FILE_EXPLORER to use service calls

  **What to do**:
  - Read current FILE_EXPLORER.tick() method (lines 1147-1284 in states.py)
  - Replace LSPManager calls with service calls if any
  - Remove get_lsp_manager() call, use context.services.lsp
  - Add service call caching if needed

  **Must NOT do**:
  - Do not change FILE_EXPLORER state logic
  - Do not add state transitions
  - Do not change LSP behavior

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to understand FILE_EXPLORER logic and update LSP calls
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7, 8, 10)
  - **Blocks**: Task 11 (tests depend on updated states)
  - **Blocked By**: Tasks 1-5 (services must exist and be initialized)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/states.py:1147-1284` - Current FILE_EXPLORER implementation
  - `ariadne/services/lsp.py` - LSPService pattern for reference

  **Acceptance Criteria**:
  - [ ] FILE_EXPLORER uses context.services.lsp instead of get_lsp_manager()
  - [ ] All LSP calls in FILE_EXPLORER use service methods
  - [ ] No get_lsp_manager() calls in FILE_EXPLORER
  - [ ] All existing tests pass

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: FILE_EXPLORER uses service calls
    Tool: Bash (grep)
    Preconditions: FILE_EXPLORER updated
    Steps:
      1. Run: grep -n "get_lsp_manager" ariadne/states.py | head -20
      2. Assert: No get_lsp_manager calls in FILE_EXPLORER section
    Expected Result: No matches for FILE_EXPLORER
    Failure Indicators: get_lsp_manager found in FILE_EXPLORER
    Evidence: .sisyphus/evidence/task-9-no-old-api.{txt}
  ```

  **Evidence to Capture**:
  - [ ] No old API usage test output

  **Commit**: YES (with Task 6-10)
  - Message: `refactor: use services in FILE_EXPLORER`
  - Files: `ariadne/states.py`
  - Pre-commit: `python -m pytest tests/ -v`

- [ ] 10. Remove LSP-related state transitions

  **What to do**:
  - Review all state transitions in states.py
  - Identify any LSP-related state transitions
  - Remove or replace with service calls
  - Ensure no LSP state transitions remain

  **Must NOT do**:
  - Do not change HFSM state machine structure
  - Do not remove valid state transitions
  - Do not break engine functionality

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to understand HFSM structure and identify LSP transitions
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7, 8, 9)
  - **Blocks**: Task 11 (tests depend on updated states)
  - **Blocked By**: Tasks 1-5 (services must exist and be initialized)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `ariadne/states.py` - Full state machine for review
  - `ariadne/services/lsp.py` - LSPService pattern for reference

  **Acceptance Criteria**:
  - [ ] No LSP-related state transitions remain
  - [ ] All LSP functionality accessible via services
  - [ ] All existing tests pass

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: No LSP state transitions
    Tool: Bash (grep)
    Preconditions: All states updated
    Steps:
      1. Run: grep -n "LSP" ariadne/states.py | head -20
      2. Assert: No LSP state transitions
    Expected Result: Only service calls, no state transitions
    Failure Indicators: LSP state transitions found
    Evidence: .sisyphus/evidence/task-10-no-lsp-states.{txt}
  ```

  **Evidence to Capture**:
  - [ ] No LSP states test output

  **Commit**: YES (with Task 6-10)
  - Message: `refactor: remove LSP state transitions`
  - Files: `ariadne/states.py`
  - Pre-commit: `python -m pytest tests/ -v`

- [ ] 11. Run existing tests

  **What to do**:
  - Run pytest on all existing tests
  - Fix any failures caused by refactoring
  - Ensure all tests pass with new architecture

  **Must NOT do**:
  - Do not skip tests
  - Do not modify tests to pass
  - Do not add new test failures

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `quick`
    - Reason: Straightforward test execution
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12, 13, 14)
  - **Blocks**: Task F1 (final verification depends on tests)
  - **Blocked By**: Tasks 1-10 (all refactoring must complete)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `tests/` - All existing tests for reference
  - `ariadne/states.py` - Updated states for test compatibility

  **Acceptance Criteria**:
  - [ ] All existing tests pass
  - [ ] No new test failures introduced
  - [ ] Test coverage maintained or improved

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: All tests pass
    Tool: Bash (pytest)
    Preconditions: All refactoring complete
    Steps:
      1. Run: python -m pytest tests/ -v
      2. Assert: All tests pass
    Expected Result: 100% pass rate
    Failure Indicators: Any test failure
    Evidence: .sisyphus/evidence/task-11-tests.{txt}
  ```

  **Evidence to Capture**:
  - [ ] Test results output

  **Commit**: YES (with Task 12-14)
  - Message: `test: all tests pass after refactoring`
  - Files: `ariadne/states.py`, `ariadne/services/`
  - Pre-commit: `python -m pytest tests/ -v`

- [ ] 12. End-to-end test with sandbox files

  **What to do**:
  - Use sandbox files from `sandbox/templates/`
  - Run Ariadne engine on sandbox files
  - Verify LSP service calls work end-to-end
  - Document any issues found

  **Must NOT do**:
  - Do not skip end-to-end testing
  - Do not modify sandbox files
  - Do not add new bugs

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to run full engine and verify integration
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 11, 13, 14)
  - **Blocks**: Task F3 (final QA depends on e2e tests)
  - **Blocked By**: Tasks 1-11 (all refactoring and unit tests must pass)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `sandbox/templates/simple_function.py` - Simple test file
  - `sandbox/templates/medium_function.py` - Medium test file
  - `ariadne/engine.py` - Engine entry point

  **Acceptance Criteria**:
  - [ ] Engine runs on sandbox files
  - [ ] LSP service calls work end-to-end
  - [ ] No errors in sandbox testing

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: Engine runs on sandbox
    Tool: Bash (python)
    Preconditions: Sandbox files exist
    Steps:
      1. Run: python engine.py --targets sandbox/templates/simple_function.py --intent "Add error handling"
      2. Assert: Engine runs without errors
    Expected Result: Engine completes successfully
    Failure Indicators: Engine crashes or hangs
    Evidence: .sisyphus/evidence/task-12-e2e.{txt}
  ```

  **Evidence to Capture**:
  - [ ] Engine output log

  **Commit**: YES (with Task 11-14)
  - Message: `e2e: sandbox tests pass after refactoring`
  - Files: `ariadne/states.py`, `ariadne/services/`
  - Pre-commit: `python engine.py --targets sandbox/templates/simple_function.py --intent "Add error handling"`

- [ ] 13. Performance benchmark comparison

  **What to do**:
  - Run benchmarks before and after refactoring
  - Compare token usage and execution time
  - Document performance changes

  **Must NOT do**:
  - Do not skip benchmarking
  - Do not modify benchmark code
  - Do not introduce performance regressions

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `unspecified-high`
    - Reason: Need to run benchmarks and analyze results
  - **Skills**: []
    - Python knowledge sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 11, 12, 14)
  - **Blocks**: Task F2 (final review depends on benchmarks)
  - **Blocked By**: Tasks 1-12 (all refactoring and e2e tests must pass)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `scripts/run_benchmarks.py` - Benchmark runner
  - `ariadne/states.py` - Updated states for benchmarking

  **Acceptance Criteria**:
  - [ ] Benchmarks run before and after
  - [ ] Performance comparison documented
  - [ ] No significant performance regression

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: Benchmarks run
    Tool: Bash (python)
    Preconditions: Benchmark runner exists
    Steps:
      1. Run: python scripts/run_benchmarks.py --before
      2. Run: python scripts/run_benchmarks.py --after
      3. Compare results
    Expected Result: Both runs complete
    Failure Indicators: Benchmark crashes
    Evidence: .sisyphus/evidence/task-13-benchmarks.{txt}
  ```

  **Evidence to Capture**:
  - [ ] Benchmark results before and after

  **Commit**: YES (with Task 11-14)
  - Message: `bench: performance comparison after refactoring`
  - Files: `ariadne/states.py`, `ariadne/services/`
  - Pre-commit: `python scripts/run_benchmarks.py --before && python scripts/run_benchmarks.py --after`

- [ ] 14. Documentation update

  **What to do**:
  - Update README.md with new architecture
  - Add services layer documentation
  - Document how to use services from states
  - Add migration guide for developers

  **Must NOT do**:
  - Do not skip documentation
  - Do not write vague documentation
  - Do not forget to update API docs

  **Recommended Agent Profile**:
  > Select category + skills based on task domain. Justify each choice.
  - **Category**: `writing`
    - Reason: Documentation task
  - **Skills**: []
    - Writing skill sufficient for this task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 11, 12, 13)
  - **Blocks**: Task F4 (final verification depends on docs)
  - **Blocked By**: Tasks 1-13 (all refactoring must complete)

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `README.md` - Current documentation for reference
  - `ariadne/services/` - New services layer for documentation

  **Acceptance Criteria**:
  - [ ] README.md updated with new architecture
  - [ ] Services layer documented
  - [ ] Migration guide for developers added

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: Documentation complete
    Tool: Bash (ls)
    Preconditions: Documentation updated
    Steps:
      1. Run: ls docs/
      2. Assert: New docs exist
    Expected Result: Documentation files present
    Failure Indicators: Documentation missing
    Evidence: .sisyphus/evidence/task-14-docs.{txt}
  ```

  **Evidence to Capture**:
  - [ ] Documentation file listing

  **Commit**: YES (with Task 11-14)
  - Message: `docs: update documentation for services layer`
  - Files: `README.md`, `docs/services.md`
  - Pre-commit: `cat README.md | grep -i "services"`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `tsc --noEmit` + linter + `bun test`. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill if UI)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, invalid input, rapid actions. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **1-5**: `feat: add services layer architecture` - ariadne/services/\*, ariadne/states.py, python -m pytest tests/ -v
- **6-10**: `refactor: use services in [state]` - ariadne/states.py, python -m pytest tests/ -v
- **11-14**: `test: all tests pass after refactoring` - ariadne/states.py, ariadne/services/\*, python -m pytest tests/ -v

---

## Success Criteria

### Verification Commands
```bash
# Run tests
python -m pytest tests/ -v

# Run sandbox e2e test
python engine.py --targets sandbox/templates/simple_function.py --intent "Add error handling"

# Run benchmarks
python scripts/run_benchmarks.py --before && python scripts/run_benchmarks.py --after
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] LSP runs as background service
- [ ] No LSP state transitions in HFSM
- [ ] Services accessible from all states
- [ ] Documentation updated
- [ ] Benchmarks run successfully