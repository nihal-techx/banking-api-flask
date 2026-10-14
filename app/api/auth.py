from flask_openapi3 import APIBlueprint, Tag

from app.schemas.auth import RegisterBody, UserOut
from app.services import auth_service

bp = APIBlueprint("auth", __name__, url_prefix="/auth", abp_tags=[Tag(name="auth")])


@bp.post("/register", responses={"201": UserOut})
def register(body: RegisterBody):
    user = auth_service.register_user(body.email, body.username, body.password)
    return UserOut.model_validate(user).model_dump(mode="json"), 201