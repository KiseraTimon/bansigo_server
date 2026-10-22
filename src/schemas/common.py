# src/schemas/common.py

from math import ceil
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PageParams(BaseModel):
    """query parameters shared by every list endpoint (use as `Annotated[PageParams, Query()]`)"""
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)


class Page(BaseModel, Generic[T]):
    """one page of results"""
    items: list[T]
    total: int
    page: int
    per_page: int
    pages: int

    @classmethod
    def of(cls, items: list[T], total: int, page: int, per_page: int) -> "Page[T]":
        return cls(items=items, total=total, page=page, per_page=per_page, pages=ceil(total / per_page) if total else 0)


class ORMModel(BaseModel):
    """base for response schemas built straight from SQLAlchemy objects"""
    model_config = ConfigDict(from_attributes=True)


class Detail(BaseModel):
    detail: str
