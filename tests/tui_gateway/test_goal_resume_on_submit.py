"""prompt.submit's resume hook lifts only a judge ``needs_input`` pause and announces it."""
from unittest.mock import patch

import pytest


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    from pathlib import Path

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals

    goals._DB_CACHE.clear()
    yield home
    goals._DB_CACHE.clear()


def _goal(sid, verdict):
    from hermes_cli.goals import GoalManager
    mgr = GoalManager(session_id=sid)
    mgr.set("flash the device")
    with patch("hermes_cli.goals.judge_goal", return_value=(verdict, "power-cycle it", False, None, False)):
        mgr.evaluate_after_turn("Please power-cycle the device.")
    return mgr


@pytest.mark.parametrize("verdict,resumed", [("needs_input", True), ("blocked", False)])
def test_typed_reply_resumes_only_needs_input(hermes_home, monkeypatch, verdict, resumed):
    from hermes_cli.goals import load_goal
    from tui_gateway import server  # handler bodies are rebound onto server.py's globals

    _goal("tui-ni", verdict)
    emitted = []
    monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))
    server._resume_goal_awaiting_input("live-1", {"session_key": "tui-ni"})

    assert (load_goal("tui-ni").status == "active") is resumed
    assert emitted == ([("status.update", "live-1", {"kind": "goal", "text": "▶ Goal resumed after your reply."})]
                       if resumed else [])


def test_session_without_key_is_a_noop(hermes_home, monkeypatch):
    from tui_gateway import server
    monkeypatch.setattr(server, "_emit", lambda *args: pytest.fail("must not emit"))
    server._resume_goal_awaiting_input("live-1", {})
