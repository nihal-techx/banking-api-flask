import uuid

from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_openapi3 import APIBlueprint, Tag

from app.api.docs import api_responses
from app.api.idempotency import run_idempotent
from app.schemas.accounts import (
    AccountListOut,
    AccountOut,
    AccountPath,
    CreateAccountBody,
)
from app.schemas.money import AmountBody, IdempotencyHeader, TransactionOut
from app.services import account_service, money_service

bp = APIBlueprint(
    "accounts",
    __name__,
    abp_tags=[Tag(name="accounts")],
    abp_security=[{"jwt": []}],
)


@bp.before_request
def require_auth():
    verify_jwt_in_request()


def current_user_id() -> uuid.UUID:
    return uuid.UUID(get_jwt_identity())


def posting_response(entry):
    return TransactionOut(
        transaction_id=entry.transaction_id,
        type=entry.transaction.type,
        account_id=entry.account_id,
        amount=entry.amount,
        balance_after=entry.balance_after,
        created_at=entry.created_at,
    ).model_dump(mode="json")


@bp.post("/accounts", responses=api_responses({"201": AccountOut}, "422"))
def create_account(body: CreateAccountBody):
    """Open an account

    Accounts always open with a zero balance. The owner is the authenticated user,
    and the request cannot set a balance or an owner.
    """
    account = account_service.open_account(current_user_id(), body.account_type)
    return AccountOut.model_validate(account).model_dump(mode="json"), 201


@bp.get("/accounts", responses=api_responses({"200": AccountListOut}))
def list_accounts():
    """List your accounts"""
    accounts = account_service.list_accounts(current_user_id())
    return {"items": [AccountOut.model_validate(a).model_dump(mode="json") for a in accounts]}


@bp.get(
    "/accounts/<account_id>",
    responses=api_responses({"200": AccountOut}, "404", "422"),
)
def get_account(path: AccountPath):
    """Get one account

    Returns 404 both when the account does not exist and when it belongs to someone else.
    """
    account = account_service.get_owned_account(current_user_id(), path.account_id)
    return AccountOut.model_validate(account).model_dump(mode="json")


@bp.post(
    "/accounts/<account_id>/deposits",
    responses=api_responses({"201": TransactionOut}, "400", "404", "422"),
)
def create_deposit(path: AccountPath, header: IdempotencyHeader, body: AmountBody):
    """Deposit money

    Credits the account. Safe to retry with an `Idempotency-Key`.
    """

    def operation(commit):
        entry = money_service.deposit(
            current_user_id(), path.account_id, body.amount, commit=commit
        )
        return posting_response(entry)

    return run_idempotent(operation, body.model_dump(mode="json"))


@bp.post(
    "/accounts/<account_id>/withdrawals",
    responses=api_responses({"201": TransactionOut}, "400", "404", "422"),
)
def create_withdrawal(path: AccountPath, header: IdempotencyHeader, body: AmountBody):
    """Withdraw money

    Debits the account. Returns `insufficient_funds` (422) if the balance is too low.
    Safe to retry with an `Idempotency-Key`.
    """

    def operation(commit):
        entry = money_service.withdraw(
            current_user_id(), path.account_id, body.amount, commit=commit
        )
        return posting_response(entry)

    return run_idempotent(operation, body.model_dump(mode="json"))
