"""Zentrale Konfiguration, ausschließlich über Umgebungsvariablen (Präfix ``AGENTDASH_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTDASH_", env_file=".env", extra="ignore")

    # Speicherort
    data_dir: Path = Path("./data")

    # Ports: UI/API, OTLP/HTTP-Receiver, Ollama-Proxy
    host: str = "0.0.0.0"
    port: int = 8080
    otlp_port: int = 4318
    proxy_port: int = 11434

    # Ollama
    ollama_upstream: str = "http://ollama:11434"
    ollama_status_interval: float = 10.0

    # Docker
    docker_enabled: bool = True
    docker_host: str = "unix:///var/run/docker.sock"
    docker_label: str = "agentdash.enable"
    # Container, die mit Proxy/OTLP sprechen, automatisch als Anwendung aufnehmen
    docker_auto_discover: bool = True
    docker_log_tail: int = 200

    # Sicherheit
    password: str | None = None
    secret_key: str | None = None
    ingest_key: str | None = None
    session_hours: int = 24 * 7

    # Speicherung
    log_retention_days: int = 14
    run_retention_days: int = 90
    store_prompts: str = "full"  # full | truncate | none
    prompt_truncate_chars: int = 4000

    # Frontend (gebautes Vite-Projekt)
    static_dir: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agentdash.db"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
