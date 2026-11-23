"""Judge ``needs_input`` verdict: pause, then resume on the user's reply (not a terminal block)."""
from unittest.mock import patch

import pytest


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME so state_meta writes never touch the real one."""
    from pathlib import Path

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals

    goals._DB_CACHE.clear()
    yield home
    goals._DB_CACHE.clear()


def _judge(verdict, reason="r"):
    return patch("hermes_cli.goals.judge_goal", return_value=(verdict, reason, False, None, False))


@pytest.mark.parametrize("raw,expected", [
    ('{"verdict": "needs_input", "reason": "power-cycle the device"}', "needs_input"),
    ('{"verdict": "needs-input", "reason": "x"}', "needs_input"),
    ('{"verdict": "NEEDS_INPUT", "reason": "x"}', "needs_input"),
    ('{"verdict": "blocked", "reason": "x"}', "blocked"),
])
def test_parser_accepts_needs_input(raw, expected):
    from hermes_cli.goals import _parse_judge_response
    verdict, _reason, parse_failed, wd = _parse_judge_response(raw)
    assert (verdict, parse_failed, wd) == (expected, False, None)


def test_needs_input_pauses_resumably_and_reply_resumes_with_budget(hermes_home):
    from hermes_cli.goals import GoalManager, load_goal

    mgr = GoalManager(session_id="ni-sid")
    mgr.set("flash the device")
    with _judge("needs_input", "the user must power-cycle the device"):
        decision = mgr.evaluate_after_turn("Please power-cycle the device, then tell me.")

    assert decision["status"] == "paused"
    assert decision["verdict"] == "needs_input"
    assert decision["should_continue"] is False
    assert "waiting for your input" in decision["message"]
    assert "resumes automatically" in decision["message"]
    persisted = load_goal("ni-sid")
    assert persisted.status == "paused" and persisted.resume_on_user_message is True
    assert persisted.paused_reason.startswith("awaiting user input:")

    # A fresh manager (another process) sees it awaiting input and the reply lifts it.
    other = GoalManager(session_id="ni-sid")
    assert other.is_awaiting_input()
    assert other.resume_after_user_input() is True
    resumed = load_goal("ni-sid")
    assert resumed.status == "active"
    assert resumed.resume_on_user_message is False
    assert resumed.turns_used == 1          # budget kept, not reset
    assert other.resume_after_user_input() is False   # idempotent

    with _judge("continue", "flashing in progress"):
        decision = other.evaluate_after_turn("Device is back; flashing now.")
    assert decision["should_continue"] is True
    assert load_goal("ni-sid").turns_used == 2


@pytest.mark.parametrize("pause", ["blocked", "user", "budget"])
def test_other_pauses_are_not_lifted_by_a_reply(hermes_home, pause):
    from hermes_cli.goals import GoalManager

    mgr = GoalManager(session_id=f"np-{pause}")
    mgr.set("goal", max_turns=1)
    if pause == "blocked":
        with _judge("blocked", "impossible"):
            mgr.evaluate_after_turn("cannot be done")
    elif pause == "user":
        mgr.pause()
    else:
        with _judge("continue", "more"):
            mgr.evaluate_after_turn("partial")
    assert mgr.state.status == "paused"
    assert not mgr.is_awaiting_input()
    assert mgr.resume_after_user_input() is False
    assert mgr.state.status == "paused"


def test_explicit_pause_clears_auto_resume(hermes_home):
    from hermes_cli.goals import GoalManager

    mgr = GoalManager(session_id="ni-explicit")
    mgr.set("goal")
    with _judge("needs_input", "pick a tag policy"):
        mgr.evaluate_after_turn("Which tag policy?")
    mgr.pause("user-paused")
    assert mgr.resume_after_user_input() is False


def test_state_without_field_loads_unchanged():
    from hermes_cli.goals import GoalState
    s = GoalState.from_json('{"goal": "g", "status": "paused", "paused_reason": "judged unachievable: x"}')
    assert s.resume_on_user_message is False
