# utilities/money.py

"""
money helpers. All KES maths is done in Decimal and rounded ONCE per line (ROUND_HALF_UP)
"""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0.00")
_CENT = Decimal("0.01")
_SHILLING = Decimal("1")


def money(value) -> Decimal:
    """
    rounds to cents
    :param value: Decimal | int | str
    :return: Decimal
    """
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def whole_shillings(value) -> Decimal:
    """
    rounds to a whole shilling (M-Pesa only moves whole shillings)
    :param value: Decimal | int | str
    :return: Decimal
    """
    return Decimal(value).quantize(_SHILLING, rounding=ROUND_HALF_UP)


def vat_contained(gross: Decimal, rate: Decimal) -> Decimal:
    """
    VAT contained in a VAT-INCLUSIVE amount: gross * rate / (100 + rate)
    :param gross: Decimal
    :param rate: Decimal  (16.00 means 16%)
    :return: Decimal
    """
    if rate <= 0:
        return ZERO
    return money(gross * rate / (Decimal(100) + rate))
