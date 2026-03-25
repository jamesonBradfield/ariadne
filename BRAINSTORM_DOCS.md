# HFSM Brainstorm Documentation: Gemini Conversation Insights

## Validation: Industry Alignment

Gemini confirms the HFSM/Ecu paradigm aligns with cutting-edge AI engineering trends:

1. **TextGrad Exists** - Stanford's open-source framework (published in Nature) treats LLM text feedback as backpropagation gradients
2. **LangGraph & Hybrid Workflows** - Industry moving from autonomous agent chats to deterministic state machines blending LLM planning with tool execution
3. **VT Code & Structural Edits** - New frontier in amputating LLM's "hands" using AST-based editing instead of fragile regex diffs

> "Your architecture isn't reinventing the wheel—it is assembling the ultimate hot rod from the newest parts available."

## Core Architectural Principles

### 1. Python Hooks Over JSON for Extensibility
- JSON becomes limiting when needing multiple shell commands, API calls, or conditional logic
- Pure Python classes provide native composition and infinite extensibility
- State as lightweight dataclass holding list of callable Python functions (hooks)

```python
from dataclasses import dataclass, field
from typing import List, Callable

@dataclass
class DynamicState:
    name: str
    intent_trigger: str  # What Small LLM looks for
    context_hooks: List[Callable] = field(default_factory=list)
    prompt_template: str = ""

    def assemble_payload(self) -> str:
        gathered_data = ""
        for hook in self.context_hooks:
            gathered_data += hook() + "\n"
        return self.prompt_template.format(context=gathered_data)
```

### 2. The "No-String" Rule: Structured Data Over Terminal Parsing
Avoid fragile regex filtering of CLI output by demanding structured data from hooks:

- **Compiler Hook**: `cargo check --message-format=json` → parse JSON dict directly
- **AST Hook**: Tree-sitter returns traversable Python object → check `tree.root_node.has_error:` (boolean)
- **Neovim LSP Hook**: RPC returns JSON object with line/column/diagnostic code

> "The Python script handles JSON parsing and extracts pure facts. The LLM only sees deterministic constraints, never raw terminal output."

### 3. Environment Context for Bulletproof Triggers
Leverage active editor state instead of guessing user intent:

- **LSP Trigger**: Query Neovim LSP for diagnostics in active buffer
- **Active Buffer Trigger**: Use current Neovim buffer filepath to constrain TreeSitterContext
- **Cursor Position**: Extract exact line number for precise AST node extraction

### 4. Small LLM as Intent Classifier/Router
Replace fragile keyword search with deterministic classification:

```
System Prompt to Small LLM:
"The user said: '[natural language request]'. Current Neovim buffer: [filepath]. 
Which state should activate: [IDLE, CODING, DEBUGGING]? Output only the state name."
```

## State Definition Patterns

### Simplified State Configuration (Python-Based)
Each state defined by:
1. **Condition**: When to activate (could be Small LLM classification result)
2. **Shell Hook**: Command to run for context gathering
3. **Prompt Template**: With placeholders for hook output

### Hybrid Approach: Configuration-Driven with Python Escape Hatches
- Start with JSON/YAML for simple states
- Allow custom Python hooks for complex logic when needed
- Maintains readability while preserving extensibility

## Next Steps for Implementation

When transitioning from brainstorming to code:

1. **Start with Tree-sitter Extraction Script**
   - Standalone script to extract AST node start/end bytes from Rust file
   - Prove Drive-by-Wire concept before integrating with LLMs

2. **Draft Cargo JSON Parser Hook**
   - Implement `cargo check --message-format=json` parsing
   - Extract structured error data without string regex

3. **Design Neovim LSP Python Hook**
   - Use pynvim to connect to active Neovim instance
   - Query LSP for diagnostics at cursor position
   - Return structured diagnostic data

4. **Create Simplified Python State Dataclass**
   - Implement the DynamicState class with hook composition
   - Test with simple shell command hooks

5. **Design Golden DB SQLite Schema**
   - Table for successful (prompt, code) pairs
   - Index by state intent, context hash, timestamp
   - Fields: id, state_intent, context_hash, prompt_text, code_snippet, success_timestamp, usage_count

## Key Takeaways

- **Determinism > Stochasticity**: Context determined by state/hooks, not LLM guessing via RAG
- **Component Reusability**: New capabilities via hook attachment, not new state classes
- **LLM Specialization**: Small LLM handles routing/prompt compilation; Big LLM handles pure code generation
- **Self-Optimization**: System learns from successes via Golden DB to improve future prompts
- **Safety Guarantees**: AST-level validation prevents syntax errors from reaching compiler
- **Token Efficiency**: Isolated AST nodes minimize context window usage

This architecture transforms the LLM from an unreliable autonomous agent into a reliable execution unit within a deterministic control system—exactly the "Engine Control Unit" paradigm needed for trustworthy AI-assisted development.