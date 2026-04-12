import pytest
from ariadne.components import SyntaxGate


class MockRustProfile:
    def get_language_ptr(self):
        from tree_sitter import Language

        return Language("tree-sitter-rust", "rust")


profile = MockRustProfile()


def test_syntax_gate_valid_rust():
    profile = RustProfile()
    gate = SyntaxGate(profile)

    # Valid Rust code
    # fn main() { ... }
    # 012345678901
    # { is at index 10
    # } is at index 11
    is_valid, error = gate.sensor.validate_repair(
        b"fn main() {}",
        [{"start_byte": 11, "end_byte": 11, "new_code": 'println!("hi");'}],
    )
    if not is_valid:
        print(f"DEBUG: {error}")
    assert is_valid
    assert error is None


def test_syntax_gate_invalid_rust():
    profile = RustProfile()
    gate = SyntaxGate(profile)

    # Invalid Rust code
    is_valid, error = gate.sensor.validate_repair(b"fn main() { let x = ; }", [])

    assert not is_valid
    assert "Syntax error" in error
