# src/models/base.py

import enum
from datetime import datetime, timezone
from typing import Type, Any

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Dialect, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime, dialect: Dialect) -> Any:
        """
        :param value: datetime
        :param dialect: Dialect
        :return: Any
        """

        if value is None:
            return None

        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed")

        value = value.astimezone(timezone.utc)

        # MySQL has no tz-aware column, so I'm storing the UTC time
        return value.replace(tzinfo=None) if dialect.name == "mysql" else value

    def process_result_value(self, value: datetime, dialect: Dialect):
        """
        :param value: datetime
        :param dialect: Dialect
        :return:
        """

        if value is None:
            return None

        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )


def str_enum(enum_cls: Type[enum.Enum], length: int = 20) -> SQLEnum:
    """
    stores a Python ENUM as a VARCHAR holding the enum's value instead
    of a native database ENUM holding the enum's name
    :param enum_cls: Type[Enum]
    :param length: int
    :return: SQLEnum
    """

    return SQLEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [member.value for member in e]
    )

class TimestampMixin:
    """
    adds created_at & updated_at.
    Maintained by the database.
    Always UTC
    """
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )

class AuditMixin(TimestampMixin):
    """
    adds created_by & updated_by.
    """
    created_by: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete="SET NULL"))
