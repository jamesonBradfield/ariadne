import tree_sitter_rust
from ariadne.components import SyntaxGate


def test_syntax_gate():
    gate = SyntaxGate(tree_sitter_rust.language())

    # Valid Rust code
    valid_code = """
fn take_damage(&mut self, amount: i32) {
    println!("Hello {}", amount);
}
"""
    result = gate.validate(valid_code)
    print("Valid code test:")
    print(f"  Valid: {result['valid']}")
    if not result["valid"]:
        print(f"  Error: {result['error_message']}")

    # Invalid Rust code
    invalid_code = """
fn take_damage(&mut self, amount: i32) {
    println!("Hello {}", amount)
} // missing semicolon
"""
    result2 = gate.validate(invalid_code)
    print("\nInvalid code test:")
    print(f"  Valid: {result2['valid']}")
    if not result2["valid"]:
        print(f"  Error: {result2['error_message']}")

    # Another invalid: completely wrong
    invalid2 = "this is not rust"
    result3 = gate.validate(invalid2)
    print("\nCompletely invalid test:")
    print(f"  Valid: {result3['valid']}")
    if not result3["valid"]:
        print(f"  Error: {result3['error_message']}")

    return result["valid"] and not result2["valid"] and not result3["valid"]


if __name__ == "__main__":
    success = test_syntax_gate()
    print(f"\nAll tests passed: {success}")
