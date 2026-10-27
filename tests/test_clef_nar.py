import pytest
from unittest.mock import patch, MagicMock
import json
from ariadne.primitives import QueryClef

def test_query_clef_verify_objective_native_clef():
    qc = QueryClef(api_base="https://clef.cloudflare.com/v1")
    
    mock_response_data = {
        "success": True,
        "result": {
            "objective_status": {
                "in_progress": 0.05,
                "completed": 0.92,
                "blocked_or_stuck": 0.03
            },
            "recommended_action": {
                "continue_splice": 0.08,
                "kanban_complete": 0.91,
                "escalate_to_planner": 0.01
            },
            "remaining_turns_bucket": {
                "0": 0.89,
                "1-5": 0.08,
                "6-15": 0.03,
                "15+": 0.00
            }
        }
    }
    
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    
    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, eval_result = qc.tick({
            "mode": "verify_objective",
            "state": "Objective: test grammar expansion\nCompleted Slices: 3"
        })
        
        assert status == "SUCCESS"
        assert eval_result["objective_satisfied"] is True
        assert eval_result["completion_confidence"] == pytest.approx(0.92, rel=1e-2)
        assert eval_result["recommended_action"] == "kanban_complete"
        assert eval_result["is_stuck"] is False

def test_query_clef_verify_objective_in_progress():
    qc = QueryClef(api_base="https://clef.cloudflare.com/v1")
    
    mock_response_data = {
        "success": True,
        "result": {
            "objective_status": {
                "in_progress": 0.85,
                "completed": 0.10,
                "blocked_or_stuck": 0.05
            },
            "recommended_action": {
                "continue_splice": 0.88,
                "kanban_complete": 0.05,
                "escalate_to_planner": 0.07
            },
            "remaining_turns_bucket": {
                "0": 0.02,
                "1-5": 0.70,
                "6-15": 0.25,
                "15+": 0.03
            }
        }
    }
    
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    
    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, eval_result = qc.tick({
            "mode": "verify_objective",
            "state": "Objective: in progress..."
        })
        
        assert status == "SUCCESS"
        assert eval_result["objective_satisfied"] is False
        assert eval_result["recommended_action"] == "continue_splice"
        assert eval_result["is_stuck"] is False

def test_query_clef_estimate_turns():
    qc = QueryClef(api_base="https://clef.cloudflare.com/v1")
    
    mock_response_data = {
        "success": True,
        "result": {
            "remaining_turns_bucket": {
                "1-5": 0.1,
                "6-15": 0.85,
                "15-30": 0.05,
                "30+": 0.0
            }
        }
    }
    
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    
    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, eval_result = qc.tick({
            "mode": "estimate_turns",
            "state": "Objective: Add Go, C++, Bash grammars"
        })
        
        assert status == "SUCCESS"
        assert eval_result["estimated_turns"] == 15
        assert eval_result["max_budget"] == 30

# --- Deterministic no-endpoint fallback (no network mocking: api_base forced empty) ---

def test_query_clef_deterministic_fallback_stuck():
    qc = QueryClef()
    qc.api_base = ""  # simulate endpoint disabled
    status, res = qc.tick({
        "mode": "verify_objective",
        "state": "Attempt 3: splice raised ERROR, test still failed"
    })
    assert status == "SUCCESS"
    assert res["objective_satisfied"] is False
    assert res["is_stuck"] is True
    assert res["recommended_action"] == "escalate_to_planner"

def test_query_clef_deterministic_fallback_in_progress():
    qc = QueryClef()
    qc.api_base = ""
    status, res = qc.tick({
        "mode": "verify_objective",
        "state": "Objective: add Go grammar; step 2 of 5 in progress"
    })
    assert status == "SUCCESS"
    assert res["objective_satisfied"] is False
    assert res["is_stuck"] is False
    assert res["recommended_action"] == "continue_splice"

def test_query_clef_deterministic_fallback_estimate_turns():
    qc = QueryClef()
    qc.api_base = ""
    status, res = qc.tick({"mode": "estimate_turns", "state": "anything"})
    assert status == "SUCCESS"
    assert res["estimated_turns"] == 15
    assert res["max_budget"] == 30

def test_query_clef_deterministic_fallback_aperture():
    qc = QueryClef()
    qc.api_base = ""
    status, res = qc.tick({
        "mode": "aperture",
        "state": "broken node foo",
        "questions": {"need_call_sites": {"type": "bool"}, "need_lsp_hover": {"type": "bool"}}
    })
    assert status == "SUCCESS"
    assert res["surgical_action"]["choice"] == "replace"
    assert res["need_call_sites"]["probability"] == 0.95
    assert res["need_lsp_hover"]["probability"] == 0.05
