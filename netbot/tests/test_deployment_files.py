"""Los artefactos de despliegue no se ejecutan en CI: estas pruebas evitan que diverjan."""
import json
import logging.config
import re
import secrets
from pathlib import Path

import yaml

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())
DOCKERFILE = (ROOT / "Dockerfile").read_text()


def test_api_trusts_proxy_headers_only_from_the_fixed_proxy_address():
    proxy_ip = COMPOSE["services"]["proxy"]["networks"]["netbot"]["ipv4_address"]
    assert f'"--forwarded-allow-ips", "{proxy_ip}"' in DOCKERFILE
    assert "--forwarded-allow-ips=*" not in DOCKERFILE and '"*"' not in DOCKERFILE
    assert '"--workers", "1"' in DOCKERFILE  # sesiones de invitados en memoria


def test_only_the_proxy_publishes_ports_and_containers_run_unprivileged():
    published = {name for name, service in COMPOSE["services"].items() if service.get("ports")}
    assert published == {"proxy"}
    assert re.search(r"^USER netbot$", DOCKERFILE, re.M)
    for name in ("api", "worker", "migrate"):
        service = COMPOSE["services"][name]
        assert service["read_only"] is True and service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name


def test_database_roles_and_write_key_are_separated_by_service():
    services = COMPOSE["services"]
    assert "netbot_app:" in services["api"]["environment"]["DATABASE_URL"]
    assert "netbot_app:" in services["worker"]["environment"]["DATABASE_URL"]
    assert "${POSTGRES_USER}" in services["migrate"]["environment"]["DATABASE_URL"]
    # El proceso expuesto nunca recibe la clave de escritura; el worker no arranca sin pedirlo.
    assert services["api"]["environment"]["UNIFI_WRITE_API_KEY"] == ""
    assert services["worker"]["profiles"] == ["worker"]
    assert services["worker"]["command"] == ["python", "-m", "app.agents.cli", "--loop"]
    assert services["migrate"]["command"] == ["python", "-m", "alembic", "upgrade", "head"]


def test_image_excludes_secrets_and_installs_only_pinned_dependencies():
    ignored = (ROOT / ".dockerignore").read_text().split()
    for pattern in (".env", ".env.*", "*.db", "*.pem", "deploy/tls/", "tests/"):
        assert pattern in ignored
    assert "pip install --no-deps -r requirements.lock" in DOCKERFILE
    pinned = [line for line in (ROOT / "requirements.lock").read_text().splitlines() if line and not line.startswith("#")]
    assert pinned and all("==" in line for line in pinned)
    names = {line.split("==")[0].lower().replace("_", "-") for line in pinned}
    assert {"fastapi", "uvicorn", "psycopg-binary", "anthropic", "httpx2", "alembic"} <= names


def test_container_proxy_template_matches_the_reference_template():
    reference = (ROOT / "deploy/nginx/netbot.conf").read_text()
    template = (ROOT / "deploy/nginx/netbot.compose.conf.template").read_text()

    def directives(text):
        return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    expected = [line.replace("netbot.example.internal", "${NETBOT_SERVER_NAME}").replace("127.0.0.1:8000", "api:8000")
                for line in directives(reference)]
    assert directives(template) == expected
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in template


def test_logging_configuration_and_production_example_are_valid(monkeypatch):
    config = json.loads((ROOT / "deploy/logging.json").read_text())
    assert {"uvicorn", "uvicorn.access", "netbot"} <= set(config["loggers"])
    assert logging.config.DictConfigurator(config).config["version"] == 1
    example = dict(line.split("=", 1) for line in (ROOT / "deploy/production.env.example").read_text().splitlines()
                   if line and not line.startswith("#"))
    # Los valores de ejemplo, completados con un secreto válido, pasan la validación de producción.
    example.update(JWT_SECRET_KEY=secrets.token_urlsafe(64))
    for key, value in example.items():
        monkeypatch.setenv(key, value)  # mismo camino que un .env real, incluidos los valores JSON
    settings = Settings(_env_file=None)
    assert settings.environment == "production" and settings.unifi_write_enabled is False
    assert settings.llm_provider == "openrouter" and settings.cors_origins == "https://netbot.example.internal"
