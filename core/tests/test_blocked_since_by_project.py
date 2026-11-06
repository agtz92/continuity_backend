"""``blocked_since_by_project`` = ``project_blocked_since`` por proyecto."""

import datetime as dt
import uuid
from types import SimpleNamespace as NS

from core.services import cooling


def _t(project_id, done=False):
    return NS(id=uuid.uuid4(), project_id=project_id, done=done)


def test_matches_per_project_version():
    now = dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc)
    p_open = NS(id=uuid.uuid4(), status="active")
    p_closed = NS(id=uuid.uuid4(), status="killed")
    p_free = NS(id=uuid.uuid4(), status="active")
    a, b, c, d = _t(p_open.id), _t(p_open.id), _t(p_closed.id), _t(p_open.id, done=True)
    loose = _t(None)
    blocker_map = {
        a.id: [NS(created=now - dt.timedelta(days=2))],
        b.id: [NS(created=now - dt.timedelta(days=5))],
        c.id: [NS(created=now - dt.timedelta(days=9))],
        d.id: [NS(created=now - dt.timedelta(days=20))],  # hecha: no cuenta
        loose.id: [NS(created=now)],
    }
    tasks = [a, b, c, d, loose]
    projects = [p_open, p_closed, p_free]

    got = cooling.blocked_since_by_project(projects, tasks, blocker_map)
    expected = {
        p.id: cooling.project_blocked_since(p.id, tasks, blocker_map, status=p.status)
        for p in projects
    }
    assert got == expected
    assert got[p_closed.id] is None and got[p_free.id] is None
