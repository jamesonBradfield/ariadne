import pytest
import os
import tempfile
from unittest.mock import MagicMock, patch
from ariadne.states import MAPS
from ariadne.payloads import JobPayload
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
            "MAPS": {
                "system_prompt": "sys",
                "user_prompt_template": "user",
                "post_process": "extract_json"
            }
        }
    }
    config_manager.render_prompt.side_effect = lambda template, vars: template

    # Setup profile
    profile = RustProfile()

    # Instantiate MAPS state
    maps_state = MAPS(config_manager, profile)

    # Setup JobPayload
    with open(temp_rust_file, "rb") as f:
        content = f.read()
        main_start = content.find(b"fn main")
        main_end = content.find(b"}", main_start) + 1

    job = JobPayload(
        intent="refactor main",
        target_files=[temp_rust_file],
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
        
        # 1. ZOOM into block (target_id 2 in function_item)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "zoom", "target_id": 2})
        status, _ = maps_state.tick(job)
        assert status == "MAPS"
        assert len(job.maps_state["navigation_stack"]) == 2
        
        # 2. ZOOM into first let_declaration (target_id 0 in block) to test 'up' later
        mock_instance.tick.return_value = ("SUCCESS", {"action": "zoom", "target_id": 0})
        status, _ = maps_state.tick(job)
        assert len(job.maps_state["navigation_stack"]) == 3
        
        # 3. UP back to block
        mock_instance.tick.return_value = ("SUCCESS", {"action": "up"})
        status, _ = maps_state.tick(job)
        assert len(job.maps_state["navigation_stack"]) == 2
        
        # 4. INSERT_BEFORE first let (target_id 0 in block)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "insert_before", "target_id": 0, "code": "// comment\n    "})
        status, _ = maps_state.tick(job)
        assert status == "MAPS"
        assert len(job.fixed_code["edits"]) == 1
        assert job.fixed_code["edits"][-1]["new_code"] == "// comment\n    "
        
        # 5. INSERT_AFTER second let (target_id 1 in block)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "insert_after", "target_id": 1, "code": "\n    println!(\"done\");"})
        status, _ = maps_state.tick(job)
        assert status == "MAPS"
        assert len(job.fixed_code["edits"]) == 2
        
        # 6. DELETE first let (target_id 0 in block)
        mock_instance.tick.return_value = ("SUCCESS", {"action": "delete", "target_id": 0})
        status, _ = maps_state.tick(job)
        assert status == "MAPS"
        assert len(job.fixed_code["edits"]) == 3
        assert job.fixed_code["edits"][-1]["new_code"] == ""
        
        # 7. DONE
        mock_instance.tick.return_value = ("SUCCESS", {"action": "done"})
        status, _ = maps_state.tick(job)
        assert status == "SYNTAX_GATE"

def test_maps_error_handling(temp_rust_file):
    # Setup mock config manager
    config_manager = MagicMock()
    config_manager.get_model_info.return_value = {
        "model": "mock-model",
        "api_base": "mock-api",
        "params": {}
    }
    config_manager.config = {
        "states": {
            "MAPS": {
                "system_prompt": "sys",
                "user_prompt_template": "user",
                "post_process": "extract_json"
            }
        }
    }
    config_manager.render_prompt.side_effect = lambda template, vars: template

    # Setup profile
    profile = RustProfile()

    # Instantiate MAPS state
    maps_state = MAPS(config_manager, profile)

    # Setup JobPayload
    job = JobPayload(
        intent="fix",
        target_files=[temp_rust_file],
        extracted_nodes=[{
            "filepath": temp_rust_file,
            "symbol": "main",
            "start_byte": 0,
            "end_byte": 10,
            "node_string": "fn main()",
            "node_type": "function_item"
        }]
    )

    # Mock QueryLLM to simulate invalid action
    with patch("ariadne.states.QueryLLM") as MockLLM:
        mock_instance = MockLLM.return_value
        
        # Invalid target_id for zoom
        mock_instance.tick.return_value = ("SUCCESS", {"action": "zoom", "target_id": 999})
        status, _ = maps_state.tick(job)
        assert status == "MAPS"
        assert "Invalid target_id" in job.llm_feedback

if __name__ == "__main__":
    pytest.main([__file__])
