"""Gunicorn config — gunicorn loads ./gunicorn.conf.py on its own.

Concurrency comes from env vars so it can be tuned in the Render dashboard
without a deploy. Requests served at once = WEB_CONCURRENCY x GUNICORN_THREADS.

The stress test of 2026-11-06 (k6, staging) broke at ~50 simultaneous users
with 2 x 4 = 8 slots: requests queued behind the heavy `dashboard` query until
p95 hit 2.1 s and some timed out. Most of a request's time is spent waiting on
Postgres, so threads are the cheap lever (each thread holds at most one
persistent DB connection: workers x threads = max connections to Supabase).

Flags passed on the command line override this file, so the Render start
command must be just `gunicorn continuity.wsgi:application` for these to apply.
"""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# gthread, not sync: sync workers buffer the whole response, which turns the
# assistant's SSE stream into one blob at the end and kills the typing effect.
worker_class = "gthread"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "8"))

# A chat turn that chains several tools legitimately takes longer than the 30 s
# default, and the default kills it silently — no error frame, nothing persisted.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
