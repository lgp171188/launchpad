import os

config_dir = os.path.dirname(__file__)
log_dir = os.path.join(config_dir, "..", "..", "logs")

bind = [":8085", ":8087"]
workers = 1
threads = 10
log_level = "DEBUG"

log_file = os.path.join(log_dir, "gunicorn.log")
error_logfile = os.path.join(log_dir, "gunicorn-error.log")
access_logfile = os.path.join(log_dir, "gunicorn-access.log")
