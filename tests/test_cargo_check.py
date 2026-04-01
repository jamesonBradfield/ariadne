import pytest
from ariadne.profiles.rust_godot import CargoCheckHook

def test_cargo_check_hook_structure():
    """Test that the CargoCheckHook component returns the expected dictionary structure."""
    hook = CargoCheckHook()
    result = hook.execute()

    # Check that we get a dictionary with the expected keys
    assert isinstance(result, dict)
    assert "success" in result
    assert "messages" in result
    assert "errors" in result
    assert "raw_output" in result
    
    # Even if it fails (no rust project), it should return a result
    if not result["success"]:
        assert isinstance(result["errors"], list)
