Phase 1: The Foundation (The Dataflow HFSM)

Forget the AI for a second. This is the structural plumbing.

    No Blackboards: States do not share global memory. Data is passed via strict, typed objects (e.g., ContextPayload, JobPayload).

    Stateless Primitives (The Pipes): You build dumb, single-purpose child states that don't know about the larger engine:

        ExtractAST: Takes a file, returns code strings.

        QueryLLM: Takes a prompt, returns AI text/JSON.

        ExecuteCommand: Runs terminal commands (like cargo test), returns stdout/stderr.

    Parent States (The Plumbers): These manage the Payload, tick their children, and route the output of one child into the input of the next.

Phase 2: The Core Loop (Agentic TDD)

This is the MVP workflow. You build this once Phase 1 is stable.

    Step 1: TRIAGE: The engine takes your vague intent and (eventually) live Godot runtime data to figure out what you want.

    Step 2: DISPATCH (The Contract): The LLM writes a strict unit test to prove your intent. You manually approve the test. Ariadne locks this test file as READ-ONLY.

    Step 3: THE CRUCIBLE (Self-Healing Loop):

        Evaluate: Runs cargo test. It fails. Captures the error.

        Search: Progressive disclosure. Looks at skeletons, asks the LLM what nodes it needs, then gets the full code for only those nodes.

        Coding: LLM writes the implementation to satisfy the locked test and failing compiler error.

        Amnesia Tick: The engine completely wipes the LLM's context memory and loops back to Evaluate until the compiler turns green.

Phase 3: The "Spice" (The Backlog)

Do not build these until Phase 1 and 2 are flawlessly writing basic Rust code.

    The RESEARCH State: Inserting a step before DISPATCH where the engine queries a DocResolver to fact-check API signatures before the LLM is allowed to write code.

    The UPGRADE State: If cargo check throws a missing method error, piping the error into cargo-semver-checks to feed the LLM the exact JSON diff of the breaking change.
