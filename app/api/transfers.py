import uuid

from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_openapi3 import APIBlueprint, Tag

from app.api.docs import api_responses
from app.api.idempotency import run_idempotent
from app.schemas.money import IdempotencyHeader, TransferBody, TransferOut
from app.services import money_service

bp = APIBlueprint(
    "transfers",
    __name__,
    abp_tags=[Tag(name="transfers")],
    abp_security=[{"jwt": []}],
)


@bp.before_request
def require_auth():
    verify_jwt_in_request()


@bp.post(
    "/transfers",
    responses=api_responses({"201": TransferOut}, "400", "404", "422"),
)
def create_transfer(header: IdempotencyHeader, body: TransferBody):
    """Transfer money between accounts

    The source must be one of your accounts; the destination can be any customer
    account. Debit and credit commit atomically. Returns 404 if the source is not
    yours or the destination does not exist. Safe to retry with an `Idempotency-Key`.
    """

    def operation(commit):
        entry = money_service.transfer(
            uuid.UUID(get_jwt_identity()),
            body.from_account_id,
            body.to_account_id,
            body.amount,
            commit=commit,
        )
        return TransferOut(
            transaction_id=entry.transaction_id,
            from_account_id=body.from_account_id,
            to_account_id=body.to_account_id,
            amount=entry.amount,
            balance_after=entry.balance_after,
            created_at=entry.created_at,
        ).model_dump(mode="json")

    return run_idempotent(operation, body.model_dump(mode="json"))
