import json
from unittest.mock import AsyncMock, patch

import pytest

from app import db


@pytest.mark.asyncio
async def test_webhook_sends_secret_header():
    db.init_schema()
    jid = db.create_job(
        wp_job_id="42",
        en_post_id=1,
        target_langs=["fr"],
        callback_url="https://httpbin.org/post",
        callback_secret="my-secret",
        s3_result_key="blog-translations/results/42/result.json",
        source_mode="inline",
    )
    db.set_status(jid, "completed")
    job = db.get_job_by_fastapi_id(jid)

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.webhook.httpx.AsyncClient", return_value=mock_client):
        from app.webhook import send_webhook

        ok = await send_webhook(job)
    assert ok
    call_kwargs = mock_client.post.call_args
    assert call_kwargs.kwargs["headers"]["X-Translation-Secret"] == "my-secret"
    body = json.loads(call_kwargs.kwargs["content"])
    assert body["wp_job_id"] == "42"
    assert body["status"] == "completed"
