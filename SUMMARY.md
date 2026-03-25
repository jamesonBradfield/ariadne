# Ariadne ECS Rewrite System - Summary

## Overview
This project implements a modular, component-based system for programmatically modifying Rust source code using tree-sitter for precise AST manipulation. The system follows a "Drive-by-Wire" approach where we surgically inject new code at exact byte coordinates.

## Files Created

### 1. test.rs
The target Rust file containing:
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

### 2. components.py
Modular components for the system:

- **TreeSitterSensor**: Language-agnostic sensor that queries an AST and extracts raw byte coordinates
  - Takes a language pointer in constructor for universality
  - `extract_node()` method returns start_byte, end_byte, node_string, and full_source

- **DriveByWireActuator**: Static class that surgically injects new bytes into a file
  - `splice()` method takes filepath, full_source, start/end coordinates, and new payload
  - Performs byte-level splicing: before + new_payload + after

### 3. state.py
Finite State Machine implementation:

- **State**: Abstract base class for all states
- **SenseState**: Extracts target node using TreeSitterSensor
- **ActuateState**: Modifies file using DriveByWireActuator
- **CompleteState**: Final state indicating success
- **StateMachine**: Manages state transitions

### 4. engine_mvp.py
Main orchestrator that:
1. Sets up context with filepath, query string, and new payload
2. Creates and configures the state machine with SENSE → ACTUATE → COMPLETE flow
3. Executes the state machine to modify test.rs

## How It Works

1. **Sensing Phase**: 
   - TreeSitterSensor parses test.rs with Rust grammar
   - Executes query to find `function_item` with name "take_damage"
   - Returns exact byte coordinates and full source

2. **Actuation Phase**:
   - DriveByWireActuator takes the source bytes
   - Splits into before (0 to start_byte) and after (end_byte to end)
   - Concatenates before + new_function_bytes + after
   - Writes back to test.rs

3. **State Machine Flow**:
   - SENSE: Extract target data → ACTUATE
   - ACTUATE: Splice new payload → COMPLETE
   - COMPLETE: Mission accomplished → END

## Example Modifications

Original function:
```rust
fn take_damage(&mut self, amount: i32) {
    self.health -= amount;
    println!("Player took {} damage, health is now {}", amount, self.health);
}
```

After first run:
```rust
fn take_damage(&mut self, amount: i32) {
    println!("Drive-by-wire successful! Took {} damage", amount);
}
```

After state machine version:
```rust
fn take_damage(&mut self, amount: i32) {
    println!("State machine rewrite successful. Took {} damage", amount);
}
```

## Key Features

- **Language Agnostic**: TreeSitterSensor accepts any language pointer
- **Precise Modification**: Works at byte level for exact replacements
- **Modular Design**: Separation of sensing, actuation, and control logic
- **Reusable Components**: Sensor and actuator can be used independently
- **Extensible**: Easy to add new states or modify the state machine flow

## Usage

```bash
python engine_mvp.py
```

Output:
```
[SENSE] Extracting target node...
[SENSE] Acquired bytes 62 to 194
Transitioning to ACTUATE
[ACTUATE] Splicing new payload...
[ACTUATE] Drive-by-Wire complete. AST modified.
Transitioning to COMPLETE
[COMPLETE] Mission accomplished.
State machine completed successfully.

State machine execution completed successfully!
```

The system has successfully modified test.rs multiple times through different implementations, demonstrating the robustness of the component-based approach.