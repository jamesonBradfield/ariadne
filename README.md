 # Ariadne

# LLM Orchestration Layer: The Engine Control Unit (ECU)


## The "Anti-MCP" Developer Pitch

Currently, if a developer wants to give an AI coding agent a new tool, the industry standard is to build a full Model Context Protocol (MCP) server. This requires dealing with JSON-RPC, standard streams, Server-Sent Events, and heavy SDKs just to run a basic shell command.


**Ariadne is a lightweight, decentralized alternative to MCP.**


By replacing stochastic "chat-to-diff" autonomous agents with a deterministic **Entity-Component-System (ECS) in Python**, this architecture shifts power back to the developer:


1. **Frictionless Tooling:** Want a tool that checks `git blame` to see who wrote a broken function? Don't build a server. Write a 10-line Python function that formats the subprocess output and snap it onto the state machine.

2. **Absolute Token Control:** Instead of the LLM fetching a massive JSON payload and burning 8,000 tokens reading it, your Python hook extracts the exact lines that matter and passes *only* those to the prompt.

3. **Decentralized Sharing:** Because tools are just isolated Python functions attached to a dataclass, a developer can write a custom `godot_scene_parser` hook, drop the `.py` file in a chat, and anyone can instantly bolt it onto their own HFSM chassis without configuring a single port.


---


## Overview


Current autonomous coding agents operate on a flawed "LLMs have hands" paradigm. They rely on stochastic RAG queries to guess what context they need, and fragile regex/diff blocks to apply their own edits, leading to hallucination spirals and context window bloat.


This architecture proposes a **Hierarchical Finite State Machine (HFSM)** that strips the heavy LLM of its autonomy. It operates as a distributed, two-gear engine:

- **The ECU (Ariadne / Laptop):** A blazing-fast small LLM handles the routing, prompt compilation, and TextGrad telemetry with zero VRAM swapping penalties.

- **The Engine (Theseus / Heavy Rig):** A massive local model dedicated 100% to generating pure code.


## The Three Core Pillars


### 1. The Chassis: States as ECS (Entity-Component-System)


We reject rigid Object-Oriented state classes. A "State" is now just an empty generic container (Node) that we dress up dynamically.


#### Contexts (The Sensors)

Components attached to the state that gather deterministic local data (e.g., RipgrepContext, TreeSitterContext). The model does not ask for files; the state forces the exact necessary data into the prompt.


#### Conditions (The Triggers)

Components that evaluate when to shift gears (e.g., ExitCodeCondition(0) from a Cargo check).


#### The ECU (Prompt Compiler)

A blazing-fast local model (like a 1.5B/8B parameter LLM) reads the raw sensor data and dynamically compiles a strict, 2-sentence directive for the heavy-lifting LLM.


##### Implementation Details:

- States are generic containers that hold lists of Context and Condition components

- When a state is activated, it executes all its ContextComponents to gather raw data

- The small LLM (Prompt Compiler) takes the parent prompt, state intent, and raw context to generate a specific directive for the big LLM

- This eliminates hardcoded strings and allows dynamic adaptation to new tools/languages


### 1.5 The Context Engine: The GATHER State & Active Foraging


To solve "Context Starvation" without resorting to massive, token-heavy RAG pipelines, Ariadne employs a deterministic, multi-turn research loop. We shift the Heavy LLM from a passive code generator into an active, iterative researcher using a Skeleton Map.

The Skeleton Map (Token-Efficient Topology)


Instead of feeding the LLM raw files or relying on blind ripgrep searches, the ECU uses Tree-sitter to generate a "Skeleton" of the project. It extracts only the declarations (struct, impl, fn) and replaces all function bodies with ....

This compresses a massive codebase into a highly token-efficient structural map (similar to an LSP document symbol tree), giving the LLM global architectural awareness for pennies on the token budget.

Active Foraging (The FETCH Loop)


Before the heavy engine writes code, it enters the GATHER state.

- The LLM reviews the Skeleton Map and the user's objective.

- If it needs to see how a specific struct or function is implemented, it outputs a strict command: FETCH: <symbol_name> (e.g., FETCH: RenderContext).

- The LLM does not need to be perfectly accurate. The Python ECU intercepts this command, runs a fuzzy-match (e.g., Levenshtein distance) against the skeleton index, finds the closest AST node, extracts the exact byte-range from disk, and appends the full implementation to the EngineContext.

- The LLM loops in this GATHER state until it is satisfied, at which point it transitions to ACTUATE.


### The Amnesic Tick (Stateless Execution)


Standard chat agents fail because their context window fills with previous turns, typos, and conversational bloat ("Context Drift").

Ariadne operates on a Stateless Execution Pipeline. Once an ACTUATE loop successfully splices code and passes the SyntaxGate, the context is instantly wiped. The next task on the system's internal todo.md starts with a pristine context window. This allows Ariadne to execute 50-step granular refactors over hours without ever exceeding an 8k token footprint.

Future Horizon / Scope Creep: The "Shadow DOM" (Zero-Compute RAG)


Note: This is logged as the architectural alternative to traditional Vector RAG.


Instead of relying on LLMs to generate semantic metadata for vector embeddings, Ariadne will eventually separate semantic meaning from compiled code natively using Tree-sitter:

- Strip & Anchor: The ECU strips // comments from the raw source code before sending it to the LLM. It anchors these comments to the nearest AST node (e.g., mapping a comment to fn initialize_multiplayer).

