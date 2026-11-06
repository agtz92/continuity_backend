# Must stay in sync with `startCommand` in render.yaml. The Render service was
# created by hand, so whichever of the two the dashboard actually uses, both
# say the same thing.
#
# Worker class (gthread), workers, threads and timeout live in gunicorn.conf.py,
# read from WEB_CONCURRENCY / GUNICORN_THREADS / GUNICORN_TIMEOUT. Don't add
# flags here: command-line flags override the config file.
web: gunicorn continuity.wsgi:application
