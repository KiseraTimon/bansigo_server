# src/exceptions.py
"""
Application errors.

Services raise these.
"""
from typing import Iterable

from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(StarletteHTTPException):
    """base subclass"""

    default_status = 400
    default_detail = "Bad request"

    def __init__(self, detail: str | None = None, headers: dict[str, str] | None = None):
        super().__init__(
            status_code=self.default_status,
            detail=detail or self.default_detail,
            headers=headers,
        )


class InvalidCredentialsError(AppError):
    """wrong username/email or password"""
    default_status = 401
    default_detail = "Invalid credentials"

    def __init__(self, detail: str | None = None):
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class UnauthorizedError(AppError):
    """missing / expired / malformed access token."""
    default_status = 401
    default_detail = "Could not validate credentials"

    def __init__(self, detail: str | None = None):
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    """authenticated, but not allowed due to role mismatches."""
    default_status = 403
    default_detail = "You do not have permission to proceed"


class AccountInactiveError(ForbiddenError):
    """self-deactivated accounts"""
    default_detail = "This account is deactivated"


class NotFoundError(AppError):
    """missing records"""
    default_status = 404
    default_detail = "Not found"


class ConflictError(AppError):
    """a unique field (username/email/phone) is already taken."""
    default_status = 409

    def __init__(self, fields: Iterable[str]):
        super().__init__(f"{', '.join(sorted(fields))} already in use")
