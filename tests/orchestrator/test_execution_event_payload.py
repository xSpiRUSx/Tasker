from engineering_orchestrator.api import Orchestrator
from engineering_orchestrator.executors.base import ExecutionResult


def test_execution_event_payload_omits_runtime_text():
    orchestrator = object.__new__(Orchestrator)
    result = ExecutionResult(
        status="success",
        summary="done",
        changed_files=["src/app.py"],
        command=["codex", "exec"],
        prompt="p" * 100,
        stdout="x" * 1000,
        stderr="y" * 500,
        logs="z" * 1500,
    )

    payload = orchestrator._execution_event_payload(result)

    assert payload["stdout_chars"] == 1000
    assert payload["stderr_chars"] == 500
    assert payload["logs_chars"] == 1500
    assert "stdout" not in payload
    assert "stderr" not in payload
    assert "logs" not in payload
