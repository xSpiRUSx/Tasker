from engineering_orchestrator.llm.token_usage import estimate_token_usage, parse_codex_cli_token_usage


def test_codex_cli_usage_parses_reported_total_only():
    usage = parse_codex_cli_token_usage(stderr="some log\n\ntokens used\n205,299\n")

    assert usage is not None
    assert usage.total_tokens == 205299
    assert usage.prompt_tokens is None
    assert usage.completion_tokens is None
    assert usage.cached_prompt_tokens is None
    assert usage.source == "codex_cli_reported_total"
    assert usage.is_estimated is False


def test_codex_cli_usage_parses_breakdown():
    usage = parse_codex_cli_token_usage(
        stderr=(
            "input tokens: 120,000\n"
            "cached input tokens: 80,000\n"
            "output tokens: 5,432\n"
            "reasoning tokens: 1,234\n"
        )
    )

    assert usage is not None
    assert usage.prompt_tokens == 120000
    assert usage.cached_prompt_tokens == 80000
    assert usage.completion_tokens == 5432
    assert usage.reasoning_tokens == 1234
    assert usage.total_tokens == 125432
    assert usage.source == "codex_cli_reported_breakdown"
    assert usage.is_estimated is False


def test_estimate_token_usage_marks_estimated():
    usage = estimate_token_usage(prompt_chars=1200, completion_chars=40)

    assert usage.prompt_tokens == 300
    assert usage.completion_tokens == 10
    assert usage.total_tokens == 310
    assert usage.source == "char_estimate"
    assert usage.is_estimated is True
