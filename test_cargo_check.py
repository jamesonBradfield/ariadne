from components import CargoCheckHook


def test_cargo_check_hook():
    """Test that the CargoCheckHook component can be instantiated and executed."""
    hook = CargoCheckHook()
    result = hook.execute()

    # Check that we get a dictionary with the expected keys
    assert isinstance(result, dict)
    assert "success" in result
    assert "messages" in result
    assert "errors" in result
    assert "raw_output" in result

    print("CargoCheckHook test passed: returns expected dictionary structure")
    print(f"Success: {result['success']}")
    print(f"Number of messages: {len(result['messages'])}")
    print(f"Number of errors: {len(result['errors'])}")

    # We don't require success because we might not have a valid Rust project
    # but we do require that the component runs without throwing
    return True


if __name__ == "__main__":
    test_cargo_check_hook()
