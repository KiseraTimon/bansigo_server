# src/models/types.py

"""
this file describes the shared column types for the trade models.

money, quantities and coordinates are never floats:
  * float can't represent 0.10 exactly, so totals drift by cents
  * M-Pesa compares the amount requested with the amount it reports back;
    a 349.99999999 vs 350.00 mismatch is expected to be a failed reconciliation

SQLAlchemy returns these columns as python `Decimal`; do all maths in Decimal
(`from decimal import Decimal, ROUND_HALF_UP`) and round once, at the line level.
"""

from sqlalchemy import BigInteger, Integer, Numeric

# KES amounts (VAT-inclusive prices): up to 9,999,999,999.99
Money = Numeric(12, 2)

# stock / order quantities: 3 decimals i.e. 1.250 kg
Quantity = Numeric(12, 3)

# percentages such as a VAT rate: 16.00
Rate = Numeric(5, 2)

# latitude / longitude in decimal degrees: 6 decimals is roughly 0.1 m
Coordinate = Numeric(9, 6)

# primary key for append-only tables that grow endlessly (ledger, events, audit).
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")
