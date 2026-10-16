#!/usr/bin/env bash
# Render build script
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
# Las migraciones se escriben en desarrollo y viajan en el repo. Generarlas
# aquí creaba archivos que no existen en git; ahora, si falta una, el build
# falla y la versión anterior sigue sirviendo.
python manage.py makemigrations --check --dry-run
python manage.py migrate --no-input
