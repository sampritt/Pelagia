"""Gunicorn defaults for Pelagia's I/O-bound API workload."""

import os


# Open-Meteo, OBIS, and OpenAI are requested independently after a dive-site
# page renders. Threads let those network waits progress concurrently while
# multiple processes retain isolation and use separate SQLite connections.
worker_class = "gthread"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = 60

