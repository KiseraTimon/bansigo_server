# src/routes/server/auth.py

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from src.dependencies import (
    get_auth_service,
    get_mailer,
    get_verification_service
)
from src.schemas import PasswordResetConfirm, PasswordResetRequests, Token, UserCreate, UserPrivate
from src.services import AuthService, VerificationService

from utilities import Mailer


# router object
router = APIRouter()

# service object dependencies
Auth = Annotated[AuthService, Depends(get_auth_service)]
Verification = Annotated[VerificationService, Depends(get_verification_service)]
Mail = Annotated[Mailer, Depends(get_mailer)]


@router.post("/signup", response_model=UserPrivate, status_code=status.HTTP_201_CREATED)
async def signup(data: UserCreate, auth: Auth):
    """
    route to create a customer's account
    :param data: UserCreate
    :param auth: AuthService
    :return:
    """

    return await auth.register(data)


@router.post("/login", response_model=Token)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], auth: Auth):
    """
    route to authenticates a user into the system
    :param form: OAuth2PasswordRequestForm
    :param auth: AuthService
    :return:
    """

    user = await auth.authenticate(form.username, form.password)
    return Token(access_token=auth.issue_token(user), token_type="bearer")


@router.post("/reactivate", response_model=UserPrivate)
async def reactivate(form: Annotated[OAuth2PasswordRequestForm, Depends()], auth: Auth):
    """
    route to re-enable self-deactivated user accounts
    :param form: OAuth2PasswordRequestForm
    :param auth: AuthService
    :return:
    """

    return await auth.reactivate(form.username, form.password)


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
        data: PasswordResetRequests,
        verification: Verification,
        mailer: Mail,
        background: BackgroundTasks
):
    """
    handles requests for password resets
    :param data: PasswordResetRequest
    :param verification: VerificationService
    :param mailer: Mailer
    :param background: BackgroundTasks
    :return:
    """

    mail = await verification.start_password_reset(data.email)
    if mail:
        background.add_task(mailer.send, mail)

    return {"detail": "if the email is registered, a reset code has been sent to it"}


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(data: PasswordResetConfirm, verification: Verification):
    """
    processes password resets
    :param data: PasswordResetConfirm
    :param verification: VerificationService
    :return:
    """

    await verification.reset_password(data.email, data.code, data.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
