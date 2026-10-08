# src/schemas/user.py

from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict, model_validator

from src.models.user import UserRole
from src.schemas.types import  Email, Name, Password, Phone, Username


class UserBase(BaseModel):
    """
    shared profile details
    """
    first_name: Name
    last_name: Name
    email: Email
    phone: Phone


class UserCreate(UserBase):
    """
    validation requirements for new account creations
    """
    model_config = ConfigDict(extra="forbid")

    username: Username | None = None
    password: Password
    password_confirm: str

    @model_validator(mode="after")
    def _passwords_match(self):
        """
        password match validation
        :return:
        """

        if self.password != self.password_confirm:
            raise ValueError("passwords do not match")

        return self


class UserCreateByAdmin(UserCreate):
    """
    admin-only endpoint for account creation validations
    """
    role: UserRole


class UserUpdate(UserBase):
    """
    validation for user profile patches
    """
    model_config = ConfigDict(extra="forbid")



    first_name: Name | None = None
    last_name: Name | None = None
    username: Username | None = None
    email: Email | None = None
    phone: Phone | None = None
    picture: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _validate_patch(self):
        """
        helper to validate user-provided inputs
        :return:
        """
        if not self.model_fields_set:
            raise ValueError("no fields provided")

        for field in self.model_fields_set - {"picture"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")

        return self


class UserPrivate(UserBase):
    """
    data available to the authenticated user only
    """

    id: int
    username: str
    role: UserRole
    picture: str | None
    is_verified: bool
    is_active: bool
    last_login: datetime | None
    created_at: datetime


class UserPublic(BaseModel):
    """
    data about the user accessible publicly through APIs
    """

    id: int
    username: str
    first_name: str
    picture: str | None
