# Ariadne ECS Engine

A true Entity-Component-System (ECS) engine for programmatically modifying source code using tree-sitter for precise AST manipulation.

## Overview

Ariadne implements a "Drive-by-Wire" approach to source code modification where we:
1. Use tree-sitter to parse source code into an AST
2. Query the AST to locate specific code elements (functions, structs, etc.)
3. Extract exact byte coordinates of those elements
4. Surgically replace the code at those coordinates with new payloads
5. Manage the process through a clean ECS architecture

## Core Architecture

### Entity-Component-System Pattern

- **Entities**: States that hold components and define execution flow
- **Components**: Reusable tools (sensors, actuators) that perform specific functions  
- **Systems**: The engine loop that manages state transitions and data flow

### Key Components

1. **Core Chassis** (`core.py`)
   - `EngineContext`: Shared memory bus passed between states
   - `State`: Base entity class that all states inherit from

2. **Reusable Components** (`components.py`)
   - `TreeSitterSensor`: Language-agnostic AST querying component
   - `DriveByWireActuator`: Surgical byte-level file modification component

3. **Engine Implementation** (`engine.py`)
   - Concrete states: `SenseState`, `ActuateState`
   - Engine loop that runs until reaching the "IDLE" state

## Files

- `test.rs` - Target Rust file for modification
- `core.py` - ECS chassis (EngineContext, State base class)
- `components.py` - Reusable tools (TreeSitterSensor, DriveByWireActuator)
- `engine.py` - Main engine with concrete states and execution loop
- `FINAL_SUMMARY.md` - Detailed architecture summary

## Usage

```bash
python engine.py
```

## Example

**Before:**
```rust
struct Player {
    health: i32,
}

impl Player {
    fn take_damage(&mut self, amount: i32) {
        self.health -= amount;
        println!("Player took {} damage, health is now {}", amount, self.health);
    }
}
```

**After:**
```rust
struct Player {
    health: i32,
}

impl Player {
    fn take_damage(&mut self, amount: i32) {
        println!("The ECS State Machine is fully operational. Took {} damage", amount);
    }
}
```

## Features

- ✅ True ECS architecture with clean separation of concerns
- ✅ Language-agnostic sensor component
- ✅ Precise byte-level code modification
- ✅ Shared context for state communication
- ✅ Clean state lifecycle (enter/execute/exit)
- ✅ Modular, reusable components
- ✅ Extensible design for adding new states/tools