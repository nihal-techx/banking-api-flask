from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_openapi3 import APIBlueprint, Tag

from app.schemas.auth import LoginBody, RegisterBody, TokenOut, UserOut
from app.services import auth_service

bp = APIBlueprint("auth", __name__, url_prefix="/auth", abp_tags=[Tag(name="auth")])


@bp.post("/register", responses={"201": UserOut})
def register(body: RegisterBody):
    user = auth_service.register_user(body.email, body.username, body.password)
    return UserOut.model_validate(user).model_dump(mode="json"), 201


@bp.post("/login", responses={"200": TokenOut})
def login(body: LoginBody):
    user = auth_service.authenticate(body.email, body.password)
    return auth_service.issue_tokens(user).model_dump(), 200


@bp.get("/me", security=[{"jwt": []}], responses={"200": UserOut})
@jwt_required()
def me():
    user = auth_service.get_user(get_jwt_identity())
    return UserOut.model_validate(user).model_dump(mode="json")