import pytest
import os
import tempfile
from unittest.mock import MagicMock, patch
from ariadne.states import SENSE, MAPS, SYNTAX_GATE, ACTUATE
from ariadne.payloads import JobPayload
from ariadne.profiles.rust_profile import RustProfile
from ariadne.profiles.python_profile import PythonProfile

@pytest.fixture
def temp_rust_file():
    content = b"fn main() {\n    let x = 1;\n}\n"
    with tempfile.NamedTemporaryFile(suffix=".rs", delete=False) as f:
        f.write(content)
        path = f.name
    yield path
    if os.path.exists(path):
        os.remove(path)

@pytest.fixture
def temp_python_file():
    content = b"def calculate(a, b):\n    return a + b\n"
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(content)
        path = f.name
    yield path
    if os.path.exists(path):
        os.remove(path)

def test_rust_end_to_end_repair(temp_rust_file):
    # Setup
    config_manager = MagicMock()
    config_manager.get_model_info.return_value = {"model": "m", "api_base": "a", "params": {}}
    config_manager.config = {"states": {"MAPS": {"system_prompt": "s", "user_prompt_template": "u", "post_process": "extract_json"}}}
    config_manager.render_prompt.side_effect = lambda t, v: t
    
    profile = RustProfile()
    sense_state = SENSE(profile)
    maps_state = MAPS(config_manager, profile)
    syntax_gate = SYNTAX_GATE(profile)
    actuate = ACTUATE()

    # Initial Job
    job = JobPayload(
        intent="fix rust main",
        target_files=[temp_rust_file],
        maps_state={"current_step_index": 0, "steps": [{"symbol": "main"}]}
    )

    with patch("ariadne.states.QueryLLM") as MockLLM:
        mock_instance = MockLLM.return_value
        
        # 1. SENSE
        status, job = sense_state.tick(job)
        assert status == "MAPS"
        assert len(job.extracted_nodes) == 1
        
        # 2. MAPS (Zoom into block)
        # named_children: identifier (0), parameters (1), block (2)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "zoom", "target_id": 2})
        status, job = maps_state.tick(job)
        assert status == "MAPS"
        
        # 3. MAPS (Replace let x = 1 with let x = 42)
        # block named_children: let_declaration (0)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "replace", "target_id": 0, "code": "let x = 42;"})
        status, job = maps_state.tick(job)
        assert status == "MAPS"
        assert len(job.fixed_code["edits"]) == 1
        
        # 4. MAPS (Done)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "done"})
        status, job = maps_state.tick(job)
        assert status == "SYNTAX_GATE"
        
        # 5. SYNTAX_GATE
        status, job = syntax_gate.tick(job)
        assert status == "ACTUATE"
        
        # 6. ACTUATE
        status, job = actuate.tick(job)
        assert status == "SENSE"
        assert job.maps_state["current_step_index"] == 1

    # Verify Disk Change
    with open(temp_rust_file, "r") as f:
        new_content = f.read()
    assert "let x = 42;" in new_content
    assert "let x = 1;" not in new_content
    assert "fn main() {" in new_content

def test_python_end_to_end_repair(temp_python_file):
    # Setup
    config_manager = MagicMock()
    config_manager.get_model_info.return_value = {"model": "m", "api_base": "a", "params": {}}
    config_manager.config = {"states": {"MAPS": {"system_prompt": "s", "user_prompt_template": "u", "post_process": "extract_json"}}}
    config_manager.render_prompt.side_effect = lambda t, v: t
    
    profile = PythonProfile()
    sense_state = SENSE(profile)
    maps_state = MAPS(config_manager, profile)
    syntax_gate = SYNTAX_GATE(profile)
    actuate = ACTUATE()

    # Initial Job
    job = JobPayload(
        intent="fix python calculate",
        target_files=[temp_python_file],
        maps_state={"current_step_index": 0, "steps": [{"symbol": "calculate"}]}
    )

    with patch("ariadne.states.QueryLLM") as MockLLM:
        mock_instance = MockLLM.return_value
        
        # 1. SENSE
        status, job = sense_state.tick(job)
        assert status == "MAPS"
        
        # 2. MAPS (Zoom into body block)
        # named_children: identifier (0), parameters (1), block (2)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "zoom", "target_id": 2})
        status, job = maps_state.tick(job)
        assert status == "MAPS"
        
        # 3. MAPS (Replace return a + b with return a * b)
        # block named_children: return_statement (0)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "replace", "target_id": 0, "code": "    return a * b"})
        status, job = maps_state.tick(job)
        assert status == "MAPS"
        
        # 4. MAPS (Done)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "done"})
        status, job = maps_state.tick(job)
        assert status == "SYNTAX_GATE"
        
        # 5. SYNTAX_GATE
        status, job = syntax_gate.tick(job)
        assert status == "ACTUATE"
        
        # 6. ACTUATE
        status, job = actuate.tick(job)
        assert status == "SENSE"

    # Verify Disk Change
    with open(temp_python_file, "r") as f:
        new_content = f.read()
    assert "return a * b" in new_content
    assert "return a + b" not in new_content
    assert "def calculate(a, b):" in new_content

if __name__ == "__main__":
    pytest.main([__file__])
