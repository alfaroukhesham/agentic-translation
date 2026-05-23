from unittest.mock import MagicMock, patch

from app.storage.s3 import S3Storage


@patch("app.storage.s3.boto3")
def test_presign_put_uses_public_endpoint(mock_boto3):
    internal = MagicMock()
    public = MagicMock()
    public.generate_presigned_url.return_value = "http://127.0.0.1:9000/bucket/key?sig=1"
    mock_boto3.client.side_effect = [internal, public]

    storage = S3Storage()
    out = storage.presign_put("blog-translations/exports/42/export.json")
    assert out["upload_url"].startswith("http://127.0.0.1:9000")
    assert out["export_key"].endswith("export.json")
    assert out["expires_in"] > 0
