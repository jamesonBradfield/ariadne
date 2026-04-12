import pytest
import sys
import os
import json

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ariadne.components import SyntaxGate
from ariadne.profiles.base import DynamicProfile


# Load Rust profile from JSON
with open(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ariadne",
        "profiles",
        "rust.json",
    ),
    "r",
) as f:
    RUST_CONFIG = json.load(f)

profile = DynamicProfile(RUST_CONFIG)


def test_syntax_gate_valid_rust():
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
    gate = SyntaxGate(profile)

    # Invalid Rust code
    is_valid, error = gate.sensor.validate_repair(b"fn main() { let x = ; }", [])

    assert not is_valid
    assert "Syntax error" in error
