# src/schemas/wishlist.py

from pydantic import BaseModel, ConfigDict, Field


class WishlistSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[int] = Field(default_factory=list, max_length=200)
