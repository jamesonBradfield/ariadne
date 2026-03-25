Your second idea—building it as a State Pre-Prompt and Post-Search Hook—is the absolute correct architectural move.

Instead of hardcoding tree-sitter into the state, you use Composition. You create a generic Hook interface. The CodingState doesn't know how to parse AST; it just knows it has a list of "Pre-Flight" and "Post-Flight" checks to run.

Here is how you inject that into the Object-Oriented HFSM we mapped out:
1. Define the Hook Interface
Python

class StateHook:
    def pre_prompt(self, filepath: str) -> str:
        """Runs BEFORE the LLM is prompted. Returns context to inject."""
        return ""

    def post_edit(self, filepath: str) -> bool:
        """Runs AFTER the SEARCH/REPLACE diff is applied. Returns True if valid."""
        return True

2. Build the Tree-sitter Plugin

Now you wrap the Python tree-sitter logic into a self-contained hook.
Python

class RustASTValidatorHook(StateHook):
    def __init__(self):
        # Initialize parser once
        self.parser = setup_tree_sitter_rust() 

    def pre_prompt(self, filepath: str) -> str:
        # E.g., extract only the relevant impl block to save tokens
        return extract_target_ast_node(filepath)

    def post_edit(self, filepath: str) -> bool:
        # The LLM just modified the file. Parse it immediately.
        with open(filepath, 'r') as f:
            tree = self.parser.parse(bytes(f.read(), "utf8"))
        
        # If the LLM forgot a closing brace, tree-sitter catches it instantly.
        if tree.root_node.has_error:
            print(f"[AST Hook] 🚨 Syntax Error detected in {filepath}!")
            return False
        return True

3. Attach Hooks to the State

Now, your CodingState becomes a pristine, modular container. You just "snap on" the tools it needs for the current job.
Python

class CodingState(BaseState):
    name = "CODING"
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # Snap on our custom gear
        self.hooks = [RustASTValidatorHook()] 

    def gather_context(self) -> str:
        # Run all Pre-Prompt hooks
        context = ""
        for hook in self.hooks:
            context += hook.pre_prompt(self.target_file)
        return context

    def execute_hooks(self, llm_output: str):
        # 1. Run the Regex Parser to apply the SEARCH/REPLACE block
        success = apply_search_replace_blocks(llm_output)
        
        if success:
            # 2. Run all Post-Edit hooks (like our AST Validator)
            for hook in self.hooks:
                if not hook.post_edit(self.target_file):
                    # Circuit Breaker! AST is broken. Force a transition to Debugging.
                    print("Reverting changes and shifting to DEBUGGING state...")
                    self.parent_controller.transition(DebuggingState)
                    return

Why this is brilliant

By doing it this way, you never have to touch the core CodingState code again.

    Want to add a hook that runs cargo fmt after the LLM edits a file? Just write a CargoFmtHook and append it to the list.

    Want to add a hook that strips out all comments before sending the file to the LLM to save tokens? Write a CommentStripperHook(StateHook).

It’s completely modular. The LLM generates the diff, the Regex applies it, and the Post-Hooks act as the final Quality Assurance gate before the HFSM decides what to do next.
