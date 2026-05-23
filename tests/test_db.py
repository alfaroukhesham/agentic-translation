from app import db


def test_init_schema_and_enqueue():
    db.init_schema()
    jid = db.create_job(
        wp_job_id="42",
        en_post_id=7379,
        target_langs=["fr", "ar"],
        callback_url="https://example.com/wp-json/blog-translation/v1/webhook",
        callback_secret="secret",
        s3_result_key="blog-translations/results/42/result.json",
        source_mode="inline",
    )
    row = db.get_job_by_fastapi_id(jid)
    assert row["status"] == "queued"
    assert row["wp_job_id"] == "42"


def test_only_one_processing():
    db.init_schema()
    a = db.create_job(
        wp_job_id="1",
        en_post_id=1,
        target_langs=["fr"],
        callback_url="http://x",
        callback_secret="s",
        s3_result_key="blog-translations/results/1/result.json",
        source_mode="inline",
    )
    db.create_job(
        wp_job_id="2",
        en_post_id=2,
        target_langs=["fr"],
        callback_url="http://x",
        callback_secret="s",
        s3_result_key="blog-translations/results/2/result.json",
        source_mode="inline",
    )
    db.set_status(a, "processing")
    nxt = db.dequeue_next()
    assert nxt is None
