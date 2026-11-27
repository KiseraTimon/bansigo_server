# src/services/review_service.py

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.exceptions import BusinessRuleError, NotFoundError
from src.models import (
    Customer, Delivery, DeliveryStatus, OrderStatus, Review, ReviewTargetType, Rider, User,
)
from src.repositories import (
    DeliveryRepository, OrderRepository, ProductRepository, ReviewRepository, RiderRepository,
)
from src.schemas import (
    OrderProductReviewItemOut, OrderReviewStatusOut, ProductReviewsSummaryOut,
    ReviewCreate, ReviewOut, RiderReviewsSummaryOut,
)
from src.services.audit_service import AuditService
from src.services.notification_service import NotificationService
from utilities import get_logger

log = get_logger(__name__)


def _sentiment_for_rating(rating: int) -> str:
    if rating >= 4:
        return "positive"
    if rating == 3:
        return "neutral"
    return "negative"


def _to_review_out(r: Review) -> ReviewOut:
    cust_name = "Verified Shopper"
    if r.customer and r.customer.user:
        first = r.customer.user.first_name or ""
        last = (r.customer.user.last_name or "")[:1]
        cust_name = f"{first} {last}.".strip() if last else (first or "Verified Shopper")

    rider_name = None
    if r.rider and r.rider.user:
        rider_name = f"{r.rider.user.first_name} {r.rider.user.last_name}".strip()

    return ReviewOut(
        id=r.id,
        customer_name=cust_name,
        target_type=r.target_type,
        order_id=r.order_id,
        order_number=r.order.order_number if r.order else None,
        product_id=r.product_id,
        product_name=r.product.name if r.product else None,
        rider_id=r.rider_id,
        rider_name=rider_name,
        rating=r.rating,
        comment=r.comment,
        sentiment=r.sentiment,
        is_published=r.is_published,
        verified_purchase=r.order_id is not None,
        created_at=r.created_at,
    )


