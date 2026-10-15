"""Pagination + byte cap of the read tools.

Regression: the old 2 KB cap cut every list to 10 items with no way to get
the rest, so Loop listed 42 of 48 open tasks and claimed it was all 48.
"""

from __future__ import annotations

import json

import pytest

from core.assistant import tools
from core.assistant.tools import MAX_RESULT_BYTES, _json_default, _truncate_payload


def _size(payload) -> int:
    return len(json.dumps(payload, default=_json_default))


def _page_through(name, user_id, args):
    seen, offset, calls = [], 0, 0
    while offset is not None:
        out = tools.call(name, user_id, {**args, "offset": offset})
        assert "error" not in out, out
        assert _size(out) <= MAX_RESULT_BYTES
        seen.append(out)
        offset = out["next_offset"]
        calls += 1
        assert calls < 20, "pagination never ended"
    return seen


@pytest.mark.django_db
def test_list_tasks_paginates_all_48(user_a, make_project, make_task):
    p = make_project(user_a)
    for i in range(42):
        make_task(user_a, project=p, title=f"task {i:02d} " + "x" * 120)
    # The 6 that went missing in prod: no due date, no project.
    for i in range(6):
        make_task(user_a, title=f"loose {i}")
    make_task(user_a, title="done one", done=True)

    pages = _page_through("list_tasks", user_a, {"done": False, "limit": 50})

    ids = [t["id"] for page in pages for t in page["tasks"]]
    assert len(ids) == 48
    assert len(set(ids)) == 48
    assert all(page["total"] == 48 for page in pages)
    assert sum(page["returned"] for page in pages) == 48
    assert pages[-1]["next_offset"] is None


@pytest.mark.django_db
def test_list_tasks_small_page_reports_next_offset(user_a, make_task):
    for i in range(25):
        make_task(user_a, title=f"t{i}")
    out = tools.call("list_tasks", user_a, {"limit": 10})
    assert out["returned"] == 10
    assert out["total"] == 25
    assert out["next_offset"] == 10

    last = tools.call("list_tasks", user_a, {"limit": 10, "offset": 20})
    assert last["returned"] == 5
    assert last["next_offset"] is None


@pytest.mark.django_db
def test_list_projects_and_ideas_paginate(user_a, make_project, make_idea):
    for i in range(30):
        make_project(user_a, name=f"p{i}")
        make_idea(user_a, title=f"i{i}")
    for name, key in (("list_projects", "projects"), ("list_ideas", "ideas")):
        pages = _page_through(name, user_a, {"limit": 12})
        ids = [row["id"] for page in pages for row in page[key]]
        assert len(set(ids)) == 30, name
        assert [page["offset"] for page in pages] == [0, 12, 24]


def test_oversized_page_is_trimmed_to_fit_with_correct_next_offset():
    rows = [{"id": i, "title": "y" * 1000} for i in range(50)]
    payload = {"tasks": rows, "total": 120, "offset": 50, "returned": 50, "next_offset": 100}

    out = _truncate_payload(payload)

    assert _size(out) <= MAX_RESULT_BYTES
    kept = len(out["tasks"])
    assert 10 < kept < 50  # fits as many as possible, not a blind cut to 10
    assert out["tasks"] == rows[:kept]
    assert out["returned"] == kept
    assert out["next_offset"] == 50 + kept
    assert out["total"] == 120
    assert out["truncated"] is True
    # One more item would not have fit.
    assert _size({**out, "tasks": rows[: kept + 1]}) > MAX_RESULT_BYTES


def test_oversized_last_page_gets_a_next_offset():
    rows = [{"id": i, "title": "z" * 2000} for i in range(20)]
    payload = {"tasks": rows, "total": 20, "offset": 0, "returned": 20, "next_offset": None}
    out = _truncate_payload(payload)
    assert out["next_offset"] == len(out["tasks"]) < 20


def test_small_payload_is_untouched():
    payload = {"tasks": [{"id": i} for i in range(50)], "total": 50}
    assert _truncate_payload(payload) is payload
