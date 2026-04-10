import pytest
import os
import tempfile
import json
from unittest.mock import MagicMock, patch
from ariadne.states import MAPS_NAV, MAPS_THINK, MAPS_SURGEON
from ariadne.payloads import JobPayload, MapsNavResponse, MapsThinkResponse, MapsSurgeonResponse
from ariadne.profiles.rust_profile import RustProfile

@pytest.fixture
def temp_rust_file():
    content = b"fn main() {\n    let x = 1;\n    let y = 2;\n}\n"
    with tempfile.NamedTemporaryFile(suffix=".rs", delete=False) as f:
        f.write(content)
        path = f.name
    yield path
    if os.path.exists(path):
        os.remove(path)

def test_maps_comprehensive_session(temp_rust_file):
    # Setup mock config manager
    config_manager = MagicMock()
    config_manager.get_model_info.return_value = {
        "model": "mock-model",
        "api_base": "mock-api",
        "params": {}
    }
    config_manager.config = {
        "states": {
            "MAPS_NAV": {"system_prompt": "sys", "user_prompt_template": "user", "post_process": "extract_json"},
            "MAPS_THINK": {"system_prompt": "sys", "user_prompt_template": "user", "post_process": "extract_json"},
            "MAPS_SURGEON": {"system_prompt": "sys", "user_prompt_template": "user", "post_process": "extract_json"}
        }
    }
    config_manager.render_prompt.side_effect = lambda template, vars: template

    # Setup profile
    profile = RustProfile()

    # Instantiate states
    nav_state = MAPS_NAV(config_manager, profile)
    think_state = MAPS_THINK(config_manager, profile)
    surgeon_state = MAPS_SURGEON(config_manager, profile)

    # Setup JobPayload
    with open(temp_rust_file, "rb") as f:
        content = f.read()
        main_start = content.find(b"fn main")
        main_end = content.find(b"}", main_start) + 1

    job = JobPayload(
        intent="refactor main",
        target_files=[temp_rust_file],
        maps_state={"current_step_index": 0, "steps": [{"symbol": "main"}]},
        extracted_nodes=[{
            "filepath": temp_rust_file,
            "symbol": "main",
            "start_byte": main_start,
            "end_byte": main_end,
            "node_string": content[main_start:main_end].decode("utf-8"),
            "node_type": "function_item"
        }]
    )

    # Mock QueryLLM to simulate actions
    with patch("ariadne.states.QueryLLM") as MockLLM:
        mock_instance = MockLLM.return_value
        
        # 1. NAV: ZOOM into block
        mock_instance.tick.return_value = ("SUCCESS", MapsNavResponse(reasoning="r", action="zoom", target_id="2"))
        status, _ = nav_state.tick(job)
        assert status == "MAPS_NAV"
        assert len(job.maps_state["navigation_stack"]) == 2
        
        # 2. NAV: ZOOM into first let
        mock_instance.tick.return_value = ("SUCCESS", MapsNavResponse(reasoning="r", action="zoom", target_id="0"))
        status, _ = nav_state.tick(job)
        assert len(job.maps_state["navigation_stack"]) == 3
        
        # 3. NAV: UP back to block
        mock_instance.tick.return_value = ("SUCCESS", MapsNavResponse(reasoning="r", action="up", target_id="2"))
        status, _ = nav_state.tick(job)
        assert len(job.maps_state["navigation_stack"]) == 2
        
        # 4. NAV: SELECT first let
        mock_instance.tick.return_value = ("SUCCESS", MapsNavResponse(reasoning="r", action="select", target_id="0"))
        status, _ = nav_state.tick(job)
        assert status == "MAPS_THINK"
        
        # 5. THINK: Draft fix
        mock_instance.tick.return_value = ("SUCCESS", MapsThinkResponse(reasoning="r", action="fix", draft_code="let x = 42;"))
        status, _ = think_state.tick(job)
        assert status == "MAPS_SURGEON"
        
        # 6. SURGEON: Format JSON
        mock_instance.tick.return_value = ("SUCCESS", MapsSurgeonResponse(reasoning="r", action="replace", code="let x = 42;"))
        status, _ = surgeon_state.tick(job)
        assert status == "SYNTAX_GATE"
        assert len(job.fixed_code["edits"]) == 1

if __name__ == "__main__":
    pytest.main([__file__])