class ReviewService:
    """
    coordinates customer product & rider delivery reviews, rating aggregation, and moderation
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.reviews = ReviewRepository(db)
        self.orders = OrderRepository(db)
        self.products = ProductRepository(db)
        self.deliveries = DeliveryRepository(db)
        self.riders = RiderRepository(db)
        self.notifications = NotificationService(db)
        self.audit = AuditService(db)

    async def submit_review(self, customer: Customer, data: ReviewCreate) -> ReviewOut:
        order = None
        rider_id = data.rider_id
        product_id = data.product_id

        if data.order_id is not None:
            order = await self.orders.get_full(data.order_id)
            if order is None or order.customer_id != customer.id:
                raise NotFoundError("Order not found")

        if data.target_type == ReviewTargetType.PRODUCT:
            if product_id is None:
                raise BusinessRuleError("product_id is required for a product review")
            product = await self.products.get_by_id(product_id)
            if product is None or not product.is_active:
                raise NotFoundError("Product not found")
            if order is not None:
                if order.status != OrderStatus.COMPLETED:
                    raise BusinessRuleError("You can review order items once the order is completed")
                if not any(item.product_id == product_id for item in order.items):
                    raise BusinessRuleError("This product is not part of the specified order")

        elif data.target_type in (ReviewTargetType.RIDER, ReviewTargetType.DELIVERY):
            if order is not None:
                delivery = order.delivery
                if delivery is None or delivery.rider_id is None:
                    raise BusinessRuleError("No delivery rider is assigned to this order")
                if delivery.status != DeliveryStatus.DELIVERED and order.status != OrderStatus.COMPLETED:
                    raise BusinessRuleError("You can rate the delivery once it has been delivered")
                rider_id = delivery.rider_id
            else:
                if rider_id is None:
                    raise BusinessRuleError("order_id or rider_id is required to review a delivery")
                rider = await self.riders.get_by_id(rider_id)
                if rider is None:
                    raise NotFoundError("Rider not found")
                # Ensure customer actually had a delivered order with this rider
                delivered_stmt = (
                    select(Delivery.id)
                    .join(Delivery.order)
                    .where(
                        Delivery.rider_id == rider_id,
                        Delivery.status == DeliveryStatus.DELIVERED,
                        Delivery.order.has(customer_id=customer.id),
                    )
                    .limit(1)
                )
                has_delivered = (await self.db.execute(delivered_stmt)).scalar_one_or_none()
                if has_delivered is None:
                    raise BusinessRuleError("You can only rate riders from your completed deliveries")

        existing = await self.reviews.find_existing(
            customer_id=customer.id,
            target_type=data.target_type,
            order_id=data.order_id,
            product_id=product_id,
            rider_id=rider_id,
        )

        sentiment = _sentiment_for_rating(data.rating)
        if existing is not None:
            before = {"rating": existing.rating, "comment": existing.comment}
            existing.rating = data.rating
            existing.comment = data.comment
            existing.sentiment = sentiment
            if rider_id is not None:
                existing.rider_id = rider_id
            review = existing
            await self.db.flush()
            self.audit.record(
                actor_id=customer.user_id,
                action="review.updated",
                entity_type="review",
                entity_id=review.id,
                before=before,
                after={"rating": review.rating, "comment": review.comment},
            )
        else:
            review = Review(
                customer_id=customer.id,
                order_id=data.order_id,
                rider_id=rider_id,
                product_id=product_id,
                target_type=data.target_type,
                rating=data.rating,
                comment=data.comment,
                sentiment=sentiment,
                is_published=True,
            )
            self.db.add(review)
            await self.db.flush()
            self.audit.record(
                actor_id=customer.user_id,
                action="review.created",
                entity_type="review",
                entity_id=review.id,
                after={
                    "target_type": data.target_type.value,
                    "rating": review.rating,
                    "product_id": product_id,
                    "rider_id": rider_id,
                    "order_id": data.order_id,
                },
            )

        if rider_id is not None and data.target_type in (ReviewTargetType.RIDER, ReviewTargetType.DELIVERY):
            await self._sync_rider_rating(rider_id, new_rating=data.rating, order_number=order.order_number if order else None)

        await self.db.commit()

        stmt = select(Review).options(*ReviewRepository._FULL).where(Review.id == review.id)
        loaded = (await self.db.execute(stmt)).scalar_one()
        return _to_review_out(loaded)

    async def _sync_rider_rating(self, rider_id: int, *, new_rating: int, order_number: str | None) -> None:
        avg_val, cnt = await self.reviews.get_rider_rating_stats(rider_id)
        rider = await self.riders.get_for_update(rider_id)
        if rider is None:
            return
        rider.rating_average = avg_val
        rider.rating_count = cnt

        ref = f"Order #{order_number}" if order_number else "a recent delivery"
        self.notifications.stage(
            user_id=rider.user_id,
            title=f"New Customer Rating: {new_rating}/5 ★",
            message=f"A customer rated {ref} {new_rating}/5 stars. Your fleet rating is now {avg_val or new_rating}/5.",
            notif_type="rating",
        )

    async def list_for_product(self, product_id: int, *, limit: int = 50) -> ProductReviewsSummaryOut:
        product = await self.products.get_by_id(product_id)
        if product is None:
            raise NotFoundError("Product not found")
        avg_val, count_val = await self.reviews.get_product_rating_stats(product_id)
        rows = await self.reviews.list_for_product(product_id, limit=limit)
        return ProductReviewsSummaryOut(
            product_id=product_id,
            average_rating=avg_val,
            total_reviews=count_val,
            reviews=[_to_review_out(r) for r in rows],
        )

    async def get_order_review_status(self, customer: Customer, order_id: int) -> OrderReviewStatusOut:
        order = await self.orders.get_full(order_id)
        if order is None or order.customer_id != customer.id:
            raise NotFoundError("Order not found")

        existing = await self.reviews.list_for_order_by_customer(customer.id, order_id)
        delivery_review = next(
            (r for r in existing if r.target_type in (ReviewTargetType.RIDER, ReviewTargetType.DELIVERY)),
            None,
        )
        prod_map = {
            r.product_id: r
            for r in existing
            if r.target_type == ReviewTargetType.PRODUCT and r.product_id is not None
        }

        rider_id = None
        rider_name = None
        can_review_delivery = False
        if order.delivery is not None and order.delivery.rider_id is not None:
            rider_id = order.delivery.rider_id
            rider_stmt = select(Rider).options(selectinload(Rider.user)).where(Rider.id == rider_id)
            rider = (await self.db.execute(rider_stmt)).scalar_one_or_none()
            if rider and rider.user:
                rider_name = f"{rider.user.first_name} {rider.user.last_name}".strip()
            can_review_delivery = (
                order.delivery.status == DeliveryStatus.DELIVERED
                or order.status == OrderStatus.COMPLETED
            )

        items_out = []
        for item in order.items:
            rev = prod_map.get(item.product_id)
            items_out.append(
                OrderProductReviewItemOut(
                    product_id=item.product_id,
                    product_name=item.product_name,
                    sku=item.sku,
                    already_reviewed=rev is not None,
                    existing_review=_to_review_out(rev) if rev is not None else None,
                )
            )

        return OrderReviewStatusOut(
            order_id=order.id,
            order_number=order.order_number,
            order_status=order.status.value,
            can_review_delivery=can_review_delivery,
            rider_id=rider_id,
            rider_name=rider_name,
            delivery_reviewed=delivery_review is not None,
            existing_delivery_review=_to_review_out(delivery_review) if delivery_review else None,
            reviewable_products=items_out,
        )

    async def list_by_customer(self, customer: Customer) -> list[ReviewOut]:
        rows = await self.reviews.list_by_customer(customer.id)
        return [_to_review_out(r) for r in rows]

    async def list_for_rider_user(self, rider_user: User) -> RiderReviewsSummaryOut:
        rider = await self.riders.get_by_user_id(rider_user.id)
        if rider is None:
            raise NotFoundError("Rider profile not found")
        avg_val, count_val = await self.reviews.get_rider_rating_stats(rider.id)
        rows = await self.reviews.list_for_rider(rider.id)
        return RiderReviewsSummaryOut(
            rider_id=rider.id,
            average_rating=avg_val if avg_val is not None else rider.rating_average,
            rating_count=count_val if count_val > 0 else rider.rating_count,
            reviews=[_to_review_out(r) for r in rows],
        )
