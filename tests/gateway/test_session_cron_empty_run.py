"""A cron admission whose run never reaches the agent must not leave an open, untitled row."""
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest


async def _execute(tmp_path, monkeypatch, *, write_message):
    from cron import scheduler
    from cron.executions import create_execution, mark_execution_running
    from gateway import run, session_cron
    from gateway.session_authority import LiveSession, SessionAuthority
    from gateway.session_contract import SessionRef
    from hermes_state import SessionDB
    from hermes_state_runtime import admit_session_input, begin_runtime_epoch, claim_session_input

    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    execution = create_execution('job', source='builtin', scheduled_instant='2026-10-08T09:00:00')
    mark_execution_running(execution['id'])
    db = SessionDB(tmp_path / 'state.db')
    db.create_session('s', source='cron')
    authority = SessionAuthority(SimpleNamespace(_draining=False), profile_id='p', instance_id='test', db=db,
                                 epoch=begin_runtime_epoch(db, instance_id='test'))
    authority.sessions['s'] = LiveSession(SimpleNamespace(platform=None, user_id='cron-owner'), 'route')
    monkeypatch.setattr(run, '_profile_runtime_scope', lambda home: nullcontext())

    def run_job(job, *, extra_prompt, execution_id, cancel_event):
        if write_message:
            db.append_message('s', 'assistant', 'report')
            return (True, 'doc', 'report', None)
        return (True, 'doc', '[SILENT]', None)  # a monitor no_change tick
    monkeypatch.setattr(scheduler, 'run_job', run_job)
    request_id = 'cron:job:' + execution['id']
    admit_session_input(db, epoch=authority.epoch, principal_id='cron-owner', session_id='s',
                        request_id=request_id, payload={'text': ''})
    row = claim_session_input(db, epoch=authority.epoch, session_id='s')
    policy = SimpleNamespace(request_json=json.dumps({
        'extra_prompt': None, 'request_id': request_id, 'cron_job': {'id': 'job', 'name': 'Job'}}))
    await session_cron.execute(authority, SessionRef('p', 's'), row, policy)
    return db


@pytest.mark.asyncio
async def test_gated_run_ends_and_hides_its_empty_session(tmp_path, monkeypatch):
    db = await _execute(tmp_path, monkeypatch, write_message=False)
    row = db.get_session('s')
    assert row['ended_at'] is not None and row['hidden']
    assert 's' not in {s['id'] for s in db.list_sessions_rich(limit=50)}


@pytest.mark.asyncio
async def test_agent_run_keeps_its_session_visible(tmp_path, monkeypatch):
    db = await _execute(tmp_path, monkeypatch, write_message=True)
    row = db.get_session('s')
    assert not row['hidden'] and row['end_reason'] != 'cron_no_agent_run'
    assert 's' in {s['id'] for s in db.list_sessions_rich(limit=50)}
