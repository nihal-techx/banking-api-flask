#!/usr/bin/env bash
# End-to-end acceptance test for a running deployment.
# Usage: bash deploy/smoke.sh https://host [extra curl args, e.g. -k]
set -euo pipefail

BASE="${1:?usage: bash deploy/smoke.sh <base-url> [extra curl args]}"
shift
CURL=(curl -sS --max-time 20 "$@")
PY="$(command -v python3 || command -v python)"

BODY="$(mktemp)"
HEADERS="$(mktemp)"
trap 'rm -f "$BODY" "$HEADERS"' EXIT

# call METHOD PATH JSON [header...]  ->  prints the HTTP status; body and headers saved to files
call() {
  local method="$1" path="$2" data="$3"
  shift 3
  local args=(-X "$method" -o "$BODY" -D "$HEADERS" -w '%{http_code}' -H 'Content-Type: application/json')
  if [ -n "$data" ]; then args+=(-d "$data"); fi
  local header
  for header in "$@"; do args+=(-H "$header"); done
  "${CURL[@]}" "${args[@]}" "$BASE$path"
}

jget() { "$PY" -c "import sys, json; print(json.load(sys.stdin)$1)" < "$BODY"; }

check() {  # check "description" expected actual
  if [ "$2" = "$3" ]; then
    echo "ok    $1"
  else
    echo "FAIL  $1 (expected $2, got $3)"
    echo "      response body: $(head -c 300 "$BODY")"
    exit 1
  fi
}

NAME="smoke$(date +%s)"
PASSWORD="smoke-Pass-12345"

check "liveness /health" 200 "$(call GET /health '')"
check "readiness /ready (database and redis reachable)" 200 "$(call GET /ready '')"
check "register a throwaway user" 201 "$(call POST /auth/register "{\"email\":\"$NAME@example.com\",\"username\":\"$NAME\",\"password\":\"$PASSWORD\"}")"
check "login" 200 "$(call POST /auth/login "{\"email\":\"$NAME@example.com\",\"password\":\"$PASSWORD\"}")"
TOKEN="$(jget "['access_token']")"
AUTH="Authorization: Bearer $TOKEN"

check "protected route without a token is refused" 401 "$(call GET /accounts '')"
check "open an account" 201 "$(call POST /accounts '{"account_type":"savings"}' "$AUTH")"
ACCOUNT="$(jget "['id']")"

KEY="smoke-$NAME"
check "deposit without an Idempotency-Key is refused (production mode is on)" 400 "$(call POST "/accounts/$ACCOUNT/deposits" '{"amount":10000}' "$AUTH")"
check "deposit with an Idempotency-Key" 201 "$(call POST "/accounts/$ACCOUNT/deposits" '{"amount":10000}' "$AUTH" "Idempotency-Key: $KEY")"
check "balance after the deposit" 10000 "$(jget "['balance_after']")"
check "replaying the same key succeeds" 201 "$(call POST "/accounts/$ACCOUNT/deposits" '{"amount":10000}' "$AUTH" "Idempotency-Key: $KEY")"
if grep -qi '^idempotent-replayed: true' "$HEADERS"; then
  echo "ok    the replay was flagged Idempotent-Replayed"
else
  echo "FAIL  the replay was not flagged Idempotent-Replayed"
  exit 1
fi
check "overdrawing is refused" 422 "$(call POST "/accounts/$ACCOUNT/withdrawals" '{"amount":999999}' "$AUTH" "Idempotency-Key: $KEY-w")"
check "statement is readable" 200 "$(call GET "/accounts/$ACCOUNT/transactions" '' "$AUTH")"
check "the statement has exactly one entry (the replay did not double-credit)" 1 "$(jget "['items'].__len__()")"
check "every response carries a request id" 1 "$(grep -ci '^x-request-id:' "$HEADERS")"

echo
echo "ALL CHECKS PASSED against $BASE"