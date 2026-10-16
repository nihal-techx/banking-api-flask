from app.services import token_service

CREDS = {"email": "alice@example.com", "username": "alice", "password": "s3cret-pass-1"}


def test_concurrent_refresh_with_one_token_succeeds_exactly_once(
    app, client, run_concurrently, monkeypatch
):
    assert client.post("/auth/register", json=CREDS).status_code == 201
    login = client.post(
        "/auth/login", json={"email": CREDS["email"], "password": CREDS["password"]}
    )
    refresh_headers = {"Authorization": f"Bearer {login.get_json()['refresh_token']}"}

    def attempt():
        return app.test_client().post("/auth/refresh", headers=refresh_headers)

    # Switch off the "already revoked?" pre-check so every request reaches the atomic
    # consume step. That step alone must then decide the winner.
    with monkeypatch.context() as patch:
        patch.setattr(token_service, "is_revoked", lambda payload: False)
        results = run_concurrently([attempt for _ in range(6)])

    responses = [value for kind, value in results if kind == "ok"]
    assert len(responses) == 6
    winners = [r for r in responses if r.status_code == 200]
    losers = [r for r in responses if r.status_code == 401]
    assert len(winners) == 1 and len(losers) == 5
    assert {r.get_json()["error"]["code"] for r in losers} == {"unauthorized"}

    # Losing the race is treated as token theft: the whole session is revoked,
    # including the new tokens the winner just received.
    new_access = winners[0].get_json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 401
    assert me.get_json()["error"]["code"] == "token_revoked"