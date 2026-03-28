import tree_sitter_rust
from state import StateMachine, SenseState, ActuateState, CompleteState
from components import TreeSitterSensor, DriveByWireActuator


def main():
    # Setup context with all necessary information
    context = {
        "filepath": "test.rs",
        "query_string": """
        (function_item
            name: (identifier) @func_name
            (#eq? @func_name "take_damage")
        ) @function
        """,
        "new_payload": """    fn take_damage(&mut self, amount: i32) {
        println!("State machine rewrite successful. Took {} damage", amount);
    }
""",
    }

    # Create and configure the state machine
    sm = StateMachine()
    sm.add_state(SenseState())
    sm.add_state(ActuateState())
    sm.add_state(CompleteState())
    sm.set_initial_state("SENSE")

    # Execute the state machine
    success = sm.execute(context)

    if success:
        print("\nState machine execution completed successfully!")
    else:
        print("\nState machine execution failed!")


if __name__ == "__main__":
    main()
