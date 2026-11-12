# src/schemas/__init__.py

from .user import (UserCreate, UserUpdate, UserCreateByAdmin, UserPrivate, UserPublic)
from .auth import (
    AccountDelete, PasswordChange, Token, CodeConfirm, PasswordResetConfirm, PasswordResetRequests,
    FirebasePublicConfig, PhoneCompleteRequest, SocialAuthRequest, SocialAuthResponse,
)
from .common import Detail, Page, PageParams
from .catalogue import (
    BrandCreate, BrandPublic, BrandUpdate, CategoryCreate, CategoryPublic, CategoryTree, CategoryUpdate,
    ProductCreate, ProductPublic, ProductQuery, ProductStaff, ProductUpdate,
)
from .inventory import InventoryOut, ReorderSettings, StockMovementOut, StockReceipt, StockTake, StockWastage
from .address import (
    AddressCreate, AddressOut, AddressUpdate, DeliveryZoneCreate, DeliveryZoneOut, DeliveryZoneUpdate,
)
from .order import (
    CancelRequest, CheckoutRequest, OrderDetail, OrderItemOut, OrderLineIn, OrderSummary, PickItemIn,
    StaffStatusChange, StatusHistoryOut,
)
from .payment import (
    C2BAck, C2BNotification, CashPaymentIn, DarajaAck, ManualPaymentIn, PaymentOut, RefundOut, RefundRejectIn, RefundRequestIn,
    StkCallbackEnvelope, StkPushRequest,
)
from .delivery import (
    CoverageCheckResponse, DeliveryAssign, DeliveryComplete, DeliveryEstimateRequest, DeliveryEstimateResponse,
    DeliveryFail, DeliveryOut, DeliveryRespond, DeliveryTrackingOut, HandoverCodeOut, RiderAdminOut,
    RiderApply, RiderDecision, RiderDeliveryDetailOut, RiderGoStatus, RiderLocation, RiderNavigationOut,
    RiderOut, RiderPublic,
)


__all__ = [
    # users + auth
    "UserCreate", "UserUpdate", "UserCreateByAdmin", "UserPrivate", "UserPublic",
    "AccountDelete", "PasswordChange", "Token", "CodeConfirm", "PasswordResetConfirm", "PasswordResetRequests",
    "FirebasePublicConfig", "PhoneCompleteRequest", "SocialAuthRequest", "SocialAuthResponse",
    # shared
    "Detail", "Page", "PageParams",
    # catalogue
    "BrandCreate", "BrandPublic", "BrandUpdate", "CategoryCreate", "CategoryPublic", "CategoryTree",
    "CategoryUpdate", "ProductCreate", "ProductPublic", "ProductQuery", "ProductStaff", "ProductUpdate",
    # inventory
    "InventoryOut", "ReorderSettings", "StockMovementOut", "StockReceipt", "StockTake", "StockWastage",
    # addresses
    "AddressCreate", "AddressOut", "AddressUpdate", "DeliveryZoneCreate", "DeliveryZoneOut", "DeliveryZoneUpdate",
    # orders
    "CancelRequest", "CheckoutRequest", "OrderDetail", "OrderItemOut", "OrderLineIn", "OrderSummary",
    "PickItemIn", "StaffStatusChange", "StatusHistoryOut",
    # payments
    "C2BAck", "C2BNotification", "CashPaymentIn", "DarajaAck", "PaymentOut", "RefundOut", "RefundRejectIn",
    "RefundRequestIn", "StkCallbackEnvelope", "StkPushRequest",
    # riders + deliveries
    "CoverageCheckResponse", "DeliveryAssign", "DeliveryComplete", "DeliveryEstimateRequest", "DeliveryEstimateResponse",
    "DeliveryFail", "DeliveryOut", "DeliveryRespond", "DeliveryTrackingOut", "HandoverCodeOut",
    "RiderAdminOut", "RiderApply", "RiderDecision", "RiderDeliveryDetailOut", "RiderGoStatus", "RiderLocation",
    "RiderNavigationOut", "RiderOut", "RiderPublic",
]
