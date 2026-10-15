import uuid

from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_openapi3 import APIBlueprint, Tag

from app.api.idempotency import run_idempotent
from app.schemas.money import TransferBody, TransferOut
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


@bp.post("/transfers", responses={"201": TransferOut})
def create_transfer(body: TransferBody):
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