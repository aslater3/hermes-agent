"""A typed reply lifts a judge ``needs_input`` goal pause; machinery wakes never do."""
import asyncio
from unittest.mock import patch

import pytest

from gateway.config import Platform
from gateway.platforms.event import MessageEvent
from gateway.run_goals import GatewayGoalsMixin
from gateway.session import SessionSource


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


def _source():
    return SessionSource(platform=Platform.LOCAL, chat_id="chat-1")


def test_only_typed_turns_count_as_user_input():
    real = MessageEvent(text="done, it's power-cycled", source=_source())
    internal = MessageEvent(text="[process finished]", source=_source(), internal=True)
    heartbeat = MessageEvent(text="heartbeat", source=_source())
    heartbeat._heartbeat_session_id = "sid"
    assert GatewayGoalsMixin._is_real_user_turn(real) is True
    assert GatewayGoalsMixin._is_real_user_turn(internal) is False
    assert GatewayGoalsMixin._is_real_user_turn(heartbeat) is False
    assert GatewayGoalsMixin._is_real_user_turn(None) is False


class _Runner(GatewayGoalsMixin):
    def __init__(self):
        self.notices = []

    async def _post_turn_manager(self, session_entry, label, module, load):
        from hermes_cli.goals import GoalManager
        return GoalManager(session_id=session_entry.session_id)

    async def _defer_goal_status_notice_after_delivery(self, source, message):
        self.notices.append(message)


class _Entry:
    session_id = "gw-ni"


def _pause_for_input():
    from hermes_cli.goals import GoalManager
    mgr = GoalManager(session_id="gw-ni")
    mgr.set("flash the device")
    with patch("hermes_cli.goals.judge_goal",
               return_value=("needs_input", "power-cycle the device", False, None, False)):
        mgr.evaluate_after_turn("Please power-cycle it.")
    return mgr


def test_reply_resumes_needs_input_goal_and_announces_it(hermes_home):
    _pause_for_input()
    runner = _Runner()
    asyncio.run(runner._resume_goal_after_user_input(_Entry(), _source()))

    from hermes_cli.goals import load_goal
    state = load_goal("gw-ni")
    assert state.status == "active" and state.turns_used == 1
    assert runner.notices == ["▶ Goal resumed after your reply."]


def test_reply_leaves_a_user_pause_alone(hermes_home):
    mgr = _pause_for_input()
    mgr.pause("user-paused")
    runner = _Runner()
    asyncio.run(runner._resume_goal_after_user_input(_Entry(), _source()))

    from hermes_cli.goals import load_goal
    assert load_goal("gw-ni").status == "paused"
    assert runner.notices == []
