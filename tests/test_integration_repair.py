import pytest
import os
import tempfile
from unittest.mock import MagicMock, patch
from ariadne.states import (
    MAPS_NAV,
    MAPS_THINK,
    MAPS_SURGEON,
    SYNTAX_GATE,
    ACTUATE,
)
from ariadne.payloads import (
    JobPayload,
    MapsThinkResponse,
    MapsSurgeonResponse,
)


class MockRustProfile:
    def get_language_ptr(self):
        # Import tree-sitter-rust and call its language() function
        try:
            import tree_sitter_rust

            return tree_sitter_rust.language()
        except ImportError:
            # Fallback for testing without the package
            from tree_sitter import Language

            return Language("tree-sitter-rust")

    def get_skeleton(self, filepath):
        return "SUCCESS", "fn main() {\n    let x = 1;\n}"

    def get_available_symbols(self, target_files, context):
        return ["main"]

    def find_symbol(self, filepath, symbol, context):
        # Simulate finding the main function
        with open(filepath, "rb") as f:
            content = f.read()
            main_start = content.find(b"fn main")
            main_end = content.find(b"}", main_start) + 1
            return (
                "SUCCESS",
                [
                    {
                        "code": content[main_start:main_end].decode("utf-8"),
                        "start_byte": main_start,
                        "end_byte": main_end,
                        "node_type": "function_item",
                    }
                ],
            )


profile = MockRustProfile()


@pytest.fixture
def temp_rust_file():
    content = b"fn main() {\n    let x = 1;\n}\n"
    with tempfile.NamedTemporaryFile(suffix=".rs", delete=False) as f:
        f.write(content)
        path = f.name
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_rust_batch_processing(temp_rust_file):
    # Setup mock config manager
    config_manager = MagicMock()
    config_manager.get_model_info.return_value = {
        "model": "mock-model",
        "api_base": "mock-api",
        "params": {},
    }
    config_manager.config = {
        "states": {
            "MAPS_NAV": {
                "system_prompt": "sys",
                "user_prompt_template": "user",
            },
            "MAPS_THINK": {
                "system_prompt": "sys",
                "user_prompt_template": "user",
            },
            "MAPS_SURGEON": {
                "system_prompt": "sys",
                "user_prompt_template": "user",
            },
        }
    }
    config_manager.render_prompt.side_effect = lambda template, vars: template

    # Setup profile
    from ariadne.core import EngineContext

    context = EngineContext(
        "MAPS_NAV",
        intent="fix rust main",
        target_files=[temp_rust_file],
        profile=profile,
    )

    # Instantiate states
    nav_state = MAPS_NAV(config_manager, profile)
    think_state = MAPS_THINK(config_manager, profile)
    surgeon_state = MAPS_SURGEON(config_manager, profile)
    syntax_gate = SYNTAX_GATE(profile)
    actuate = ACTUATE()

    # Initial Job with plan
    with open(temp_rust_file, "rb") as f:
        content = f.read()
        main_start = content.find(b"fn main")
        main_end = content.find(b"}", main_start) + 1

    job = JobPayload(
        intent="fix rust main",
        target_files=[temp_rust_file],
        maps_state={
            "current_step_index": 0,
            "steps": [{"symbol": "main"}],
            "id_map": {
                "function_item": (main_start, main_end)
            },  # Key is node_type, not symbol
        },
    )

    # Mock QueryLLM to simulate actions
    with patch("ariadne.states.QueryLLM") as MockLLM:
        mock_instance = MockLLM.return_value

        # 1. MAPS_NAV: Discover main function
        status, job = nav_state.tick(job, context)
        assert status == "MAPS_NAV"
        assert len(job.tracked_nodes) == 1
        assert job.tracked_nodes[0]["symbol"] == "main"

        # 2. MAPS_THINK: Draft fix
        mock_instance.tick.return_value = (
            "SUCCESS",
            MapsThinkResponse(
                reasoning="r",
                action="fix",
                draft_code='fn main() {\n    println!("Hello, world!");\n}',
            ),
        )
        status, job = think_state.tick(job, context)
        assert status == "MAPS_SURGEON"

        # 3. MAPS_SURGEON: Format JSON
        mock_instance.tick.return_value = (
            "SUCCESS",
            MapsSurgeonResponse(
                reasoning="r",
                action="replace",
                code='fn main() {\n    println!("Hello, world!");\n}',
            ),
        )
        status, job = surgeon_state.tick(job, context)
        assert status == "SYNTAX_GATE"
        assert len(job.fixed_code["edits"]) == 1

        # 4. SYNTAX_GATE
        status, job = syntax_gate.tick(job, context)
        assert status == "ACTUATE"

        # 5. ACTUATE
        status, job = actuate.tick(job, context)
        assert status == "MAPS_NAV"
        assert len(job.tracked_nodes) == 0  # Node was edited and removed

    # Verify Disk Change
    with open(temp_rust_file, "r") as f:
        new_content = f.read()
    assert "fn main() {" in new_content
    assert 'println!("Hello, world!");' in new_content
    assert "let x = 1;" not in new_content


