import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"  # 0.0.0.0 is for inside the container only
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = 2
worker_class = "gthread"
timeout = 30
graceful_timeout = 20
keepalive = 5
max_requests = 2000
max_requests_jitter = 200
worker_tmp_dir = "/dev/shm"
limit_request_line = 4094
accesslog = "-"
errorlog = "-"
