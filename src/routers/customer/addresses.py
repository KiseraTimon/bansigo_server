# src/routers/customer/addresses.py

from typing import Annotated
from fastapi import APIRouter, Depends, Response, status

from src.dependencies import CurrentCustomer, get_address_service
from src.schemas import (
    AddressCreate,
    AddressOut,
    AddressUpdate,
    DeliveryZoneOut,
)
from src.services import AddressService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["customer-addresses"])
AddressServiceDep = Annotated[AddressService, Depends(get_address_service)]


@router.get(
    "/zones",
    response_model=list[DeliveryZoneOut],
    status_code=status.HTTP_200_OK,
    summary="List active delivery zones",
)
async def list_delivery_zones(
    service: AddressServiceDep,
) -> list[DeliveryZoneOut]:
    """
    Returns all active delivery zones configured for the supermarket.
    """
    zones = await service.list_zones(active_only=True)
    return [DeliveryZoneOut.model_validate(z) for z in zones]


@router.get(
    "/addresses",
    response_model=list[AddressOut],
    status_code=status.HTTP_200_OK,
    summary="List customer delivery addresses",
)
async def list_addresses(
    customer: CurrentCustomer,
    service: AddressServiceDep,
) -> list[AddressOut]:
    """
    Returns all saved delivery addresses for the authenticated customer.
    """
    addresses = await service.list_for(customer)
    return [AddressOut.model_validate(a) for a in addresses]


@router.post(
    "/addresses",
    response_model=AddressOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new delivery address",
)
async def create_address(
    data: AddressCreate,
    customer: CurrentCustomer,
    service: AddressServiceDep,
) -> AddressOut:
    """
    Saves a new customer address with latitude, longitude coordinates and zone ID.
    """
    address = await service.create(customer, data)
    return AddressOut.model_validate(address)


@router.get(
    "/addresses/{address_id}",
    response_model=AddressOut,
    status_code=status.HTTP_200_OK,
    summary="Get single delivery address",
)
async def get_address(
    address_id: int,
    customer: CurrentCustomer,
    service: AddressServiceDep,
) -> AddressOut:
    """
    Retrieves details for a specific customer address.
    """
    address = await service.get_for(customer, address_id)
    return AddressOut.model_validate(address)


@router.patch(
    "/addresses/{address_id}",
    response_model=AddressOut,
    status_code=status.HTTP_200_OK,
    summary="Update a delivery address",
)
async def update_address(
    address_id: int,
    data: AddressUpdate,
    customer: CurrentCustomer,
    service: AddressServiceDep,
) -> AddressOut:
    """
    Updates fields or coordinate pin of an existing address.
    """
    address = await service.update(customer, address_id, data)
    return AddressOut.model_validate(address)


@router.delete(
    "/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a delivery address",
)
async def delete_address(
    address_id: int,
    customer: CurrentCustomer,
    service: AddressServiceDep,
) -> Response:
    """
    Deletes an existing customer delivery address.
    """
    await service.delete(customer, address_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
