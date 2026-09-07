"""Runtime settings (environment variables, ``PS_`` prefix).

Defaults are chosen so ``uvicorn protocol_studio.main:app`` works on a laptop
with no configuration: SQLite file DB, dev auth (auto sign-in as the admin),
artifacts under ``./data``. Production sets ``PS_DATABASE_URL`` (Postgres),
``PS_AUTH_MODE=google`` and the Google OAuth secrets.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/protocol_studio.db"
    data_dir: Path = Path("./data")
    secret_key: str = Field(default="dev-only-change-me", description="Signs the session cookie.")
    session_max_age: int = 60 * 60 * 12

    # auth_mode: "dev" signs everyone in as dev_user_email; "google" uses OIDC.
    auth_mode: str = "dev"
    dev_user_email: str = "ben@sarika.com"
    admin_emails: list[str] = ["ben@sarika.com"]
    allowed_domain: str = "sarika.com"
    google_client_id: str = ""
    google_client_secret: str = ""
    public_base_url: str = "http://localhost:8080"

    # Frontend build to serve at "/" (empty → API only).
    web_dist: Path = Path("../web/dist")

    cors_origins: list[str] = ["http://localhost:5173"]

    # Evidence corpus (ADR-015/017): read-only S3 prefix holding FDA reviews, protocols, SAPs.
    aws_region: str = "us-east-2"
    corpus_s3_uri: str = "s3://sarika-main-fs/protocol-corpus/"
    upload_max_bytes: int = 60 * 1024 * 1024


settings = Settings()
