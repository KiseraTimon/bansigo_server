# src/services/user_service.py

"""
module for user account management in events such as
profile patching, account deactivation, and account deletion.

only handles authenticated users
"""

import secrets
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import AppError, ConflictError
from src.models import User, VerificationToken
from src.repositories import UserRepository
from src.schemas import UserUpdate
from src.security import hash_password_async, verify_password_async


class UserService:
    """
    Provides methods for user account management i.e profile patching,
    account deactivation, and account deletion.
    """

    # constructor
    def __init__(self, db: AsyncSession):
        """
        constructor
        :param db: AsyncSession
        """
        self.db = db
        self.users = UserRepository(db)


    # profile patch
    async def update_profile(self, user: User, data: UserUpdate) -> User:
        """
        updates user details
        :param user: User
        :param data: UserUpdate
        :return: User
        """

        # mapping ONLY modified fields
        changes = data.model_dump(exclude_unset=True)

        # checking values that changed
        changed_unique = {
            field: value for field, value in changes.items()
            if field in ("username", "email", "phone") and value != getattr(user, field)
        }

        if changed_unique:
            taken = await self.users.conflicting_fields(**changed_unique, exclude_id=user.id)
            if taken:
                raise ConflictError(taken)

        # marking emails for re-verification
        if "email" in changed_unique:
            user.is_verified = False

        for field, value in changes.items():
            setattr(user, field, value)

        try:
            await self.db.commit()

        except IntegrityError:
            await self.db.rollback()
            raise ConflictError(["username, email or phone"])

        await self.db.refresh(user)
        return user


    # account deactivation
    async def deactivate(self, user: User) -> None:
        """
        reversible deactivation of user accounts
        :param user: User
        :return: None
        """

        user.is_active = False
        await self.db.commit()


    # account deletions
    async def delete_account(self, user: User, password: str) -> None:
        """
        anonymized, soft deletion of user accounts
        :param user: User
        :param password: str
        :return: None
        """

        if not await verify_password_async(password, user.password_hash):
            raise AppError("Password is incorrect")

        # Tombstone values; Unique per id, so UNIQUE constraints still hold
        user.username = f"deleted-{user.id}"
        user.email = f"deleted-{user.id}@deleted.invalid"
        user.phone = f"deleted-{user.id}"
        user.first_name = "Deleted"
        user.last_name = "User"
        user.picture = None
        user.password_hash = await hash_password_async(secrets.token_urlsafe(32))
        user.is_active = False
        user.is_verified = False
        user.deleted_at = datetime.now(timezone.utc)

        # clearing live verification/reset codes for deleted user
        await self.db.execute(
            delete(VerificationToken)
            .where(VerificationToken.user_id == user.id)
        )

        # TODO
        """
            scrub PII in the role profile (customer addresses, rider, license/vehicle etc.)
            but keep order/payment rows
        """

        await self.db.commit()


