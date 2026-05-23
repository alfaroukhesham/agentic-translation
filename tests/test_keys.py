from app.config import get_settings
from app.storage.keys import export_key, result_key


def test_export_key():
    get_settings.cache_clear()
    assert export_key("42") == "blog-translations/exports/42/export.json"


def test_result_key():
    get_settings.cache_clear()
    assert result_key("42") == "blog-translations/results/42/result.json"