def test_maps_batch_processing(temp_rust_file):
    # Setup mock config manager
    config_manager = MagicMock()
    config_manager.get_model_info.return_value = {
        "model": "mock-model",
        "api_base": "mock-api",
        "params": {},
    }
    config_manager.config = {
        "states": {
            "MAPS_NAV": {
                "system_prompt": "sys",
                "user_prompt_template": "user",
            },
            "MAPS_THINK": {
                "system_prompt": "sys",
                "user_prompt_template": "user",
            },
            "MAPS_SURGEON": {
                "system_prompt": "sys",
                "user_prompt_template": "user",
            },
        }
    }
    config_manager.render_prompt.side_effect = lambda template, vars: template

    # Setup profile
    from ariadne.core import EngineContext

    context = EngineContext(
        "MAPS_NAV",
        intent="refactor main",
        target_files=[temp_rust_file],
        profile=profile,
    )

    # Instantiate states
    nav_state = MAPS_NAV(config_manager, profile)
    think_state = MAPS_THINK(config_manager, profile)
    surgeon_state = MAPS_SURGEON(config_manager, profile)

    # Setup JobPayload with tracked nodes
    with open(temp_rust_file, "rb") as f:
        content = f.read()
        main_start = content.find(b"fn main")
        main_end = content.find(b"}", main_start) + 1

    job = JobPayload(
        intent="refactor main",
        target_files=[temp_rust_file],
        maps_state={
            "current_step_index": 0,
            "steps": [{"symbol": "main"}],
            "id_map": {"function_item": (main_start, main_end)},  # Key is node_type
        },
        tracked_nodes=[
            {
                "filepath": temp_rust_file,
                "symbol": "main",
                "start_byte": main_start,
                "end_byte": main_end,
                "node_string": content[main_start:main_end].decode("utf-8"),
                "node_type": "function_item",
            }
        ],
    )

    # Mock QueryLLM to simulate actions
    with patch("ariadne.states.QueryLLM") as MockLLM:
        mock_instance = MockLLM.return_value

        # 1. NAV: SELECT main function
        mock_instance.tick.return_value = (
            "SUCCESS",
            MapsThinkResponse(reasoning="r", action="fix", draft_code="let x = 42;"),
        )
        status, _ = think_state.tick(job, context)
        assert status == "MAPS_SURGEON"

        # 2. SURGEON: Format JSON
        mock_instance.tick.return_value = (
            "SUCCESS",
            MapsSurgeonResponse(reasoning="r", action="replace", code="let x = 42;"),
        )
        status, _ = surgeon_state.tick(job, context)
        assert status == "SYNTAX_GATE"
        assert len(job.fixed_code["edits"]) == 1


if __name__ == "__main__":
    pytest.main([__file__])
