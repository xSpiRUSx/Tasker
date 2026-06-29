from engineering_orchestrator.corrections import LinkedTaskDetector


def test_detects_explicit_task_id():
    result = LinkedTaskDetector().detect("по ENG-2026-00011 нужно исправить замечания")

    assert result.found is True
    assert result.parent_task_id == "ENG-2026-00011"
    assert result.extracted_reference == "ENG-2026-00011"


def test_detects_russian_numeric_task_reference():
    result = LinkedTaskDetector().detect("Есть замечания по задаче 00011: исправить запрос")

    assert result.found is True
    assert result.parent_task_id is None
    assert result.extracted_reference == "00011"


def test_detects_previous_task_hint():
    result = LinkedTaskDetector().detect("после ревью по предыдущей задаче исправь замечания")

    assert result.found is True
    assert result.needs_latest_task_lookup is True


def test_ignores_plain_new_task():
    result = LinkedTaskDetector().detect("sq_erp_ext исправь ошибку запроса")

    assert result.found is False
