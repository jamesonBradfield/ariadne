import pytest
import os
import tempfile
from unittest.mock import MagicMock
from ariadne.states import MAPS
from ariadne.payloads import JobPayload
from ariadne.testing.mock_primitives import MockQueryLLM
from ariadne.profiles.rust_profile import RustProfile

@pytest.fixture
def temp_rust_file():
    content = b"fn main() {\n    let x = 1;\n}\n\nfn foo() {\n    // some comment\n}\n"
    with tempfile.NamedTemporaryFile(suffix=".rs", delete=False) as f:
        f.write(content)
        path = f.name
    yield path
    if os.path.exists(path):
        os.remove(path)

def test_maps_state_transition(temp_rust_file):
    # Setup mock config manager
    config_manager = MagicMock()
    config_manager.get_model_info.return_value = {
        "model": "mock-model",
        "api_base": "mock-api",
        "system_prompt": "sys",
        "user_prompt_template": "user",
        "params": {},
        "post_process": "extract_json"
    }
    config_manager.render_prompt.side_effect = lambda template, vars: template

    # Setup profile
    profile = RustProfile()

    # Instantiate MAPS state
    maps_state = MAPS(config_manager, profile)

    # Define mock responses
    responses = {
        "MAPS": {"action": "replace", "target": 0, "code": "fn foo() { println!(\"fixed\"); }"}
    }
    mock_llm = MockQueryLLM(responses=responses)
    
    # Replace the real LLM with our mock
    maps_state.llm = mock_llm

    # Setup JobPayload
    # We need to find the byte offsets for 'foo' in our temp file.
    # fn main() { ... } is bytes 0 to ~25
    # fn foo() { ... } starts after that.
    with open(temp_rust_file, "rb") as f:
        content = f.read()
        foo_start = content.find(b"fn foo")
        foo_end = content.find(b"}", foo_start) + 1

    job = JobPayload(
        intent="fix foo",
        target_files=[temp_rust_file],
        current_file_index=0,
        extracted_nodes=[{
            "symbol": "foo",
            "start_byte": foo_start,
            "end_byte": foo_end
        }]
    )

    # First tick: Execute 'replace'
    status, updated_job = maps_state.tick(job)
    assert status == "MAPS"
    assert len(job.fixed_code["edits"]) == 1
    assert job.fixed_code["edits"][0]["action"] == "replace"
    assert job.fixed_code["edits"][0]["new_code"] == "fn foo() { println!(\"fixed\"); }"

    # Second tick: LLM returns 'done'
    mock_llm.responses["MAPS"] = {"action": "done"}
    status, updated_job = maps_state.tick(job)
    assert status == "MAPS"
    assert job.maps_state["current_target_index"] == 1

    # Third tick: Should transition to SYNTAX_GATE
    status, updated_job = maps_state.tick(job)
    assert status == "SYNTAX_GATE"
    assert not hasattr(job, "maps_state")
