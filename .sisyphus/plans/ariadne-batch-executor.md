# Ariadne Batch Executor Refactoring Plan

## Objective
Refactor Ariadne from a single-pass surgical editor to a batch-processing executor that:
1. Discovers multiple edit locations before editing
2. Uses amnesia pattern (clear navigation state, preserve tracked nodes)
3. Removes LLM-driven routing decisions
4. Implements deterministic flow between discovery, review, and editing

## Current Architecture Problems
1. **TRIAGE fails often** - LLM struggles to distill intent
2. **DISPATCH is premature** - Building test contracts before reading code
3. **ROUTER is redundant** - LLM-driven state decisions can be deterministic
4. **SENSE/SEARCH are intermediate** - Can be merged into NAVIGATE
5. **THINKING overlaps MAPS_THINK** - Same functionality in different states

## Proposed Architecture

### States to Keep (5 core states):
1. **TRIAGE** - Extract intent (minimal, could be removed later)
2. **THINKING** - Create repair plan from failures
3. **MAPS_NAV** - Discovery mode: Find all promising nodes
4. **MAPS_THINK** - Review mode: Analyze tracked nodes
5. **MAPS_SURGEON** - Edit mode: Apply surgical fixes

### States to Remove (3 states):
1. **ROUTER** - Deterministic flow replaces LLM routing
2. **SEARCH** - Merged into MAPS_NAV discovery
3. **SENSE** - Merged into MAPS_NAV discovery

### Services to Create/Enhance:
1. **TestExecutionService** - Replace EVALUATE state
2. **SymbolSensingService** - Find symbol locations
3. **SyntaxValidationService** - Validate syntax before write
4. **ActuationService** - Apply edits to disk

## Implementation Steps

### Step 1: Remove States (COMPLETED)
- [x] Remove ROUTER state from states.py
- [x] Remove SEARCH state from states.py
- [x] Remove SENSE state from states.py
- [x] Update all state transitions to use new flow
- [x] Remove RouterResponse from payloads.py
- [x] Update valid_states list in primitives.py
- [x] Remove ROUTER config from ariadne_config.json

### Step 2: Update MAPS_NAV for Discovery Mode (COMPLETED)
- [x] Implement node tracking in job.tracked_nodes
- [x] Find all nodes for each symbol in plan
- [x] Use amnesia pattern (clear navigation, keep tracked nodes)
- [x] Transition to MAPS_THINK when discovery complete

### Step 3: Update MAPS_THINK for Batch Review (COMPLETED)
- [x] Process tracked nodes one by one
- [x] Send each to LLM for diagnosis
- [x] Prepare for surgical editing
- [x] Handle skip/abort actions

### Step 4: Update MAPS_SURGEON and ACTUATE (COMPLETED)
- [x] Edit nodes from tracked_nodes list
- [x] Remove edited nodes from tracking
- [x] Loop back to MAPS_THINK if more nodes remain
- [x] Return to MAPS_NAV when all nodes processed

### Step 5: Update Other States (COMPLETED)
- [x] Update THINKING to transition directly to MAPS_NAV
- [x] Update FILE_EXPLORER to transition to MAPS_NAV
- [x] Update SPAWN to initialize work list and transition to MAPS_NAV
- [x] Update INTERVENE default state from ROUTER to MAPS_NAV

### Step 6: Verify and Test
- [x] Run syntax checks on all modified files
- [x] Test engine startup
- [ ] Test basic flow with sample intent
- [ ] Verify batch processing works correctly

### Step 7: Documentation
- [x] Update AGENTS.md with new architecture
- [x] Document the amnesia pattern
- [x] Document the batch processing flow

### Step 8: Cleanup
- [x] Remove unused imports
- [x] Remove unused payload fields
- [x] Clean up debug logging

## New Flow Diagram

```
User Input
    ↓
[TRIAGE] → Extract intent
    ↓
[THINKING] → Analyze failures, create plan
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

## Key Patterns

### Amnesia Pattern
```python
# Clear navigation state but preserve tracked nodes
if "navigation_stack" in job.maps_state:
    del job.maps_state["navigation_stack"]
# job.tracked_nodes persists across iterations
```

### Batch Processing Loop
```python
# MAPS_NAV: Discover and track
for symbol in plan.steps:
    nodes = find_symbol(symbol)
    job.tracked_nodes.extend(nodes)

# MAPS_THINK: Review one node at a time
node = job.tracked_nodes[0]
# ... analyze and draft ...

# ACTUATE: Edit and remove from tracking
edit_node(node)
job.tracked_nodes.pop(0)
# Loop back if more nodes remain
```

## Decisions Made
1. **TRIAGE**: Removed - Start directly in THINKING with user intent
2. **EVALUATE**: Made into TestExecutionService - Called by ACTUATE after edits
3. **POST_MORTEM**: Made into background service - Not part of main flow
4. **FILE_EXPLORER**: Merged into MAPS_NAV - Unified navigation state

## Success Criteria
- [ ] Engine starts without errors
- [ ] Can process user intent and create plan
- [ ] Can discover multiple edit locations
- [ ] Can edit multiple nodes in batch
- [ ] Can verify edits with tests/LSP
- [ ] No LLM-driven routing decisions
- [ ] Amnesia pattern works correctly
