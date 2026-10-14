import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Account, User


def make_user(email="a@example.com", username="alice"):
    return User(email=email, username=username, password_hash="x")


def test_create_user_with_account(db_session):
    user = make_user()
    db_session.add(user)
    db_session.flush()
    db_session.add(Account(owner_id=user.id, account_type="savings"))
    db_session.commit()

    account = db_session.query(Account).one()
    assert account.balance == 0
    assert account.currency == "INR"
    assert account.owner.email == "a@example.com"


def test_negative_balance_rejected_by_database(db_session):
    user = make_user()
    db_session.add(user)
    db_session.flush()
    db_session.add(Account(owner_id=user.id, account_type="savings", balance=-1))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_email_rejected_by_database(db_session):
    db_session.add(make_user(email="dup@example.com", username="one"))
    db_session.flush()
    db_session.add(make_user(email="dup@example.com", username="two"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_ready_checks_database(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ready"}        