import pytest
from pydantic import ValidationError

from app.core.config import Settings

ENV_VARS = (
    "MONITORING_PROVIDER",
    "OPNSENSE_BASE_URL",
    "OPNSENSE_API_URL",
    "OPNSENSE_API_KEY",
    "OPNSENSE_API_SECRET",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_defaults_to_mock_without_any_credentials():
    assert settings().monitoring_provider == "mock"


def test_opnsense_provider_requires_credentials_and_names_the_missing_ones():
    with pytest.raises(ValidationError) as info:
        settings(monitoring_provider="opnsense")
    message = str(info.value)
    assert (
        "OPNSENSE_BASE_URL" in message
        and "OPNSENSE_API_KEY" in message
        and "OPNSENSE_API_SECRET" in message
    )


def test_blank_values_from_env_example_count_as_missing(monkeypatch):
    monkeypatch.setenv("OPNSENSE_API_KEY", "")
    assert settings().opnsense_api_key is None


@pytest.mark.parametrize("variable", ["OPNSENSE_BASE_URL", "OPNSENSE_API_URL"])
def test_both_url_variable_names_are_accepted(monkeypatch, variable):
    monkeypatch.setenv(variable, "https://fw.local")
    assert settings().opnsense_base_url == "https://fw.local"


def test_secrets_are_masked_in_repr(monkeypatch):
    monkeypatch.setenv("MONITORING_PROVIDER", "opnsense")
    monkeypatch.setenv("OPNSENSE_BASE_URL", "https://fw.local")
    monkeypatch.setenv("OPNSENSE_API_KEY", "key-abc")
    monkeypatch.setenv("OPNSENSE_API_SECRET", "secret-xyz")
    current = settings()
    assert "key-abc" not in repr(current) and "secret-xyz" not in repr(current)
    assert current.opnsense_api_secret.get_secret_value() == "secret-xyz"


def test_base_url_must_be_http():
    with pytest.raises(ValidationError):
        settings(
            monitoring_provider="opnsense",
            opnsense_base_url="fw.local",
            opnsense_api_key="k",
            opnsense_api_secret="s",
        )
