# src/routers/server/profiles.py

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status

from src.dependencies import (
    CurrentUser,
    get_auth_service,
    get_mailer,
    get_user_service,
    get_verification_service,
    DbSession
)
from src.exceptions import NotFoundError
from src.repositories import UserRepository
from src.schemas import AccountDelete, CodeConfirm, PasswordChange, UserPrivate, UserPublic, UserUpdate
from src.services import AuthService, UserService, VerificationService

from utilities import Mailer


# router object
router = APIRouter()

# service objects
Users = Annotated[UserService, Depends(get_user_service)]
Auth = Annotated[AuthService, Depends(get_auth_service)]
Verification = Annotated[VerificationService, Depends(get_verification_service)]
Mail = Annotated[Mailer, Depends(get_mailer)]


@router.get("/me", response_model=UserPrivate)
async def read_me(user: CurrentUser):
    """
    authenticated user's profile api
    :param user: CurrentUser
    :return:
    """

    return user


@router.patch("/me", response_model=UserPrivate)
async def update_me(data: UserUpdate, user: CurrentUser, users: Users):
    """
    authenticated user's profile update api
    :param data: UserUpdate
    :param user: CurrentUser
    :param users: UserService
    :return:
    """

    return await users.update_profile(user, data)


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(data: PasswordChange, user: CurrentUser, auth: Auth):
    """
    authenticated user's profile password update api
    :param data: PasswordChange
    :param user: CurrentUser
    :param auth: AuthService
    :return:
    """

    await auth.change_password(user, data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_me(user: CurrentUser, users: Users):
    """
    authenticated user's profile deactivation api
    :param user: CurrentUser
    :param users: UserService
    :return:
    """

    await users.deactivate(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(data: AccountDelete, user: CurrentUser, users: Users):
    """
    authenticated user's profile deletion api
    :param data: AccountDelete
    :param user: CurrentUser
    :param users: UserService
    :return:
    """

    await users.delete_account(user, data.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/email-verification", status_code=status.HTTP_202_ACCEPTED)
async def request_email_verification(
        user: CurrentUser,
        verification: Verification,
        mailer: Mail,
        background: BackgroundTasks
):
    """
    emails the authenticated user their email verification code
    :param user: CurrentUser
    :param verification: VerificationService
    :param mailer: Mailer
    :param background: BackgroundTasks
    :return:
    """

    mail = await verification.start_email_verification(user)
    background.add_task(mailer.send, mail)
    return {"detail": "Verification code sent"}


@router.post("/me/email-verification/confirm", response_model=UserPrivate)
async def confirm_email_verification(
        data: CodeConfirm,
        user: CurrentUser,
        verification: Verification
):
    """
    validates the verification code for user emails
    :param data: CodeConfirm
    :param user: CurrentUser
    :param verification: VerificationService
    :return:
    """

    return await verification.confirm_mail(user, data.code)


@router.get("/{user_id}", response_model=UserPublic)
async def read_public_profile(user_id: int, _: CurrentUser, db: DbSession):
    """
    public API to access another active user
    :param user_id: int
    :param _: CurrentUser
    :param db: AsyncSession
    :return:
    """

    target = await UserRepository(db).get_by_id(user_id)
    if (target is None) or (not target.is_active) or (target.deleted_at is not None):
        raise NotFoundError("user not found")

    return target
