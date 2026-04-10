import pytest
import os
import tempfile
from unittest.mock import MagicMock, patch
from ariadne.states import SENSE, MAPS_NAV, MAPS_THINK, MAPS_SURGEON, SYNTAX_GATE, ACTUATE
from ariadne.payloads import JobPayload, MapsNavResponse, MapsThinkResponse, MapsSurgeonResponse
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
    from ariadne.core import EngineContext
    config_manager = MagicMock()
    config_manager.get_model_info.return_value = {"model": "m", "api_base": "a", "params": {}}
    config_manager.config = {
        "states": {
            "MAPS_NAV": {"system_prompt": "s", "user_prompt_template": "u", "post_process": "extract_json"},
            "MAPS_THINK": {"system_prompt": "s", "user_prompt_template": "u", "post_process": "extract_json"},
            "MAPS_SURGEON": {"system_prompt": "s", "user_prompt_template": "u", "post_process": "extract_json"}
        }
    }
    config_manager.render_prompt.side_effect = lambda t, v: t
    
    profile = RustProfile()
    context = EngineContext("SENSE", intent="fix rust main", target_files=[temp_rust_file], profile=profile)
    
    sense_state = SENSE(profile)
    nav_state = MAPS_NAV(config_manager, profile)
    think_state = MAPS_THINK(config_manager, profile)
    surgeon_state = MAPS_SURGEON(config_manager, profile)
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
        status, job = sense_state.tick(job, context)
        assert status == "MAPS_NAV"
        assert len(job.extracted_nodes) == 1
        
        # 2. MAPS_NAV (Zoom into block)
        # block ID is likely "2" or similar
        mock_instance.tick.return_value = ("SUCCESS", MapsNavResponse(reasoning="r", action="zoom", target_id="2"))
        status, job = nav_state.tick(job, context)
        assert status == "MAPS_NAV"
        
        # 3. MAPS_NAV (Select let_declaration)
        mock_instance.tick.return_value = ("SUCCESS", MapsNavResponse(reasoning="r", action="select", target_id="0"))
        status, job = nav_state.tick(job, context)
        assert status == "MAPS_THINK"
        
        # 4. MAPS_THINK (Draft fix)
        mock_instance.tick.return_value = ("SUCCESS", MapsThinkResponse(reasoning="r", action="fix", draft_code="let x = 42;"))
        status, job = think_state.tick(job, context)
        assert status == "MAPS_SURGEON"
        
        # 5. MAPS_SURGEON (Format JSON)
        mock_instance.tick.return_value = ("SUCCESS", MapsSurgeonResponse(reasoning="r", action="replace", code="let x = 42;"))
        status, job = surgeon_state.tick(job, context)
        assert status == "SYNTAX_GATE"
        assert len(job.fixed_code["edits"]) == 1
        
        # 6. SYNTAX_GATE
        status, job = syntax_gate.tick(job, context)
        assert status == "ACTUATE"
        
        # 7. ACTUATE
        status, job = actuate.tick(job, context)
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
    from ariadne.core import EngineContext
    config_manager = MagicMock()
    config_manager.get_model_info.return_value = {"model": "m", "api_base": "a", "params": {}}
    config_manager.config = {
        "states": {
            "MAPS_NAV": {"system_prompt": "s", "user_prompt_template": "u", "post_process": "extract_json"},
            "MAPS_THINK": {"system_prompt": "s", "user_prompt_template": "u", "post_process": "extract_json"},
            "MAPS_SURGEON": {"system_prompt": "s", "user_prompt_template": "u", "post_process": "extract_json"}
        }
    }
    config_manager.render_prompt.side_effect = lambda t, v: t
    
    profile = PythonProfile()
    context = EngineContext("SENSE", intent="fix python calculate", target_files=[temp_python_file], profile=profile)
    
    sense_state = SENSE(profile)
    nav_state = MAPS_NAV(config_manager, profile)
    think_state = MAPS_THINK(config_manager, profile)
    surgeon_state = MAPS_SURGEON(config_manager, profile)
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
        status, job = sense_state.tick(job, context)
        assert status == "MAPS_NAV"
        
        # 2. MAPS_NAV (Zoom into body)
        mock_instance.tick.return_value = ("SUCCESS", MapsNavResponse(reasoning="r", action="zoom", target_id="2"))
        status, job = nav_state.tick(job, context)
        assert status == "MAPS_NAV"
        
        # 3. MAPS_NAV (Select return_statement)
        mock_instance.tick.return_value = ("SUCCESS", MapsNavResponse(reasoning="r", action="select", target_id="0"))
        status, job = nav_state.tick(job, context)
        assert status == "MAPS_THINK"
        
        # 4. MAPS_THINK (Draft fix)
        mock_instance.tick.return_value = ("SUCCESS", MapsThinkResponse(reasoning="r", action="fix", draft_code="    return a * b"))
        status, job = think_state.tick(job, context)
        assert status == "MAPS_SURGEON"
        
        # 5. MAPS_SURGEON (Format JSON)
        mock_instance.tick.return_value = ("SUCCESS", MapsSurgeonResponse(reasoning="r", action="replace", code="    return a * b"))
        status, job = surgeon_state.tick(job, context)
        assert status == "SYNTAX_GATE"
        
        # 6. SYNTAX_GATE
        status, job = syntax_gate.tick(job, context)
        assert status == "ACTUATE"
        
        # 7. ACTUATE
        status, job = actuate.tick(job, context)
        assert status == "SENSE"

    # Verify Disk Change
    with open(temp_python_file, "r") as f:
        new_content = f.read()
    assert "return a * b" in new_content
    assert "return a + b" not in new_content
    assert "def calculate(a, b):" in new_content

if __name__ == "__main__":
    pytest.main([__file__])
