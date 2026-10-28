import pytest
from sqlalchemy import func, select, text

from app import tasks
from app.extensions import db
from app.models import OutboxEvent
from app.notifications import build_messages
from app.services import outbox_service


class Spy:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


@pytest.fixture
def spy(monkeypatch):
    recorder = Spy()
    monkeypatch.setattr(tasks, "notifier", recorder)
    return recorder


def open_account(client, headers):
    response = client.post("/accounts", json={"account_type": "savings"}, headers=headers)
    return response.get_json()["id"]


def deposit(client, headers, account_id, amount, key=None):
    merged = {**headers, **({"Idempotency-Key": key} if key else {})}
    return client.post(f"/accounts/{account_id}/deposits", json={"amount": amount}, headers=merged)


def withdraw(client, headers, account_id, amount):
    return client.post(
        f"/accounts/{account_id}/withdrawals", json={"amount": amount}, headers=headers
    )


def transfer(client, headers, from_id, to_id, amount):
    body = {"from_account_id": from_id, "to_account_id": to_id, "amount": amount}
    return client.post("/transfers", json=body, headers=headers)


def count_events(db_session, pending_only=False):
    stmt = select(func.count()).select_from(OutboxEvent)
    if pending_only:
        stmt = stmt.where(OutboxEvent.published_at.is_(None))
    return db_session.scalar(stmt)


def test_posting_writes_one_outbox_event_atomically(client, signup, db_session):
    alice = signup("alice")
    a = open_account(client, alice)
    assert deposit(client, alice, a, 5_000).status_code == 201

    event = db_session.scalars(select(OutboxEvent)).one()
    assert event.event_type == "transaction.posted"
    assert event.published_at is None
    assert event.payload["type"] == "deposit"
    assert sorted(
        (e["direction"], e["amount"], e["owner_id"] is None) for e in event.payload["entries"]
    ) == [("credit", 5_000, False), ("debit", 5_000, True)]


def test_failed_posting_writes_no_event(client, signup, db_session):
    alice = signup("alice")
    a = open_account(client, alice)
    assert deposit(client, alice, a, 1_000).status_code == 201
    assert withdraw(client, alice, a, 5_000).status_code == 422

    assert count_events(db_session) == 1  # only the deposit's event


def test_idempotent_replay_emits_no_second_event(client, signup, db_session):
    alice = signup("alice")
    a = open_account(client, alice)
    assert deposit(client, alice, a, 1_000, key="k-1").status_code == 201
    assert deposit(client, alice, a, 1_000, key="k-1").status_code == 201

    assert count_events(db_session) == 1


def test_relay_publishes_marks_and_notifies(client, signup, db_session, spy):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)
    deposit(client, alice, a, 10_000)
    transfer(client, alice, a, b, 2_500)

    assert outbox_service.publish_pending() == 2
    assert count_events(db_session, pending_only=True) == 0

    texts = [m.text for m in spy.messages]
    assert len(texts) == 3  # deposit: the customer; transfer: sender and receiver
    assert any("credited" in t and "INR 100.00" in t for t in texts)
    assert any("debited" in t and "INR 25.00" in t for t in texts)
    assert any("credited" in t and "INR 25.00" in t for t in texts)


def test_relay_with_nothing_pending(db_session):
    assert outbox_service.publish_pending() == 0


def test_broker_outage_keeps_money_moving_and_events_pending(
    client, signup, db_session, spy, monkeypatch
):
    alice = signup("alice")
    a = open_account(client, alice)
    original_publish = outbox_service._publish

    def broker_down(event):
        raise ConnectionError("broker is down")

    monkeypatch.setattr(outbox_service, "_publish", broker_down)

    # The request path never touches the broker, so money still moves.
    assert deposit(client, alice, a, 5_000).status_code == 201
    assert client.get(f"/accounts/{a}", headers=alice).get_json()["balance"] == 5_000

    with pytest.raises(ConnectionError):
        outbox_service.publish_pending()
    assert count_events(db_session, pending_only=True) == 1  # nothing lost
    assert spy.messages == []

    monkeypatch.setattr(outbox_service, "_publish", original_publish)  # broker is back
    assert outbox_service.publish_pending() == 1
    assert len(spy.messages) == 1


def test_duplicate_delivery_is_deduplicated(app, spy):
    payload = {
        "transaction_id": "t-1",
        "type": "deposit",
        "entries": [
            {
                "account_id": "0000-abcd",
                "owner_id": "user-1",
                "direction": "credit",
                "amount": 100,
                "balance_after": 100,
            }
        ],
    }
    tasks.send_transaction_notifications(42, payload)
    tasks.send_transaction_notifications(42, payload)  # the relay re-published it
    assert len(spy.messages) == 1

    tasks.send_transaction_notifications(43, payload)  # a different event
    assert len(spy.messages) == 2


def test_relay_skips_rows_locked_by_another_relay(client, signup, db_session, spy):
    alice = signup("alice")
    a = open_account(client, alice)
    deposit(client, alice, a, 1_000)
    deposit(client, alice, a, 2_000)
    first_id = db_session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id)).first()

    with db.engine.connect() as other_relay, other_relay.begin():
        other_relay.execute(
            text("SELECT 1 FROM outbox_events WHERE id = :id FOR UPDATE"), {"id": first_id}
        )
        assert outbox_service.publish_pending() == 1  # skipped the locked row, did not wait

    assert outbox_service.publish_pending() == 1  # picked up once the lock was released
    assert len(spy.messages) == 2


@pytest.mark.parametrize(
    "amount,expected",
    [(5, "INR 0.05"), (100, "INR 1.00"), (123_456, "INR 1,234.56")],
)
def test_messages_format_money_without_floats(amount, expected):
    payload = {
        "type": "deposit",
        "entries": [
            {
                "account_id": "x-1234",
                "owner_id": "user-1",
                "direction": "credit",
                "amount": amount,
                "balance_after": amount,
            },
            {
                "account_id": "sys-0000",
                "owner_id": None,
                "direction": "debit",
                "amount": amount,
                "balance_after": -amount,
            },
        ],
    }
    messages = build_messages(payload)
    assert len(messages) == 1  # the system account is never notified
    assert expected in messages[0].text


def test_relay_cli_command(app, client, signup, db_session, spy):
    alice = signup("alice")
    a = open_account(client, alice)
    deposit(client, alice, a, 1_000)

    result = app.test_cli_runner().invoke(args=["outbox-relay", "--once"])
    assert result.exit_code == 0, result.output
    assert "published 1" in result.output
    assert len(spy.messages) == 1
