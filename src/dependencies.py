# src/dependencies.py

from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings, get_settings
from src.database import get_db
from src.exceptions import ForbiddenError, UnauthorizedError
from src.repositories import UserRepository
from src.security import decode_access_token
from src.models import User, UserRole
from src.services import AuthService, UserService, VerificationService

from utilities import Mailer


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_auth_service(settings: SettingsDep, db: DbSession) -> AuthService:
    return AuthService(db, settings)


def get_user_service(db: DbSession) -> UserService:
    return UserService(db)


def get_verification_service(settings: SettingsDep, db: DbSession) -> VerificationService:
    return VerificationService(db, settings)


def get_mailer(settings: SettingsDep) -> Mailer:
    return Mailer(settings)


async def get_current_user(
        token: Annotated[str, Depends(oauth2_scheme)],
        settings: SettingsDep,
        db: DbSession
) -> User:
    """
    resolves the active user using the token
    :param token: OAuth2PasswordBearer
    :param settings: Settings
    :param db: AsyncSession
    :return:
    """

    try:
        payload = decode_access_token(token, settings.secret_key.get_secret_value())
        user_id = int(payload["sub"])

    except (jwt.PyJWTError, KeyError, ValueError):
        raise UnauthorizedError()

    user = await UserRepository(db).get_by_id(user_id)
    if (user is None) or (not user.is_active) or (user.deleted_at is not None):
        raise UnauthorizedError()

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """
    role gate for child models
    :param roles: UserRole
    :return:
    """

    async def checker(user: CurrentUser) -> User:
        """
        :param user: CurrentUser
        :return: User
        """
        if user.role not in roles:
            raise ForbiddenError()

        return user

    return checker
