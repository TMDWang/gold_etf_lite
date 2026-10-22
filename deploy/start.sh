#!/bin/sh
set -eu
umask 077
# Bind mounts are created by Docker as root on first start.
mkdir -p /backups
chown appuser:appuser /backups
chmod 700 /backups
python manage.py check --deploy --fail-level ERROR
python manage.py migrate --noinput
exec supervisord -c deploy/supervisord.conf
