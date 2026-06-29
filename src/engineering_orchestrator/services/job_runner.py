from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from engineering_orchestrator.models import TaskJob
from engineering_orchestrator.services.task_store import TaskStore


class JobRunner:
    def __init__(self, task_store: TaskStore, max_workers: int = 1):
        self.task_store = task_store
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tasker-job")

    def enqueue(self, task_id: str, action: str, work: Callable[[], object]) -> TaskJob:
        job = self.task_store.create_job(task_id, action)
        self.executor.submit(self._run, job.id, work)
        return job

    def _run(self, job_id: str, work: Callable[[], object]) -> None:
        self.task_store.start_job(job_id)
        try:
            work()
        except Exception as exc:  # pragma: no cover - defensive guard for background execution
            self.task_store.finish_job(job_id, "failed", str(exc))
            return
        self.task_store.finish_job(job_id, "succeeded")
