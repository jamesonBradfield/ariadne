## 2026-04-12 Task: Update AGENTS.md with new architecture

### Changes Made
- Updated State Machine description from "10-state HFSM (TRIAGE → POST_MORTEM)" to "8-state HFSM (DISPATCH → THINKING → MAPS_NAV → MAPS_THINK → MAPS_SURGEON → POST_MORTEM)"
- Added Batch Processing pattern: "Discovery mode finds multiple nodes before editing"
- Added Amnesia Pattern: "Navigation state cleared but tracked nodes preserved"

### Learnings
- The new architecture removes TRIAGE, ROUTER, SEARCH, SENSE states
- Core states are now: DISPATCH, THINKING, MAPS_NAV, MAPS_THINK, MAPS_SURGEON, POST_MORTEM
- Batch processing is a key pattern - find multiple nodes before editing
- Amnesia pattern clears navigation state but preserves tracked nodes

### Issues Encountered
- None

### Decisions Made
- Updated AGENTS.md to reflect the new 8-state architecture
- Added documentation for batch processing and amnesia patterns

---

## 2026-04-12 Task: Document Amnesia Pattern

### What is the Amnesia Pattern?
The Amnesia Pattern is a state management technique used in MAPS_NAV to clear navigation state while preserving tracked nodes. This allows the system to move between different discovery phases without losing context about which nodes have been identified for editing.

### Implementation
```python
# In MAPS_NAV.tick():
job.maps_state["current_step_index"] += 1
if "navigation_stack" in job.maps_state:
    del job.maps_state["navigation_stack"]
```

### Why is it needed?
- **Navigation state** (e.g., `navigation_stack`, `ast_stack`) is specific to a single file exploration
- **Tracked nodes** (e.g., `tracked_nodes`) represent the work items to be edited
- When discovering multiple symbols, we need to clear the navigation context but keep the work items
- This allows MAPS_NAV to find symbol 1, clear navigation, find symbol 2, clear navigation, etc.

### Flow
1. MAPS_NAV discovers symbol 1 → tracks nodes → clears navigation state
2. MAPS_NAV discovers symbol 2 → tracks nodes → clears navigation state
3. MAPS_NAV discovers symbol 3 → tracks nodes → clears navigation state
4. MAPS_NAV transitions to MAPS_THINK to review all tracked nodes

---

## 2026-04-12 Task: Document Batch Processing Flow

### What is Batch Processing?
Batch processing is the core pattern that allows Ariadne to discover multiple edit locations before applying any edits. This is in contrast to the old single-pass approach where it would edit one location, test, then move to the next.

### Flow Diagram
```
User Input
    ↓
[THINKING] → Analyze failures, create plan with multiple steps
    ↓
[MAPS_NAV] → Discovery Mode
    ├─→ Find symbol 1 → Track nodes → Amnesia
    ├─→ Find symbol 2 → Track nodes → Amnesia
    └─→ ... until plan complete
    ↓
[MAPS_THINK] → Review Mode
    ├─→ Analyze node 1 → Draft fix
    ├─→ Analyze node 2 → Draft fix
    └─→ ... for each tracked node
    ↓
[MAPS_SURGEON] → Edit Mode
    ├─→ Create surgical edit
    ├─→ Apply to disk
    └─→ Remove from tracked_nodes
    ↓
[SYNTAX_GATE] → Validate syntax
    ↓
[ACTUATE] → Loop control
    ├─→ More nodes? → Back to MAPS_THINK
    └─→ Done? → Back to MAPS_NAV
```

### Key Components

#### 1. MAPS_NAV (Discovery Mode)
- Iterates through plan.steps
- For each step, finds all nodes matching the symbol
- Tracks nodes in `job.tracked_nodes`
- Clears navigation state (amnesia pattern)
- Transitions to MAPS_THINK when discovery complete

#### 2. MAPS_THINK (Review Mode)
- Processes `job.tracked_nodes` one by one
- Sends each node to LLM for diagnosis
- Creates draft code for each node
- Handles skip/abort actions
- Transitions to MAPS_SURGEON after successful diagnosis

#### 3. MAPS_SURGEON (Edit Mode)
- Applies surgical edits to the tracked node
- Performs Ghost Check (LSP validation)
- Transitions to SYNTAX_GATE after successful edit

#### 4. ACTUATE (Loop Control)
- Applies edits to disk
- Removes edited node from `job.tracked_nodes`
- Loops back to MAPS_THINK if more nodes remain
- Returns to MAPS_NAV when all nodes processed

### Benefits
1. **Deterministic**: No LLM-driven routing decisions
2. **Efficient**: Discover all locations before editing
3. **Safe**: Syntax validation before each edit
4. **Flexible**: Can skip or abort individual nodes

---

## 2026-04-12 Task: Cleanup

### Changes Made
- Removed unused imports from states.py (subprocess, shlex, tempfile, threading)
- Removed unused field from JobPayload (extracted_nodes)
- Fixed duplicate code in MAPS_NAV

### Learnings
- Unused imports and fields can accumulate during refactoring
- Debug logging was already minimal (no logger.debug statements)
- Duplicate code in MAPS_NAV was a result of incremental edits

### Issues Encountered
- None

### Decisions Made
- Removed unused imports to keep codebase clean
- Removed unused field to reduce payload size
- Fixed duplicate code to prevent confusion
