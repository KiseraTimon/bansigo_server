# src/repositories/customer_repository.py

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Customer
from .base_repository import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    """Repository for Customer database operations ONLY"""

    def __init__(self, db: AsyncSession):
        """
        constructor
        :param db: AsyncSession
        """
        super().__init__(Customer, db)



