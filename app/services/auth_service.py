import uuid

from flask import current_app
from flask_jwt_extended import create_access_token, create_refresh_token
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.errors import AuthenticationError, ConflictError
from app.extensions import db
from app.models import User
from app.schemas.auth import TokenOut
from app.security import hash_password, verify_password

# Verified against when the email is unknown, so both login paths cost the same time.
_DUMMY_HASH = hash_password("not-a-real-password")


def register_user(email: str, username: str, password: str) -> User:
    user = User(email=email, username=username, password_hash=hash_password(password))
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ConflictError("Email or username already registered")
    return user


def authenticate(email: str, password: str) -> User:
    user = db.session.scalar(select(User).where(User.email == email))
    password_ok = verify_password(user.password_hash if user else _DUMMY_HASH, password)
    if user is None or not password_ok:
        raise AuthenticationError("Invalid email or password")
    return user


def issue_tokens(user: User) -> TokenOut:
    identity = str(user.id)
    expires = current_app.config["JWT_ACCESS_TOKEN_EXPIRES"]
    return TokenOut(
        access_token=create_access_token(identity=identity),
        refresh_token=create_refresh_token(identity=identity),
        expires_in=int(expires.total_seconds()),
    )


def get_user(user_id: str) -> User:
    user = db.session.get(User, uuid.UUID(user_id))
    if user is None:
        raise AuthenticationError("User no longer exists")
    return user