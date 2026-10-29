import os

bind = "0.0.0.0:8000"
workers = int(os.getenv("WEB_CONCURRENCY", "3"))
timeout = 30  # must stay above LEDGER_LOCK_TIMEOUT_MS so we return a clean 503, not a killed worker
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
worker_tmp_dir = "/dev/shm"  # keep gunicorn's heartbeat files off the container's disk
