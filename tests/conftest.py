import os
import pytest


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STORAGE_ENDPOINT", "http://127.0.0.1:9000")
    monkeypatch.setenv("STORAGE_PUBLIC_ENDPOINT", "http://127.0.0.1:9000")
    monkeypatch.setenv("STORAGE_BUCKET", "test-bucket")
    monkeypatch.setenv("STORAGE_ACCESS_KEY", "test")
    monkeypatch.setenv("STORAGE_SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("API_SECRET", "test-api-secret")
    from app.config import get_settings

    get_settings.cache_clear()
