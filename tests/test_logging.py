import json
import logging
import re
import sys

import pytest
from flask import g

from app.logging_config import JsonFormatter


def make_record(request_id="-", exc_info=None, **extra):
    record = logging.LogRecord(
        "app.test", logging.INFO, __file__, 10, "hello %s", ("world",), exc_info
    )
    record.request_id = request_id
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_one_json_object_per_record():
    payload = json.loads(JsonFormatter().format(make_record("req-12345678", status=200)))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["request_id"] == "req-12345678"
    assert payload["status"] == 200
    assert payload["timestamp"].endswith("+00:00")


def test_json_formatter_omits_the_placeholder_request_id():
    payload = json.loads(JsonFormatter().format(make_record("-")))
    assert "request_id" not in payload


def test_json_formatter_includes_the_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        record = make_record(exc_info=sys.exc_info())
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]


def test_log_records_carry_the_current_request_id(app, caplog):
    log = logging.getLogger("app.test")
    with caplog.at_level(logging.INFO, logger="app.test"):
        log.info("outside a request")
        with app.test_request_context("/"):
            g.request_id = "req-12345678"
            log.info("inside a request")
    outside, inside = caplog.records[-2:]
    assert outside.request_id == "-"
    assert inside.request_id == "req-12345678"


def test_response_carries_a_generated_request_id(client):
    request_id = client.get("/health").headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)


def test_a_valid_incoming_request_id_is_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "client-trace-12345"})
    assert response.headers["X-Request-ID"] == "client-trace-12345"


@pytest.mark.parametrize(
    "supplied", ["short", "has spaces in it!!", "x" * 65, "<script>alert(1)</script>"]
)
def test_an_invalid_incoming_request_id_is_replaced(client, supplied):
    response = client.get("/health", headers={"X-Request-ID": supplied})
    returned = response.headers["X-Request-ID"]
    assert returned != supplied
    assert re.fullmatch(r"[0-9a-f]{32}", returned)


def test_requests_are_logged_with_status_and_duration(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        response = client.get("/accounts")  # no token: 401
    record = next(r for r in caplog.records if r.name == "app.request")
    assert (record.method, record.path, record.status) == ("GET", "/accounts", 401)
    assert record.duration_ms >= 0
    assert record.request_id == response.headers["X-Request-ID"]


def test_health_probes_are_not_logged_at_info(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        client.get("/health")
        client.get("/ready")
    assert [r for r in caplog.records if r.name == "app.request"] == []


def test_credentials_and_tokens_never_appear_in_logs(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "Hunter2-super-secret"},
        )
        client.get("/auth/me", headers={"Authorization": "Bearer super-secret-token-value-123"})
    assert "Hunter2-super-secret" not in caplog.text
    assert "super-secret-token-value-123" not in caplog.text
