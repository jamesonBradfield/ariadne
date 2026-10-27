import os
import json
import tempfile
import pytest

# Import from the plugin location
import sys
sys.path.insert(0, "/home/jamesontb/.hermes/plugins/ariadne-compactor")
from __init__ import AriadneAmnesiacEngine


def test_plugin_init():
    engine = AriadneAmnesiacEngine(context_length=100000, threshold_pct=0.8)
    assert engine.name == "ariadne"
    assert engine.context_length == 100000
    assert engine.threshold_tokens == 80000
    assert engine.threshold_percent == 0.8
    assert engine.get_status()["threshold_tokens"] == 80000


def test_tool_schemas():
    engine = AriadneAmnesiacEngine()
    schemas = engine.get_tool_schemas()
    names = {s["name"] for s in schemas}
    assert "ariadne_skeletonize" in names
    assert "ariadne_track_symbols" in names
    assert "ariadne_ast_drill" in names
    assert "ariadne_actuate_splice" in names


def test_actuate_splice_replace():
    engine = AriadneAmnesiacEngine()
    with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
        f.write("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
        f_path = f.name

    try:
        # Track foo
        engine.tracked_nodes = [{
            "filepath": f_path,
            "symbol": "foo",
            "start_byte": 0,
            "end_byte": 23,
            "node_type": "function_definition"
        }]

        # Replace foo
        new_code = "def foo():\n    return 42\n"
        res = engine.handle_tool_call("ariadne_actuate_splice", {
            "action": "replace",
            "new_code": new_code
        })
        assert res == "ACTUATED_AND_FLUSHED"
        assert len(engine.tracked_nodes) == 0

        with open(f_path, "r") as f:
            content = f.read()
        assert "return 42" in content
        assert "def bar():" in content
    finally:
        os.remove(f_path)


def test_actuate_splice_insert_after():
    engine = AriadneAmnesiacEngine()
    with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
        f.write("def foo():\n    return 1\n")
        f_path = f.name

    try:
        # Track foo
        engine.tracked_nodes = [{
            "filepath": f_path,
            "symbol": "foo",
            "start_byte": 0,
            "end_byte": 23,
            "node_type": "function_definition"
        }]

        # Insert after foo
        new_code = "\ndef bar():\n    return 2\n"
        res = engine.handle_tool_call("ariadne_actuate_splice", {
            "action": "insert_after",
            "new_code": new_code
        })
        assert res == "ACTUATED_AND_FLUSHED"

        with open(f_path, "r") as f:
            content = f.read()
        assert "def foo():" in content
        assert "def bar():" in content
    finally:
        os.remove(f_path)


def test_actuate_splice_insert_before():
    engine = AriadneAmnesiacEngine()
    with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
        f.write("def bar():\n    return 2\n")
        f_path = f.name

    try:
        # Track bar
        engine.tracked_nodes = [{
            "filepath": f_path,
            "symbol": "bar",
            "start_byte": 0,
            "end_byte": 23,
            "node_type": "function_definition"
        }]

        # Insert before bar
        new_code = "def foo():\n    return 1\n\n"
        res = engine.handle_tool_call("ariadne_actuate_splice", {
            "action": "insert_before",
            "new_code": new_code
        })
        assert res == "ACTUATED_AND_FLUSHED"

        with open(f_path, "r") as f:
            content = f.read()
        assert content.startswith("def foo():")
        assert "def bar():" in content
    finally:
        os.remove(f_path)


def test_actuate_splice_multi_node_offset_shift():
    engine = AriadneAmnesiacEngine()
    with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
        # foo: 0 to 24 (24 bytes)
        # bar: 25 to 49 (24 bytes)
        f.write("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
        f_path = f.name

    try:
        # Pre-track both foo and bar
        engine.tracked_nodes = [
            {"filepath": f_path, "symbol": "foo", "start_byte": 0, "end_byte": 23, "node_type": "function_definition"},
            {"filepath": f_path, "symbol": "bar", "start_byte": 25, "end_byte": 49, "node_type": "function_definition"}
        ]

        # Splice foo with longer code (adds 20 bytes)
        longer_foo = "def foo():\n    # very long comment\n    return 1\n"
        res = engine.handle_tool_call("ariadne_actuate_splice", {
            "action": "replace",
            "new_code": longer_foo
        })
        assert res == "ACTUATED_AND_FLUSHED"

        # Check that bar's byte offsets shifted correctly in the queue!
        assert len(engine.tracked_nodes) == 1
        bar_node = engine.tracked_nodes[0]
        assert bar_node["symbol"] == "bar"
        delta = len(longer_foo.encode("utf-8")) - 23
        assert bar_node["start_byte"] == 25 + delta
        assert bar_node["end_byte"] == 49 + delta

        # Now splice bar
        res = engine.handle_tool_call("ariadne_actuate_splice", {
            "action": "replace",
            "new_code": "def bar():\n    return 999\n"
        })
        assert res == "ACTUATED_AND_FLUSHED"

        with open(f_path, "r") as f:
            content = f.read()
        assert "return 1" in content
        assert "return 999" in content
    finally:
        os.remove(f_path)


def test_fence_rejection():
    engine = AriadneAmnesiacEngine()
    engine.tracked_nodes = [{"filepath": "fake.py", "start_byte": 0, "end_byte": 10}]
    res = engine.handle_tool_call("ariadne_actuate_splice", {
        "action": "replace",
        "new_code": "```python\nprint(1)\n```"
    })
    data = json.loads(res)
    assert data["status"] == "SYNTAX_GATE_FAILED"
    assert "markdown fences" in data["error"]


def test_select_context_empty_queue():
    engine = AriadneAmnesiacEngine()
    messages = [
        {"role": "system", "content": "base system"},
        {"role": "user", "content": "fix bug"},
    ]
    selected = engine.select_context(messages)
    assert len(selected) >= 2
    assert selected[0]["content"] == "base system"
    # Amnesic system prompt injected
    assert "Objective:" in selected[1]["content"]
    assert "Active Queue: 1 of 0 tracked nodes" in selected[1]["content"]


def test_checkpoint_save_and_restore():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["HERMES_HOME"] = tmpdir
        try:
            # Session 1: track nodes
            engine1 = AriadneAmnesiacEngine()
            engine1.on_session_start("session_abc", intent="repair entity armor")
            engine1.tracked_nodes = [
                {"filepath": "src/lib.rs", "symbol": "foo", "start_byte": 10, "end_byte": 50, "node_type": "fn"}
            ]
            engine1._completed_edits = [{"filepath": "src/lib.rs", "action": "replace"}]
            engine1.save_checkpoint()

            # Session 2: simulate crash recovery / resume on same session_id
            engine2 = AriadneAmnesiacEngine()
            engine2.on_session_start("session_abc")
            assert engine2.intent == "repair entity armor"
            assert len(engine2.tracked_nodes) == 1
            assert engine2.tracked_nodes[0]["symbol"] == "foo"
            assert len(engine2._completed_edits) == 1

            # Session reset cleans checkpoint
            engine2.on_session_reset()
            assert len(engine2.tracked_nodes) == 0
            ckpt_path = engine2._checkpoint_path()
            assert not os.path.exists(ckpt_path)
        finally:
            os.environ.pop("HERMES_HOME", None)


def test_turn_awareness_and_clef_verification():
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["HERMES_HOME"] = tmpdir
        try:
            engine = AriadneAmnesiacEngine()
            engine.on_session_start("session_turns_isolated", intent="expand tree-sitter grammars")
            assert engine.turn_count == 0

            mock_eval = {
                "objective_satisfied": True,
                "completion_confidence": 0.94,
                "is_stuck": False,
                "recommended_action": "kanban_complete",
            }

            # Simulate 3 turns
            engine.on_turn_complete([{"role": "user", "content": "step 1"}])
            assert engine.turn_count == 1
            engine.on_turn_complete([{"role": "user", "content": "step 2"}])
            assert engine.turn_count == 2

            # On turn 3 (warmup reached), mock QueryClef returning completion
            with patch("ariadne.primitives.QueryClef.tick", return_value=("SUCCESS", mock_eval)):
                engine.on_turn_complete([{"role": "user", "content": "step 3"}])
                assert engine.turn_count == 3
                assert engine.directive_nudge is not None
                assert "OBJECTIVE VERIFIED COMPLETE" in engine.directive_nudge

            # Verify directive nudge is prepended to amnesic view
            view = engine._render_amnesic_view()
            assert "[CRITICAL DIRECTIVE: OBJECTIVE VERIFIED COMPLETE]" in view
            assert "kanban_complete" in view
            assert f"Turn Progress: 3/{engine.estimated_turns}" in view
        finally:
            os.environ.pop("HERMES_HOME", None)


def test_agentic_planning_escalation():
    engine = AriadneAmnesiacEngine()
    engine.turn_count = 30
    engine.max_turn_budget = 30
    engine.escalated_to_planning = True

    messages = [
        {"role": "system", "content": "system instruction"},
        {"role": "user", "content": "step 1"},
        {"role": "assistant", "content": "tool 1"},
        {"role": "tool", "content": "output 1"},
        {"role": "user", "content": "step 2"},
    ]

    selected = engine.select_context(messages)
    # Escalated turn pauses compaction and injects planning frame
    assert len(selected) == len(messages) + 1
    assert "SURGEON ESCALATION: AGENTIC PLANNING TURN" in selected[1]["content"]
    assert engine.escalated_to_planning is False


