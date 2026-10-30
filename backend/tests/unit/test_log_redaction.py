import json
import logging
import sys

from app.logging import JsonFormatter


def format_record(**extra) -> dict:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "event", None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(JsonFormatter().format(record))


def test_sensitive_extra_fields_are_redacted_whatever_their_case():
    payload = format_record(
        Password="hunter2", csrf_token="abc", session_id="xyz", api_key="k", status=200
    )

    assert payload["Password"] == "[redacted]"
    assert payload["csrf_token"] == "[redacted]"
    assert payload["session_id"] == "[redacted]"
    assert payload["api_key"] == "[redacted]"
    assert payload["status"] == 200


def test_sensitive_keys_inside_dict_fields_are_redacted():
    payload = format_record(body={"email": "a@example.com", "Authorization": "Bearer x"})

    assert payload["body"] == {"email": "a@example.com", "Authorization": "[redacted]"}


def test_exception_logs_keep_the_traceback_and_redact_extras():
    record = logging.LogRecord("app.test", logging.ERROR, __file__, 1, "failed", None, None)
    record.cookie = "session=secret-value"
    try:
        raise ValueError("boom")
    except ValueError:
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))

    assert payload["cookie"] == "[redacted]"
    assert "ValueError: boom" in payload["exc_info"]
