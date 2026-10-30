from app.schemas.errors import ErrorResponse

API_DESCRIPTION = """
A banking API: accounts, deposits, withdrawals and transfers on a double-entry ledger.

## Money
All amounts are **integers in paise** (1 rupee = 100 paise): `10000` means INR 100.00.
Floats and numeric strings are rejected. Balances can never go negative, and every
movement is recorded as balanced debit and credit ledger entries.

## Authentication
Send `Authorization: Bearer <access_token>`. Access tokens last 15 minutes. Use
`POST /auth/refresh` with the refresh token to get a new pair. Refresh tokens are
single-use: replaying one revokes the whole session.

## Idempotency and retries
Endpoints that move money accept an `Idempotency-Key` header (any unique string up to
255 characters, such as a UUID). Retrying a request with the same key returns the
original response, with the header `Idempotent-Replayed: true`, and never moves money
twice. Reusing a key with a different request returns `idempotency_key_reuse`. A request
that fails (for example with `insufficient_funds`) does not consume its key.
After a timeout or a `503`, retry the same request with the same key, using
exponential backoff.

## Errors
Every error has the same shape: `{"error": {"code", "message", "details"}}`.
Branch on `code`, not on `message`. Framework-level errors (unknown URL, wrong method)
use the same shape with codes such as `not_found` and `method_not_allowed`.

Every response carries an `X-Request-ID` header. Send your own (8 to 64 characters from
`A-Za-z0-9._-`) to correlate calls across systems, or let the server generate one.
Unexpected server errors also return it as `request_id` in the error body: quote it when
reporting a problem.

| Status | Codes | Meaning |
|---|---|---|
| 400 | `invalid_idempotency_key` | The `Idempotency-Key` header is empty, too long, or required and missing. |
| 401 | `unauthorized`, `missing_token`, `invalid_token`, `token_expired`, `token_revoked` | Bad credentials, or a missing, malformed, expired or revoked token. |
| 404 | `not_found` | The resource does not exist or is not yours. The two are indistinguishable by design. |
| 409 | `conflict` | The email or username is already registered. |
| 422 | `validation_error`, `insufficient_funds`, `idempotency_key_reuse`, `invalid_cursor` | The request is well-formed but cannot be processed. |
| 429 | `rate_limited` | Too many attempts. Wait the number of seconds in the `Retry-After` header, then retry. |
| 500 | `internal_error` | An unexpected server error. Report persistent failures with the `request_id`. |
| 503 | `busy`, `service_unavailable` | Temporary. Retry with exponential backoff. |
"""


def api_responses(success: dict, *error_statuses: str, protected: bool = True) -> dict:
    """Build the `responses` mapping for a route: its success model plus the shared
    error envelope for each status it can return. Protected routes always add 401 and 503."""
    # The library injects a default 422 on every operation. Declaring it ourselves makes it
    # use our error envelope instead of the library's array-of-errors shape. Any request
    # can also hit an unexpected 500.
    statuses = {"422", "500"} | set(error_statuses)
    if protected:
        statuses |= {"401", "503"}
    return {**success, **{status: ErrorResponse for status in sorted(statuses)}}
