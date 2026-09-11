# Must stay in sync with `startCommand` in render.yaml. The Render service was
# created by hand, so whichever of the two the dashboard actually uses, both
# say the same thing.
#
# gthread, not sync: sync workers buffer the whole response, which turns the
# assistant's SSE stream into one blob at the end and kills the typing effect.
# --timeout 120 because a turn that chains several tools legitimately takes
# longer than gunicorn's 30s default, and the default kills it silently —
# no error frame, nothing persisted.
web: gunicorn continuity.wsgi:application --worker-class gthread --workers 2 --threads 4 --timeout 120
