import base64
import json
import uuid

import pytest


def open_account(client, headers, account_type="savings"):
    response = client.post("/accounts", json={"account_type": account_type}, headers=headers)
    return response.get_json()["id"]


def deposit(client, headers, account_id, amount):
    response = client.post(
        f"/accounts/{account_id}/deposits", json={"amount": amount}, headers=headers
    )
    assert response.status_code == 201
    return response.get_json()


def withdraw(client, headers, account_id, amount):
    response = client.post(
        f"/accounts/{account_id}/withdrawals", json={"amount": amount}, headers=headers
    )
    assert response.status_code == 201
    return response.get_json()


def transfer(client, headers, from_id, to_id, amount):
    body = {"from_account_id": from_id, "to_account_id": to_id, "amount": amount}
    response = client.post("/transfers", json=body, headers=headers)
    assert response.status_code == 201
    return response.get_json()


def statement(client, headers, account_id, **params):
    return client.get(
        f"/accounts/{account_id}/transactions", query_string=params, headers=headers
    )


def walk(client, headers, account_id, limit):
    """Follow next_cursor until exhausted. Returns (all_items, page_sizes)."""
    items, sizes, cursor = [], [], None
    for _ in range(100):  # guard against a cursor that never ends
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = statement(client, headers, account_id, **params).get_json()
        items.extend(body["items"])
        sizes.append(len(body["items"]))
        cursor = body["next_cursor"]
        if cursor is None:
            return items, sizes
    raise AssertionError("pagination never terminated")


def b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def test_statement_lists_newest_first_with_counterparty(client, signup):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)
    deposit(client, alice, a, 10_000)
    transfer(client, alice, a, b, 3_000)
    withdraw(client, alice, a, 1_000)

    body = statement(client, alice, a).get_json()
    assert [
        (i["type"], i["direction"], i["amount"], i["balance_after"]) for i in body["items"]
    ] == [
        ("withdrawal", "debit", 1_000, 6_000),
        ("transfer", "debit", 3_000, 7_000),
        ("deposit", "credit", 10_000, 10_000),
    ]
    assert [i["counterparty_account_id"] for i in body["items"]] == [None, b, None]
    assert body["next_cursor"] is None

    received = statement(client, bob, b).get_json()["items"]
    assert len(received) == 1
    assert received[0]["direction"] == "credit"
    assert received[0]["counterparty_account_id"] == a


@pytest.mark.parametrize("limit", [1, 3, 6, 100])
def test_pagination_walks_every_entry_exactly_once(client, signup, limit):
    alice = signup("alice")
    a = open_account(client, alice)
    for amount in range(100, 700, 100):  # six deposits: 100 .. 600
        deposit(client, alice, a, amount)

    items, sizes = walk(client, alice, a, limit)
    assert [i["amount"] for i in items] == [600, 500, 400, 300, 200, 100]
    assert all(size > 0 for size in sizes)  # no phantom empty page at exact multiples
    assert all(size == limit for size in sizes[:-1])


def test_pages_are_stable_when_new_entries_arrive(client, signup):
    alice = signup("alice")
    a = open_account(client, alice)
    for amount in (100, 200, 300, 400, 500):
        deposit(client, alice, a, amount)

    first = statement(client, alice, a, limit=2).get_json()
    assert [i["amount"] for i in first["items"]] == [500, 400]

    for amount in (1_000, 2_000, 3_000):  # new activity between page fetches
        deposit(client, alice, a, amount)

    second = statement(client, alice, a, limit=2, cursor=first["next_cursor"]).get_json()
    assert [i["amount"] for i in second["items"]] == [300, 200]  # no repeats, no skips


def test_running_balance_chain_holds_across_pages(client, signup):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)
    deposit(client, alice, a, 10_000)
    deposit(client, bob, b, 4_000)
    transfer(client, alice, a, b, 2_500)
    transfer(client, bob, b, a, 700)
    withdraw(client, alice, a, 1_200)
    deposit(client, alice, a, 300)

    items, _ = walk(client, alice, a, limit=2)
    assert len(items) == 5

    current = client.get(f"/accounts/{a}", headers=alice).get_json()["balance"]
    assert current == 7_300
    assert items[0]["balance_after"] == current

    for newer, older in zip(items, items[1:]):
        signed = newer["amount"] if newer["direction"] == "credit" else -newer["amount"]
        assert newer["balance_after"] == older["balance_after"] + signed

    assert items[-1]["balance_after"] == items[-1]["amount"]  # the account started at zero


def test_statement_is_scoped_to_account_owner(client, signup):
    alice, bob = signup("alice"), signup("bob")
    a = open_account(client, alice)
    deposit(client, alice, a, 1_000)

    assert statement(client, bob, a).status_code == 404
    assert statement(client, alice, str(uuid.uuid4())).status_code == 404
    assert statement(client, alice, a).status_code == 200


def test_statement_endpoints_require_auth(client):
    assert client.get(f"/accounts/{uuid.uuid4()}/transactions").status_code == 401
    assert client.get(f"/transactions/{uuid.uuid4()}").status_code == 401


def test_empty_statement(client, signup):
    alice = signup("alice")
    a = open_account(client, alice)
    assert statement(client, alice, a).get_json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize(
    "params",
    [
        {"cursor": "!!!"},
        {"cursor": b64({"id": "x"})},
        {"cursor": b64([1, 2])},
        {"limit": 0},
        {"limit": 101},
        {"limit": "abc"},
    ],
)
def test_invalid_cursor_and_limits_rejected(client, signup, params):
    alice = signup("alice")
    a = open_account(client, alice)
    assert statement(client, alice, a, **params).status_code == 422


def test_transaction_detail_visible_to_participants_only(client, signup):
    alice, bob, carol = signup("alice"), signup("bob"), signup("carol")
    a, b = open_account(client, alice), open_account(client, bob)
    deposit(client, alice, a, 5_000)
    txn_id = transfer(client, alice, a, b, 2_000)["transaction_id"]

    mine = client.get(f"/transactions/{txn_id}", headers=alice).get_json()
    assert mine["type"] == "transfer"
    assert [
        (e["direction"], e["amount"], e["balance_after"], e["counterparty_account_id"])
        for e in mine["entries"]
    ] == [("debit", 2_000, 3_000, b)]

    theirs = client.get(f"/transactions/{txn_id}", headers=bob).get_json()
    assert [
        (e["direction"], e["balance_after"], e["counterparty_account_id"])
        for e in theirs["entries"]
    ] == [("credit", 2_000, a)]

    assert client.get(f"/transactions/{txn_id}", headers=carol).status_code == 404


def test_transaction_detail_for_transfer_between_own_accounts(client, signup):
    alice = signup("alice")
    savings, current = open_account(client, alice), open_account(client, alice, "current")
    deposit(client, alice, savings, 4_000)
    txn_id = transfer(client, alice, savings, current, 1_500)["transaction_id"]

    body = client.get(f"/transactions/{txn_id}", headers=alice).get_json()
    assert sorted((e["direction"], e["amount"]) for e in body["entries"]) == [
        ("credit", 1_500),
        ("debit", 1_500),
    ]


def test_unknown_transaction_is_404(client, signup):
    alice = signup("alice")
    assert client.get(f"/transactions/{uuid.uuid4()}", headers=alice).status_code == 404