import json

import pytest

from app.api.docs import API_DESCRIPTION
from app.errors import AppError

SPEC_URL = "/openapi/openapi.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

EXPECTED = {
    ("/auth/register", "post"),
    ("/auth/login", "post"),
    ("/auth/refresh", "post"),
    ("/auth/logout", "post"),
    ("/auth/me", "get"),
    ("/accounts", "post"),
    ("/accounts", "get"),
    ("/accounts/{account_id}", "get"),
    ("/accounts/{account_id}/deposits", "post"),
    ("/accounts/{account_id}/withdrawals", "post"),
    ("/accounts/{account_id}/transactions", "get"),
    ("/transfers", "post"),
    ("/transactions/{transaction_id}", "get"),
}
NO_AUTH = {("/auth/register", "post"), ("/auth/login", "post")}
MONEY = [
    ("/accounts/{account_id}/deposits", "post"),
    ("/accounts/{account_id}/withdrawals", "post"),
    ("/transfers", "post"),
]


@pytest.fixture
def spec(client):
    response = client.get(SPEC_URL)
    assert response.status_code == 200, f"spec is not served at {SPEC_URL}"
    return response.get_json()


def operations(spec):
    return {
        (path, method): operation
        for path, methods in spec["paths"].items()
        for method, operation in methods.items()
        if method in HTTP_METHODS
    }


def has_idempotency_header(operation):
    return any(
        param.get("name") == "Idempotency-Key" and param.get("in") == "header"
        for param in operation.get("parameters", [])
    )


def all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from all_subclasses(sub)


def test_every_public_operation_is_documented(spec):
    assert EXPECTED <= set(operations(spec))


def test_operations_declare_bearer_security_except_register_and_login(spec):
    ops = operations(spec)
    for key in EXPECTED:
        if key in NO_AUTH:
            assert not ops[key].get("security"), key
        else:
            assert {"jwt": []} in ops[key]["security"], key


def test_authentication_failures_are_documented(spec):
    ops = operations(spec)
    for key in EXPECTED - {("/auth/register", "post")}:
        assert "401" in ops[key]["responses"], key


@pytest.mark.parametrize("key", MONEY)
def test_money_operations_document_idempotency_and_failures(spec, key):
    operation = operations(spec)[key]
    assert has_idempotency_header(operation), key
    for status in ("400", "401", "404", "422", "503"):
        assert status in operation["responses"], (key, status)


def test_other_operations_do_not_advertise_the_idempotency_header(spec):
    ops = operations(spec)
    for key in EXPECTED - set(MONEY):
        assert not has_idempotency_header(ops[key]), key


def test_every_error_response_uses_the_shared_envelope(spec):
    for key, operation in operations(spec).items():
        for status, response in operation["responses"].items():
            if int(status) >= 400:
                assert "ErrorResponse" in json.dumps(response), (key, status)


def test_description_documents_money_auth_and_idempotency(spec):
    description = spec["info"]["description"]
    for phrase in ("paise", "Bearer", "Idempotency-Key"):
        assert phrase in description, phrase


def test_every_error_code_is_documented():
    codes = {sub.code for sub in all_subclasses(AppError)}
    codes |= {
        "validation_error",
        "missing_token",
        "invalid_token",
        "token_expired",
        "token_revoked",
        "service_unavailable",
    }
    missing = sorted(code for code in codes if f"`{code}`" not in API_DESCRIPTION)
    assert missing == []


def test_amount_fields_document_their_unit(spec):
    amount = spec["components"]["schemas"]["AmountBody"]["properties"]["amount"]
    assert "paise" in amount["description"]
