# src/services/auth_service.py

"""
centralized service for authentication operations i.e.
sign in, sign up, re-activate, change password.
"""

import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from src.exceptions import (
    AccountInactiveError,
    AppError,
    ConflictError,
    InvalidCredentialsError
)
from src.models import Customer, User, UserRole
from src.repositories import UserRepository
from src.schemas import PasswordChange, UserCreate
from src.schemas.types import USERNAME_MAX
from src.security import (
    create_access_token,
    hash_password_async,
    needs_rehash,
    verify_password_async
)

class AuthService:
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings
    ):
        """
        constructor
        :param db: AsyncSession
        :param settings: Settings
        """
        self.db = db
        self.settings = settings
        self.users = UserRepository(db)


    async def register(self, data: UserCreate, role: UserRole = UserRole.CUSTOMER) -> User:
        """
        creates an account
        :param data: UserCreate
        :param role: UserRole
        :return: User
        """

        taken = await self.users.conflicting_fields(
            username=data.username, email=data.email, phone=data.phone
        )

        if taken:
            raise ConflictError(taken)

        user = User(
            first_name=data.first_name,
            last_name=data.last_name,
            username=data.username or await self._generate_username(data.first_name, data.last_name),
            email=data.email,
            phone=data.phone,
            role=role,
            password_hash=await hash_password_async(data.password)
        )
        self._attach_role_profile(user)

        self.db.add(user)
        try:
            await self.db.commit()
        except IntegrityError:
            """
            This error occurs when:
                Two people registered the same email/phone/username at the same moment
                and both passed the conflict check above, but the UNIQUE constrained
                stopped the operation
            """

            await self.db.rollback()
            raise ConflictError(["username, email, or phone"])

        await self.db.refresh(user)
        return user

    @staticmethod
    def _attach_role_profile(user: User) -> None:
        """
        creates the empty 1:1 profile row for the user's role; saved together with the user.
        :param user: User
        :return: None
        """

        if user.role is UserRole.CUSTOMER:
            user.customer = Customer()


    async def _generate_username(self, first_name: str, last_name: str) -> str:
        """
        generates custom usernames combining first names and last names, sometimes with numbers.
        :param first_name: str
        :param last_name: str
        :return: str
        """

        base = re.sub(
            r"[^a-z0-9]",
            "",
            f"{first_name}{last_name}".lower()
        )[: USERNAME_MAX -4]

        if len(base) < 3:
            base = f"{base}user"

        existing = await self.users.usernames_with_prefix(base)
        if base not in existing:
            return base

        n = 2
        while f"{base}{n}" in existing:
            n += 1

        return f"{base}{n}"


    async def _verify_credentials(self, identifier: str, password: str) -> User:
        """
        validates a user's identity
        :param identifier: str
        :param password: str
        :return: User
        """

        user = await self.users.find_by_login(identifier.strip().lower())

        # password check
        password_ok = await verify_password_async(password, user.password_hash)
        if user is None or not password_ok:
            raise InvalidCredentialsError()

        # hash upgrade for strengthened hash params
        if needs_rehash(user.password_hash):
            user.password_hash = await hash_password_async(password)

        return user


    async def authenticate(self, identifier: str, password: str) -> User:
        """
        login with username OR email AND password
        :param identifier: str
        :param password: str
        :return: User
        """

        user = await self._verify_credentials(identifier, password)
        if not user.is_active:
            # detail revealed only after password is validated to probe existing accounts
            raise AccountInactiveError("This account is deactivated. Reactivate it to continue")

        if (self.settings.require_verified_email) and (not user.is_verified):
            raise AccountInactiveError("Verify your email address to continue")

        user.last_login = datetime.now(timezone.utc)
        await self.db.commit()
        return user


    def issue_token(self, user: User) -> str:
        """
        access method to generate user tokens
        :param user: User
        :return: str
        """

        return create_access_token(
            user.id,
            self.settings.secret_key.get_secret_value(),
            self.settings.access_tokens_expire_minutes
        )


    async def reactivate(self, identifier: str, password: str) -> User:
        """
        undoes a self-deactivation of user accounts
        :param identifier: str
        :param password: str
        :return:
        """

        user = await self._verify_credentials(identifier, password)
        user.is_active = True
        await self.db.commit()
        return user


    async def change_password(self, user: User, data: PasswordChange) -> None:
        """
        modifies user account passwords
        :param user: User
        :param data: PasswordChange
        :return: None
        """

        if not await verify_password_async(data.current_password, user.password_hash):
            raise AppError("Current password is incorrect")

        if await verify_password_async(data.new_password, user.password_hash):
            raise AppError("New password must be different from the current one")

        user.password_hash = await hash_password_async(data.new_password)
        await self.db.commit()
