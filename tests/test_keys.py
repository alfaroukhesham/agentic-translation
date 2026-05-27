import pytest

from app.job_types import normalize_job_type
from app.storage.keys import export_key, result_key


def test_export_key_blog_default():
    assert export_key("42") == "blog-translations/exports/42/export.json"


def test_result_key_blog_default():
    assert result_key("42") == "blog-translations/results/42/result.json"


def test_news_prefix():
    assert export_key("7", "news") == "news-translations/exports/7/export.json"
    assert result_key("7", "news") == "news-translations/results/7/result.json"


def test_page_acf_prefix():
    assert export_key("3", "page_acf") == "page-acf-translations/exports/3/export.json"
    assert result_key("3", "page_acf") == "page-acf-translations/results/3/result.json"


def test_invalid_job_type():
    with pytest.raises(ValueError):
        normalize_job_type("invalid")
