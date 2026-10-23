import pytest

from app.core import config


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("timeout_ms", [300_000, 420_000])
def test_extraction_uses_configured_timeout_and_medium_for_both_versions(
    api_client, gemini_mock, monkeypatch, version, timeout_ms,
):
    monkeypatch.setattr(config, "GEMINI_TIMEOUT_MS", timeout_ms)
    result = api_client.post("/profile/extract", json={"text": "소개 글", "prompt_version": version})
    assert result.status_code == 200
    assert gemini_mock.call_args.kwargs["http_options"].timeout == timeout_ms
    generation = gemini_mock.return_value.__enter__.return_value.models.generate_content.call_args.kwargs["config"]
    assert generation.thinking_config.thinking_level.value == "MEDIUM"
