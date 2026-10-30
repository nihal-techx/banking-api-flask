from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from flask_openapi3 import APIBlueprint, Tag

from app.api.docs import api_responses
from app.errors import AuthenticationError
from app.schemas.auth import LoginBody, RegisterBody, TokenOut, UserOut
from app.services import auth_service, rate_limit_service, token_service

bp = APIBlueprint("auth", __name__, url_prefix="/auth", abp_tags=[Tag(name="auth")])


@bp.post(
    "/register",
    responses=api_responses({"201": UserOut}, "409", "429", protected=False),
)
def register(body: RegisterBody):
    """Create a user

    Emails are case-insensitive. Passwords are 8 to 128 characters and are stored
    hashed (Argon2id). Rate-limited per client IP.
    """
    rate_limit_service.check_register()
    user = auth_service.register_user(body.email, body.username, body.password)
    return UserOut.model_validate(user).model_dump(mode="json"), 201


@bp.post(
    "/login",
    responses=api_responses({"200": TokenOut}, "401", "429", protected=False),
)
def login(body: LoginBody):
    """Exchange credentials for tokens

    Returns a short-lived access token and a single-use refresh token. Unknown email
    and wrong password return the identical error, so accounts cannot be enumerated.
    Rate-limited per client IP and per IP and email: wait for `Retry-After` seconds.
    """
    rate_limit_service.check_login(body.email)
    user = auth_service.authenticate(body.email, body.password)
    return auth_service.issue_tokens(user).model_dump(), 200


@bp.post(
    "/refresh",
    security=[{"jwt": []}],
    responses=api_responses({"200": TokenOut}),
)
@jwt_required(refresh=True)
def refresh():
    """Rotate tokens

    Send the refresh token as the bearer token. It is single-use. Presenting an
    already-used refresh token revokes the whole session (`token_revoked`).
    """
    claims = get_jwt()
    user = auth_service.get_user(get_jwt_identity())
    if not token_service.consume_token(claims["jti"], claims["exp"]):
        # Lost the race against another use of the same refresh token.
        token_service.revoke_family(claims["fid"])
        raise AuthenticationError("Refresh token already used")
    return auth_service.issue_tokens(user, family_id=claims["fid"]).model_dump()


@bp.post("/logout", security=[{"jwt": []}], responses=api_responses({}))
@jwt_required()
def logout():
    """Revoke the current session

    Invalidates both the access and the refresh token. Returns 204 with no body.
    """
    token_service.revoke_family(get_jwt()["fid"])
    return "", 204


@bp.get("/me", security=[{"jwt": []}], responses=api_responses({"200": UserOut}))
@jwt_required()
def me():
    """The authenticated user"""
    user = auth_service.get_user(get_jwt_identity())
    return UserOut.model_validate(user).model_dump(mode="json")
