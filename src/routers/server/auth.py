# src/routers/server/auth.py

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from src.dependencies import (
    CurrentUser,
    SettingsDep,
    get_auth_service,
    get_mailer,
    get_oauth_verifier,
    get_verification_service,
)
from src.helpers.oauth_verifier import OAuthVerifier
from src.schemas import (
    FirebasePublicConfig,
    PasswordResetConfirm,
    PasswordResetRequests,
    PhoneCompleteRequest,
    SocialAuthRequest,
    SocialAuthResponse,
    Token,
    UserCreate,
    UserPrivate,
)
from src.services import AuthService, VerificationService

from utilities import Mailer


# router object
router = APIRouter()

# service object dependencies
Auth = Annotated[AuthService, Depends(get_auth_service)]
Verification = Annotated[VerificationService, Depends(get_verification_service)]
Mail = Annotated[Mailer, Depends(get_mailer)]
Verifier = Annotated[OAuthVerifier, Depends(get_oauth_verifier)]


@router.post("/signup", response_model=UserPrivate, status_code=status.HTTP_201_CREATED)
async def signup(data: UserCreate, auth: Auth):
    """
    route to create a customer's account with standard credentials
    :param data: UserCreate
    :param auth: AuthService
    :return:
    """

    return await auth.register(data)


@router.post("/login", response_model=Token)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], auth: Auth):
    """
    route to authenticate a user into the system using username/email and password
    :param form: OAuth2PasswordRequestForm
    :param auth: AuthService
    :return:
    """

    user = await auth.authenticate(form.username, form.password)
    return Token(access_token=auth.issue_token(user), token_type="bearer")


@router.get("/firebase/config", response_model=FirebasePublicConfig)
async def get_firebase_config(settings: SettingsDep):
    """
    exposes public Firebase configuration for client-side JavaScript SDK initialization
    """
    return FirebasePublicConfig(
        api_key=settings.firebase_api_key.get_secret_value() if settings.firebase_api_key else None,
        auth_domain=settings.firebase_auth_domain,
        project_id=settings.firebase_project_id,
        storage_bucket=settings.firebase_storage_bucket,
        messaging_sender_id=settings.firebase_messaging_sender_id,
        app_id=settings.firebase_app_id,
        measurement_id=settings.firebase_measurement_id,
    )


@router.post("/social", response_model=SocialAuthResponse)
async def social_auth(data: SocialAuthRequest, auth: Auth, verifier: Verifier):
    """
    authenticates or registers a customer via Firebase, Google, or Facebook OAuth.
    Issues a local system JWT token while preserving local customer entity relations.
    """
    # 1. verify the token with the upstream provider
    payload = await verifier.verify_token(data.provider, data.token, data.phone)

    # 2. authenticate or provision user in local relational database
    user, is_new_user = await auth.authenticate_social(payload)

    # 3. issue system bearer JWT
    access_token = auth.issue_token(user)

    return SocialAuthResponse(
        access_token=access_token,
        token_type="bearer",
        user=user,
        is_new_user=is_new_user,
        requires_phone=(user.phone is None),
    )


@router.post("/complete-phone", response_model=UserPrivate)
async def complete_phone(data: PhoneCompleteRequest, user: CurrentUser, auth: Auth):
    """
    enables a social login user to attach their phone number to complete their profile.
    """
    return await auth.complete_phone(user, data.phone)


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
