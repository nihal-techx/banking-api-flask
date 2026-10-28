import uuid


def create(client, headers, account_type="savings"):
    return client.post("/accounts", json={"account_type": account_type}, headers=headers)


def test_create_account(client, signup):
    response = create(client, signup("alice"))
    assert response.status_code == 201
    body = response.get_json()
    assert body["balance"] == 0
    assert body["currency"] == "INR"
    assert body["account_type"] == "savings"
    assert "owner_id" not in body


def test_list_returns_only_own_accounts(client, signup):
    alice, bob = signup("alice"), signup("bob")
    create(client, alice)
    create(client, alice, "current")
    create(client, bob)
    assert len(client.get("/accounts", headers=alice).get_json()["items"]) == 2
    assert len(client.get("/accounts", headers=bob).get_json()["items"]) == 1


def test_other_users_account_is_404_and_indistinguishable_from_missing(client, signup):
    alice, bob = signup("alice"), signup("bob")
    account_id = create(client, alice).get_json()["id"]

    foreign = client.get(f"/accounts/{account_id}", headers=bob)
    missing = client.get(f"/accounts/{uuid.uuid4()}", headers=bob)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.get_json() == missing.get_json()
    assert client.get(f"/accounts/{account_id}", headers=alice).status_code == 200


def test_accounts_require_auth(client):
    assert client.get("/accounts").status_code == 401
    assert client.post("/accounts", json={"account_type": "savings"}).status_code == 401
    assert client.get(f"/accounts/{uuid.uuid4()}").status_code == 401


def test_client_cannot_set_balance_or_owner(client, signup):
    alice = signup("alice")
    response = client.post(
        "/accounts",
        json={"account_type": "savings", "balance": 999999, "owner_id": str(uuid.uuid4())},
        headers=alice,
    )
    assert response.status_code == 422
    assert client.get("/accounts", headers=alice).get_json()["items"] == []


def test_invalid_account_type_rejected(client, signup):
    response = create(client, signup("alice"), "premium")
    assert response.status_code == 422


def test_malformed_account_id_rejected(client, signup):
    response = client.get("/accounts/not-a-uuid", headers=signup("alice"))
    assert response.status_code == 422
