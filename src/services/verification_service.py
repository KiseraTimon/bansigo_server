# src/services/verification_service.py

"""
responsible for generating one-time codes for:
    - email verification
    - password resets
"""

import hashlib
import hmac
import math
import secrets
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from src.exceptions import AppError, TooManyRequestsError
from src.models import TokenPurpose, User, VerificationToken
from src.repositories import UserRepository, VerificationTokenRepository
from src.security import hash_password_async
from utilities import Mail, utc_now


# constants
_BAD_CODE = "Invalid or expired code"


class VerificationService:
    def __init__(self, db: AsyncSession, settings: Settings):
        """
        constructor
        :param db: AsyncSession
        :param settings: Settings
        """

        self.db = db
        self.settings = settings
        self.users = UserRepository(db)
        self.tokens = VerificationTokenRepository(db)


    def _hash(self, user_id: int, purpose: TokenPurpose, code: str) -> str:
        """
        binds the user to the purpose to prevent multi-purpose codes
        :param user_id: int
        :param purpose: TokenPurpose
        :param code: str
        :return: str
        """

        key = self.settings.secret_key.get_secret_value().encode()
        return hmac.new(key, f"{purpose.value}:{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


    async def issue_code(self, user: User, purpose: TokenPurpose) -> str:
        """
        creates/replaces the user's code for a 'purpose'
        :param user: User
        :param purpose: TokenPurpose
        :return: str
        """

        now = utc_now()

        existing = await self.tokens.get(user.id, purpose)
        if existing is not None:
            cooldown = timedelta(seconds=self.settings.verification_resend_cooldown_seconds)
            remaining = (existing.created_at + cooldown - now).total_seconds()

            if remaining > 0:
                raise TooManyRequestsError(
                    retry_after=math.ceil(remaining),
                    detail=f"Please wait {math.ceil(remaining)}s before requesting another code"
                )

            # one live code per user + purpose
            await self.tokens.delete_for(user.id, purpose)

        length = self.settings.verification_code_length
        code = f"{secrets.randbelow(10 ** length):0{length}d}"
        self.db.add(VerificationToken(
            user_id=user.id,
            purpose=purpose,
            code_hash=self._hash(user.id, purpose, code),
            created_at=now,
            expires_at=now + timedelta(minutes=self.settings.verification_code_ttl_minutes)
        ))

        await self.db.commit()
        return code


    async def consume_code(self, user: User, purpose: TokenPurpose, code: str) -> None:
        """
        processes code usage.
        raises AppError if code is not live and unexpired.
        :param user: User
        :param purpose: TokenPurpose
        :param code: str
        :return: None
        """

        token = await self.tokens.get(user.id, purpose)
        if token is None:
            raise AppError(_BAD_CODE)

        if utc_now() > token.expires_at:
            await self.tokens.delete_for(user.id, purpose)
            await self.db.commit()

            raise AppError("This code has expired. Request a new one")

        if not hmac.compare_digest(token.code_hash, self._hash(user.id, purpose, code)):
            token.attempts += 1
            if token.attempts >= self.settings.verification_max_attempts:
                await self.tokens.delete_for(user.id, purpose)
                await self.db.commit()

                raise AppError("Too many incorrect attempts. Request a new code.")

            await self.db.commit()
            raise AppError("Incorrect code")

        # codes a are single-use
        await self.tokens.delete_for(user.id, purpose)


    async def start_email_verification(self, user: User) -> Mail:
        """
        initiates email verifications
        :param user: User
        :return: Mail
        """

        if user.is_verified:
            raise AppError("Email is already verified")

        code = await self.issue_code(user, TokenPurpose.VERIFY_EMAIL)
        return self._compose(user, code, "Verify your email", "verify your email address")


    async def confirm_mail(self, user: User, code: str) -> User:
        """
        processes emails verifications
        :param user: User
        :param code: str
        :return: User
        """

        await self.consume_code(user, TokenPurpose.VERIFY_EMAIL, code)
        user.is_verified = True

        await self.db.commit()
        await self.db.refresh(user)

        return user


    async def start_password_reset(self, email: str) -> Mail | None:
        """
        initiates password resets
        :param email: str
        :return: Mail | None
        """

        user = await self.users.find_by_login(email)
        if (user is None) or (user.deleted_at is not None):
            return None

        try:
            code = await self.issue_code(user, TokenPurpose.RESET_PASSWORD)

        except TooManyRequestsError:
            return None

        return self._compose(user, code, "Reset your password", "reset your password")


    async def reset_password(self, email: str, code: str, new_password: str) -> None:
        """
        processes account password resets
        :param email: str
        :param code: str
        :param new_password: str
        :return: None
        """

        user = await self.users.find_by_login(email)
        if (user is None) or (user.deleted_at is not None):
            raise AppError(_BAD_CODE)

        await self.consume_code(user, TokenPurpose.RESET_PASSWORD, code)
        user.password_hash = await hash_password_async(new_password)
        user.is_verified = True

        await self.db.commit()


    def _compose(self, user: User, code: str, subject: str, action: str) -> Mail:
        """
        composes the mail body
        :param user: User
        :param code: str
        :param subject: str
        :param action: str
        :return: Mail
        """

        ttl = self.settings.verification_code_ttl_minutes
        app = self.settings.app_name

        return Mail(
            to=user.email,
            subject=f"{app}: {subject}",
            body=(
                f"Hi {user.first_name},\n\n"
                f"Use this code to {action}:\n\n   {code}\n\n"
                f"It expires in {ttl} minutes. If you did not ask for this, you can ignore this email"
            )
        )
