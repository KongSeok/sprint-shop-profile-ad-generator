from unittest.mock import Mock, call

import pytest
from google.genai.errors import APIError

from app.services import gemini_retry


@pytest.mark.parametrize(("statuses", "delays", "terminal"), [
    ((503, 503, None), (5, 15), None),
    ((503, 503, 503), (5, 15), 503),
    ((429,), (), 429),
    ((503, 429), (5,), 429),
    ((504,), (), 504),
])
def test_retry_only_overload(monkeypatch, statuses, delays, terminal):
    sleep = Mock()
    monkeypatch.setattr(gemini_retry, "sleep", sleep)
    generate = Mock(side_effect=[
        APIError(status, {"error": {"message": "test"}}) if status else "ok"
        for status in statuses
    ])
    if terminal:
        with pytest.raises(APIError) as error:
            gemini_retry.generate_content(generate, model="test")
        assert error.value.code == terminal
    else:
        assert gemini_retry.generate_content(generate, model="test") == "ok"
    assert generate.call_args_list == [call(model="test")] * len(statuses)
    assert sleep.call_args_list == [call(delay) for delay in delays]
