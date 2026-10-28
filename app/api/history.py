import uuid

from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_openapi3 import APIBlueprint, Tag

from app.api.docs import api_responses
from app.schemas.accounts import AccountPath
from app.schemas.history import (
    StatementItem,
    StatementOut,
    StatementQuery,
    TransactionDetailOut,
    TransactionPath,
)
from app.services import history_service

bp = APIBlueprint(
    "history",
    __name__,
    abp_tags=[Tag(name="history")],
    abp_security=[{"jwt": []}],
)


@bp.before_request
def require_auth():
    verify_jwt_in_request()


def current_user_id() -> uuid.UUID:
    return uuid.UUID(get_jwt_identity())


def to_item(row) -> StatementItem:
    entry, txn_type, counterparty_id = row
    return StatementItem(
        transaction_id=entry.transaction_id,
        type=txn_type,
        direction=entry.direction,
        amount=entry.amount,
        balance_after=entry.balance_after,
        counterparty_account_id=counterparty_id,
        created_at=entry.created_at,
    )


@bp.get(
    "/accounts/<account_id>/transactions",
    responses=api_responses({"200": StatementOut}, "404", "422"),
)
def account_statement(path: AccountPath, query: StatementQuery):
    """Account statement

    Newest first, with the running balance on every row. Paginated with an opaque
    cursor: pass `next_cursor` from the previous page as `cursor`. A null
    `next_cursor` means there are no more pages.
    """
    rows, next_cursor = history_service.get_statement(
        current_user_id(), path.account_id, query.limit, query.cursor
    )
    return StatementOut(items=[to_item(row) for row in rows], next_cursor=next_cursor).model_dump(
        mode="json"
    )


@bp.get(
    "/transactions/<transaction_id>",
    responses=api_responses({"200": TransactionDetailOut}, "404", "422"),
)
def transaction_detail(path: TransactionPath):
    """Transaction detail

    Returns only your side of the transaction. Returns 404 if you were not a party to it.
    """
    rows = history_service.get_transaction(current_user_id(), path.transaction_id)
    first_entry, txn_type, _ = rows[0]
    return TransactionDetailOut(
        transaction_id=path.transaction_id,
        type=txn_type,
        created_at=first_entry.created_at,
        entries=[to_item(row) for row in rows],
    ).model_dump(mode="json")
