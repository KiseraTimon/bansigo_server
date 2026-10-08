# src/security.py

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
from starlette.concurrency import run_in_threadpool


_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
JWT_ALGORITHM = "HS256"


# passwords

def hash_password(password: str) -> str:
    """
    synchronous password hashing function
    :param password: str
    :return: str
    """
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """
    synchronous password verification function
    :param password: str
    :param password_hash: str
    :return: bool
    """
    return _pwd_context.verify(password, password_hash)

def needs_rehash(password_hash: str) -> str:
    """
    synchronously validates if hashes are outdated
    :param password_hash: str
    :return: bool
    """
    return _pwd_context.needs_update(password_hash)


async def hash_password_async(password: str) -> str:
    """
    asynchronous password hashing
    :param password: str
    :return: str
    """
    return await run_in_threadpool(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    """
    asynchronous password verification
    :param password: str
    :param password_hash: str
    :return: bool
    """
    return await run_in_threadpool(verify_password, password, password_hash)


# tokens

def create_access_token(user_id: int, secret: str, expires_minutes: int) -> str:
    """
    generates an access token
    :param user_id: int
    :param secret: str
    :param expires_minutes: int
    :return: str
    """

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes)
    }

    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str, secret: str) -> dict:
    """
    decodes a user's access token
    raises jwt.PyJWTError (expired, bad signature, missing claims ...)
    :param token: str
    :param secret: str
    :return: dict
    """

    return jwt.decode(
        token,
        secret,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "sub"]}
    )
