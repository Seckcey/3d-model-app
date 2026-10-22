"""Celery app for the isolated CAD worker.

This process has no database credentials and no outbound network: it receives
a validated spec from the queue, writes files to its staging directory and
returns hashes. The API side verifies and publishes them.
"""

import os

from celery import Celery

app = Celery("bpcad-cad", broker=os.environ.get("REDIS_URL", "memory://"))
app.conf.update(
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="cad",
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 2 * 3600},
    imports=("cadworker.tasks",),
)