- The Shadow File: These comments are stored in an asynchronous .ariadne/comments/ JSON structure, mirroring the project tree.

- Passive Integration: Developers can write commands in standard comments (e.g., // ARIADNE: Refactor this to use the new state machine). A background watchdog detects the save, wakes the engine, executes the splice, and moves the command to the semantic history log.

This keeps the actual codebase entirely free of LLM bloat while maintaining a rich, queryable semantic index of the project's intent.


### 2. The Actuator: Drive-by-Wire (AST Splicing)


We completely amputate the big LLM's "hands." The model is forbidden from writing SEARCH/REPLACE blocks, markdown formatting, or worrying about file paths.


#### Byte-Level Targeting

Using Tree-sitter, the HFSM extracts an isolated AST node (e.g., an impl block) and memorizes its exact start_byte and end_byte locations in the physical file.


#### Pure Function Execution

The big LLM receives the isolated code and outputs pure, raw Rust. It is completely blind to the larger file system.


#### The Splicer

The HFSM takes the raw string from the big LLM and drops it directly into the memorized byte slot. If the LLM hallucinates conversational text, Tree-sitter instantly flags it as invalid syntax and blocks the disk write.


##### Benefits:

- Zero File-System Awareness: The LLM is completely blind to your project structure. It only ever sees isolated chunks of logic.

- Context Window Optimization: You no longer waste tokens on <<<<<<< SEARCH syntax or repeating code that isn't changing.

- Hardware-Level Locking: If the Big LLM decides to hallucinate and outputs a conversational response, the Tree-sitter Post-Flight hook will immediately try to parse that as the target language, instantly fail, and block the write to disk. The hallucination never touches your actual codebase.


### 3. The Telemetry: TextGrad (Self-Healing Loop)


When the system hits a compilation error, it does not stubbornly feed the same generic prompt back into the loop. It self-heals.


#### Objective Loss

Deterministic feedback (like a Rust compiler traceback) acts as an objective loss function.


#### Gradient Evaluation

The small LLM (ECU) analyzes the failure, calculates the "gradient" of the mistake, and shifts the prompt for the next attempt (e.g., "Previous attempt failed. You MUST use .to_variant() this time.").


#### The Golden DB

When exit_code == 0 is finally achieved, the HFSM saves the successful prompt/code pair to a local SQLite database. In future sessions, the small LLM queries this database to learn from past "wins" and optimize instructions before firing the engine.


##### Implementation Details:

- TextGrad is implemented as a TelemetryComponent that can be selectively attached to states

- Only attached to states with objective loss functions (CODING, DEBUGGING, etc.)

- Not attached to subjective states (RESEARCH, BRAINSTORMING) to prevent hallucination loops

- The Golden DB stores successful (prompt, code) pairs indexed by state intent and context

- Before compiling a prompt, the small LLM first checks the Golden DB for similar successful executions


## The Multi-Turn Execution Loop


The engine operates in a continuous FSM tick loop:


1. **Sense:** Tree-sitter extracts the AST; tools gather contextual docs.

2. **Compile:** The ECU (Ariadne) evaluates intent, checks the Golden DB, and writes the prompt.

3. **Combust:** The heavy model (Theseus) processes the isolated AST node.

4. **Actuate:** The Drive-by-Wire hook physically splices the new bytes.

5. **Gate 1 (Syntax):** Tree-sitter / Linters run. *Fail -> Auto-fix or calculate TextGrad loss.*

6. **Gate 2 (Logic):** Headless engine probes run (e.g., `godot --headless -s probe.gd`). *Fail -> Calculate TextGrad loss.*

7. **Evaluate:** 

   - *Pass:* Save to Golden DB and drop to `IDLE`.

   - *Loop:* Inject TextGrad feedback and transition back to Step 2.

   - *Max Retries:* Break to `ANALYSIS` state to diagnose the architectural flaw.


## ECS Directory Structure


```

aider-hfsm/

├── core/

│   ├── engine.py          # The main HFSM loop and state transitions

│   ├── compiler.py        # The small LLM prompt compiler

│   └── applier.py         # AST splicing applier (replaces SEARCH/REPLACE parser)

├── components/

│   ├── conditions.py      # Triggers (ExitCodeCondition, RegexMatchCondition)

│   ├── contexts.py        # Tools (RipgrepContext, TreeSitterContext, MCPContext)

│   └── telemetry.py       # Telemetry components (TextGradEvaluator, GoldenDBLogger)

└── config/

    └── states.json        # Define your states here instead of in Python!

```


## Key Advantages Over Traditional Approaches


1. **Determinism over Stochasticity**: Context is determined by state, not guessed by the LLM via RAG

2. **Component Reusability**: New capabilities added by attaching components, not writing new state classes

3. **LLM Specialization**: Small LLM handles routing/prompt compilation; Big LLM handles pure code generation

4. **Self-Optimization**: System learns from successes and improves future prompt engineering

5. **Error Prevention**: AST-level validation prevents syntax errors from reaching the compiler

6. **Token Efficiency**: Isolated AST nodes minimize context window usage

7. **Safety Guarantees**: Hardware-level locking prevents harmful code from being written to disk


This architecture transforms the LLM from an unreliable autonomous agent into a reliable execution unit within a deterministic control system. 
