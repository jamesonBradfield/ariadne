import tree_sitter_rust as tsrust
from tree_sitter import Language, Node, Parser

# 1. Initialize the Rust language parser
# We add type ignores here because the C-bindings return pointers
# that make strict LSPs like basedpyright panic.
RUST_LANGUAGE = Language(tsrust.language())  # type: ignore
parser = Parser(RUST_LANGUAGE)

# 2. The Dummy Payload
rust_code = """
fn main() {
    println!("Hello, Ariadne!");
}

struct GameState {
    is_running: bool,
}

impl GameState {
    fn start(&mut self) {
        self.is_running = true;
    }
}
"""
