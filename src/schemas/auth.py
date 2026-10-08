# src/schemas/auth.py

from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from .types import Email, Password


class Token(BaseModel):
    """
    validation properties of a token
    """

    access_token: str
    token_type: str = "bearer"


class PasswordChange(BaseModel):
    """
    validation properties for a password change event
    """

    current_password: str
    new_password: Password
    new_password_confirm: str


    @model_validator(mode="after")
    def _match(self):
        """
        helper to check if passwords match
        :return:
        """

        if self.new_password != self.new_password_confirm:
            raise ValueError("passwords do not match")

        return self


class AccountDelete(BaseModel):
    """
    validation properties for an account deletion event.
    This is a destructive event requiring password re-confirmation
    """

    password: str


Code = Annotated[str, Field(pattern=r"^\d{4,10}$")]
class CodeConfirm(BaseModel):
    """
    validation properties for code confirmations
    """

    code: Code


class PasswordResetRequests(BaseModel):
    """
    validation properties for password reset requests
    """

    email: Email


class PasswordResetConfirm(BaseModel):
    """
    validation properties for password reset confirmations
    """

    email: Email
    code: Code
    new_password: Password
    new_password_confirm: str

    @model_validator(mode="after")
    def _match(self):
        if self.new_password != self.new_password_confirm:
            raise ValueError("passwords do not match")

        return self
