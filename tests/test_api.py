from fastapi.testclient import TestClient

from app import db
from app.dispatcher import app


def test_health():
    db.init_schema()
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_export_upload():
    client = TestClient(app)
    with __import__("unittest.mock").patch("app.routes.v1.get_storage") as gs:
        gs.return_value.presign_put.return_value = {
            "upload_url": "http://127.0.0.1:9000/upload",
            "export_key": "blog-translations/exports/99/export.json",
            "expires_in": 900,
        }
        r = client.post("/v1/jobs/99/export-upload")
    assert r.status_code == 200
    assert "exports/99/export.json" in r.json()["export_key"]
