import pytest
from pydantic import ValidationError

from app.core.config import Settings

ENV_VARS = (
    "MONITORING_PROVIDER",
    "OPNSENSE_BASE_URL",
    "OPNSENSE_API_URL",
    "OPNSENSE_API_KEY",
    "OPNSENSE_API_SECRET",
    "UNIFI_ENABLED",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_defaults_to_real_sources_and_never_to_mock():
    current = settings()
    assert current.monitoring_provider == "opnsense" and current.unifi_enabled is True


def test_missing_credentials_do_not_stop_startup_and_are_named():
    current = settings()
    assert current.opnsense_missing == ["OPNSENSE_BASE_URL", "OPNSENSE_API_KEY", "OPNSENSE_API_SECRET"]
    assert current.unifi_missing == ["UNIFI_BASE_URL", "UNIFI_API_KEY"]
    assert settings(unifi_transport="connector").unifi_missing == ["UNIFI_CONSOLE_ID", "UNIFI_API_KEY"]


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


async def test_unconfigured_sources_report_what_is_missing_without_fake_data():
    from app.monitoring.factory import build_monitoring_provider, build_unifi_source
    from app.monitoring.schemas import IssueKind

    current = settings()
    firewall, unifi = build_monitoring_provider(current), build_unifi_source(current)
    assert (firewall.source, unifi.source) == ("opnsense", "unifi")
    for result in (await firewall.get_system_metrics(), await firewall.collect_inventory(), await unifi.collect_inventory()):
        assert result.data is None and result.issues[0].kind == IssueKind.NOT_CONFIGURED
    assert "OPNSENSE_API_KEY" in (await firewall.get_clients()).issues[0].message


def test_unifi_url_must_be_http():
    with pytest.raises(ValidationError):
        settings(unifi_base_url="console.local")
