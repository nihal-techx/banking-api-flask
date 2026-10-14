from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from flask_openapi3 import APIBlueprint, Tag

from app.errors import AuthenticationError
from app.schemas.auth import LoginBody, RegisterBody, TokenOut, UserOut
from app.services import auth_service, token_service

bp = APIBlueprint("auth", __name__, url_prefix="/auth", abp_tags=[Tag(name="auth")])


@bp.post("/register", responses={"201": UserOut})
def register(body: RegisterBody):
    user = auth_service.register_user(body.email, body.username, body.password)
    return UserOut.model_validate(user).model_dump(mode="json"), 201


@bp.post("/login", responses={"200": TokenOut})
def login(body: LoginBody):
    user = auth_service.authenticate(body.email, body.password)
    return auth_service.issue_tokens(user).model_dump(), 200


@bp.post("/refresh", security=[{"jwt": []}], responses={"200": TokenOut})
@jwt_required(refresh=True)
def refresh():
    claims = get_jwt()
    user = auth_service.get_user(get_jwt_identity())
    if not token_service.consume_token(claims["jti"], claims["exp"]):
        # Lost the race against another use of the same refresh token.
        token_service.revoke_family(claims["fid"])
        raise AuthenticationError("Refresh token already used")
    return auth_service.issue_tokens(user, family_id=claims["fid"]).model_dump()


@bp.post("/logout", security=[{"jwt": []}])
@jwt_required()
def logout():
    token_service.revoke_family(get_jwt()["fid"])
    return "", 204


@bp.get("/me", security=[{"jwt": []}], responses={"200": UserOut})
@jwt_required()
def me():
    user = auth_service.get_user(get_jwt_identity())
    return UserOut.model_validate(user).model_dump(mode="json")