from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from engineering_orchestrator.models import TaskJob
from engineering_orchestrator.services.task_store import TaskStore


class JobRunner:
    def __init__(self, task_store: TaskStore, max_workers: int = 1):
        self.task_store = task_store
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tasker-job")
        self._futures = {}

    def enqueue(self, task_id: str, action: str, work: Callable[[], object], input: dict | None = None) -> TaskJob:
        job = self.task_store.create_job(task_id, action, input=input)
        self._futures[job.id] = self.executor.submit(self._run, job.id, work)
        return job

    def cancel(self, job_id: str) -> TaskJob:
        future = self._futures.get(job_id)
        if future is not None:
            future.cancel()
        return self.task_store.cancel_job(job_id)

    def _run(self, job_id: str, work: Callable[[], object]) -> None:
        if self.task_store.get_job(job_id).status == "cancelled":
            return
        self.task_store.start_job(job_id)
        try:
            result = work()
        except Exception as exc:  # pragma: no cover - defensive guard for background execution
            if self.task_store.get_job(job_id).status == "cancelled":
                return
            self.task_store.finish_job(job_id, "failed", str(exc))
            return
        if self.task_store.get_job(job_id).status == "cancelled":
            return
        if hasattr(result, "model_dump"):
            payload = result.model_dump(mode="json")
        elif isinstance(result, dict):
            payload = result
        elif isinstance(result, list):
            payload = {"items": result}
        else:
            payload = {"result": str(result)}
        self.task_store.finish_job(job_id, "succeeded", result=payload)
