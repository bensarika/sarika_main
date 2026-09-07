"""API test fixtures: fresh SQLite DB per test, dev auth, an admin and an author client."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    os.environ["PS_DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["PS_DATA_DIR"] = str(tmp_path / "data")
    # settings/db are module globals; re-import fresh for each test.
    import importlib

    import protocol_studio.settings as st

    importlib.reload(st)
    import protocol_studio.db as db

    importlib.reload(db)
    import protocol_studio.auth.session as sess

    importlib.reload(sess)
    import protocol_studio.api.admin as ad
    import protocol_studio.api.library as lib
    import protocol_studio.api.versions as vs
    import protocol_studio.api.works as ws
    import protocol_studio.auth.routes as ar
    import protocol_studio.engine.export as ex
    import protocol_studio.main as main

    for m in (ar, ex, ws, vs, ad, lib, main):
        importlib.reload(m)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    r = client.post("/auth/dev-login")
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    return client


def login_as(client: TestClient, email: str) -> None:
    client.cookies.clear()
    r = client.post("/auth/dev-login", params={"email": email})
    assert r.status_code == 200, r.text
