# src/schemas/auth.py

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from .types import Email, Password, Phone
from .user import UserPrivate


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


# social and OAuth schemas
class SocialAuthRequest(BaseModel):
    """
    payload sent by frontend when logging in with Firebase, Google, or Facebook
    """
    provider: Literal["firebase", "google", "facebook"] = "firebase"
    token: str = Field(min_length=1, description="Firebase ID token, Google ID token, or Facebook access token")
    phone: Phone | None = None


class SocialAuthResponse(BaseModel):
    """
    response returned upon successful OAuth/social authentication
    """
    access_token: str
    token_type: str = "bearer"
    user: UserPrivate
    is_new_user: bool = False
    requires_phone: bool = False


class PhoneCompleteRequest(BaseModel):
    """
    payload for social login users to complete their profile with their phone number
    """
    phone: Phone


class FirebasePublicConfig(BaseModel):
    """
    public Firebase configuration for client-side SDK initialization
    """
    api_key: str | None = None
    auth_domain: str
    project_id: str
    storage_bucket: str
    messaging_sender_id: str
    app_id: str
    measurement_id: str | None = None
