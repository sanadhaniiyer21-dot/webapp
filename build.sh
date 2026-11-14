#!/usr/bin/env bash
# Render build step.
#
# set -o errexit matters: without it a failed migration still produces a
# "successful" deploy serving a broken site.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

# Collect static files for WhiteNoise. CompressedStaticFilesStorage, not the
# Manifest variant, so a missing hashed file can never break the 500 page.
python manage.py collectstatic --noinput

# Applies the schema and seeds the catalogue, the FAQ and the error codes.
python manage.py migrate --noinput
