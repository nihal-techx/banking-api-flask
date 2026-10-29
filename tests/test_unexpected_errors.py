import logging

import pytest

from app.services import account_service


@pytest.fixture
def exploding_service(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail: the db password is hunter2")

    monkeypatch.setattr(account_service, "list_accounts", boom)


def test_unexpected_errors_return_the_envelope_without_leaking_details(
    client, signup, exploding_service
):
    headers = signup("alice")
    response = client.get("/accounts", headers=headers)

    assert response.status_code == 500
    error = response.get_json()["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert "hunter2" not in response.get_data(as_text=True)


def test_unexpected_errors_are_logged_with_the_traceback(client, signup, exploding_service, caplog):
    headers = signup("alice")
    with caplog.at_level(logging.ERROR):
        response = client.get("/accounts", headers=headers)

    record = next(r for r in caplog.records if r.name == "app.error_handlers")
    assert record.exc_info is not None
    assert record.request_id == response.headers["X-Request-ID"]
