from engineering_orchestrator.services.validation_service import ValidationService


def test_validation_service_runs_commands_and_captures_output(tmp_path):
    service = ValidationService(timeout_seconds=30)

    result = service.run(
        [
            "python -c \"print('ok')\"",
            "python -c \"import sys; print('bad'); sys.exit(7)\"",
        ],
        tmp_path,
    )

    assert result.status == "failed"
    assert result.commands[0].status == "passed"
    assert "ok" in result.commands[0].stdout
    assert result.commands[1].status == "failed"
    assert result.commands[1].returncode != 0
    assert "bad" in result.commands[1].stdout
