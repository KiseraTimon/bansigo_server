# src/services/auth_service.py

"""
centralized service for authentication operations i.e.
sign in, sign up, social sign in, re-activate, change password.
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
    InvalidCredentialsError,
    NotFoundError,
)
from src.helpers.oauth_verifier import OAuthUserPayload
from src.models import Customer, User, UserRole
from src.repositories import UserRepository
from src.schemas import PasswordChange, UserCreate
from src.schemas.types import USERNAME_MAX
from src.security import (
    create_access_token,
    hash_password_async,
    needs_rehash,
    verify_password_async,
)
from utilities import get_logger

log = get_logger(__name__)


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
        creates a manual account
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
            role=(data.role if hasattr(data, "role") and data.role else None) or role,
            password_hash=await hash_password_async(data.password),
            auth_provider="local"
        )
        self._attach_role_profile(user)

        self.db.add(user)
        try:
            await self.db.commit()
        except IntegrityError:
            """
            This error occurs when:
                Two people registered the same email/phone/username at the same moment
                and both passed the conflict check above, but the UNIQUE constraint
                stopped the operation
            """

            await self.db.rollback()
            raise ConflictError(["username, email, or phone"])

        await self.db.refresh(user)
        return user


    async def authenticate_social(
        self,
        payload: OAuthUserPayload
    ) -> tuple[User, bool]:
        """
        authenticates or provisions a customer using verified OAuth data.
        returns (user, is_new_user).
        """
        # 1. Lookup by federated provider UID if set
        user: User | None = None
        if payload.uid:
            user = await self.users.find_by_firebase_uid(payload.uid)

        # 2. If not found by UID, lookup by verified email
        if user is None:
            user = await self.users.find_by_email(payload.email)

        # 3. If existing user found: link and update profile attributes
        if user is not None:
            if not user.is_active:
                raise AccountInactiveError("This account is deactivated. Reactivate it to continue")

            # link federated UID if not already set
            if user.firebase_uid is None and payload.uid:
                user.firebase_uid = payload.uid

            # mark verified if social provider verified email
            if payload.email_verified and not user.is_verified:
                user.is_verified = True

            # update picture if user does not have one
            if user.picture is None and payload.picture:
                user.picture = payload.picture

            # attach phone if user lacks one and phone was supplied
            if user.phone is None and payload.phone:
                taken = await self.users.conflicting_fields(phone=payload.phone, exclude_id=user.id)
                if not taken:
                    user.phone = payload.phone

            user.last_login = datetime.now(timezone.utc)
            await self.db.commit()
            await self.db.refresh(user)
            log.info("Social user logged in: user_id=%s, email=%s, provider=%s", user.id, user.email, payload.provider)
            return user, False

        # 4. New user registration
        # generate a unique username from their name
        username = await self._generate_username(payload.first_name, payload.last_name)

        # check phone conflict if phone was supplied
        phone_to_set = payload.phone
        if phone_to_set:
            taken = await self.users.conflicting_fields(phone=phone_to_set)
            if taken:
                phone_to_set = None

        user = User(
            first_name=payload.first_name,
            last_name=payload.last_name,
            username=username,
            email=payload.email,
            phone=phone_to_set,
            picture=payload.picture,
            password_hash=None,
            role=UserRole.CUSTOMER,
            is_active=True,
            is_verified=payload.email_verified,
            auth_provider=payload.provider,
            firebase_uid=payload.uid,
            last_login=datetime.now(timezone.utc)
        )
        self._attach_role_profile(user)

        self.db.add(user)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            existing = await self.users.find_by_email(payload.email)
            if existing:
                return existing, False
            raise ConflictError(["email or username"])

        await self.db.refresh(user)
        log.info("New social user registered: user_id=%s, email=%s, provider=%s", user.id, user.email, payload.provider)
        return user, True


    async def complete_phone(self, user: User, phone: str) -> User:
        """
        attaches a phone number to a user account (e.g. following social login).
        """
        if user.phone == phone:
            return user

        taken = await self.users.conflicting_fields(phone=phone, exclude_id=user.id)
        if taken:
            raise ConflictError(["phone"])

        user.phone = phone
        await self.db.commit()
        await self.db.refresh(user)
        log.info("User phone completed: user_id=%s, phone=%s", user.id, phone)
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
        elif user.role is UserRole.RIDER:
            from src.models.rider import Rider
            user.rider = Rider()


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

        # accounts without local passwords (social sign-in) or non-existent users
        if user is None or not user.password_hash:
            raise InvalidCredentialsError()

        # password check
        password_ok = await verify_password_async(password, user.password_hash)
        if not password_ok:
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

        if not user.password_hash:
            # Set initial password for social account
            user.password_hash = await hash_password_async(data.new_password)
            await self.db.commit()
            return

        if not await verify_password_async(data.current_password, user.password_hash):
            raise AppError("Current password is incorrect")

        if await verify_password_async(data.new_password, user.password_hash):
            raise AppError("New password must be different from the current one")

        user.password_hash = await hash_password_async(data.new_password)
        await self.db.commit()
