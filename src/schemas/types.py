# src/schemas/types.py

"""
Validated field types. Each one cleans then checks its input, so by
the time a value reaches a service it is already normalized (trimmed,
lowercased, +254-formatted etc. ...)

Plain functions with explicit error messages are used instead of regex
constraints so the API returns readable errors and there is no ambiguity about
the order in which "strip / lowercase / match" happen.
"""

import re
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, EmailStr, Field


# constants
USERNAME_MIN, USERNAME_MAX = 3, 30
_USERNAME_RE = re.compile(rf"[a-z0-9_.]{{{USERNAME_MIN},{USERNAME_MAX}}}")
_KE_MOBILE_RE = re.compile(r"\+254[17]\d{8}")  # +2547XXXXXXXX / +2541XXXXXXXX


def _clean_name(v: str) -> str:
    """
    checks the length of a name property
    :param v: str
    :return: str
    """

    v = v.strip()
    if not 1 <= len(v) <= 50:
        raise ValueError("must be between 1 and 50 characters")
    return v


def _clean_username(v: str) -> str:
    """
    checks the pattern and length of a username
    :param v: str
    :return: str
    """

    v = v.strip().lower()
    if not _USERNAME_RE.fullmatch(v):
        raise ValueError(
            f"must be {USERNAME_MIN}-{USERNAME_MAX} characters: letters, digits, '_' or '.'"
        )
    return v


def _clean_email(v: str) -> str:
    """
    checks the length of an email property
    :param v: str
    :return: str
    """
    v = v.strip().lower()
    if len(v) > 100:
        raise ValueError("must be at most 100 characters")
    return v


def _normalise_phone(v: str) -> str:
    """
    Accepts 0712345678, 0112345678, 254712345678, +254 712 345 678 ... and
    always returns +254712345678, so the UNIQUE constraint really catches
    duplicates (0712... and +254712... are the same phone).
    :param v: str
    :return: str
    """

    digits = re.sub(r"[\s\-().]", "", v)
    if re.fullmatch(r"0[17]\d{8}", digits):
        digits = "+254" + digits[1:]
    elif re.fullmatch(r"254[17]\d{8}", digits):
        digits = "+" + digits
    if not _KE_MOBILE_RE.fullmatch(digits):
        raise ValueError("must be a valid Kenyan mobile number, e.g. 0712345678 or +254712345678")
    return digits


def _clean_text(v: str) -> str:
    """
    trims free text; the field's max_length (checked after this) bounds it
    :param v: str
    :return: str
    """
    return v.strip()


# normalized properties
Name = Annotated[str, AfterValidator(_clean_name)]
Username = Annotated[str, AfterValidator(_clean_username)]
Email = Annotated[EmailStr, AfterValidator(_clean_email)]
Phone = Annotated[str, AfterValidator(_normalise_phone)]
Password = Annotated[str, Field(min_length=8, max_length=128)]


# trade-domain properties.
# Mirrors the DB column types in src/models/types.py so a bad value fails as a 422, not a database error
MoneyAmount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
NonNegativeQuantity = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)]
Latitude = Annotated[Decimal, Field(ge=-90, le=90, max_digits=9, decimal_places=6)]
Longitude = Annotated[Decimal, Field(ge=-180, le=180, max_digits=9, decimal_places=6)]
IdempotencyKey = Annotated[str, AfterValidator(_clean_text), Field(min_length=8, max_length=64)]
ShortText = Annotated[str, AfterValidator(_clean_text), Field(min_length=1, max_length=255)]
