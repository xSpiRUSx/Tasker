from engineering_orchestrator.policies.file_policy import FilePolicy


def test_file_policy_blocks_secret_and_requires_config_approval():
    policy = FilePolicy(
        project={"blocked_paths": ["**/*.cf"], "config_paths": ["*.yml"]},
        workflow={"blocked_change_types": ["configuration_change"]},
    )

    findings = policy.evaluate([".env", "settings.yml", "external/test.cf"], approved_gates=set())

    assert {finding.code for finding in findings} == {
        "blocked_path_changed",
        "config_change_requires_approval",
    }
    assert any(finding.path == ".env" for finding in findings)
    assert any(finding.path == "settings.yml" for finding in findings)

    approved_findings = policy.evaluate(["settings.yml"], approved_gates={"config_change"})

    assert approved_findings == []
