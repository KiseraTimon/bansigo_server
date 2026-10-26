# src/helpers/catalogue_import_export.py

"""
helper module for bulk spreadsheet import and export of catalogue products.
handles CSV serialization and deserialization, variant recognition,
and audit logging.
"""

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Brand, Category, Inventory, MovementType, Product, StockMovement, TaxClass, UnitType,
)
from src.services.audit_service import AuditService
from utilities import get_logger, slugify

log = get_logger(__name__)

CSV_HEADERS = [
    "sku",
    "barcode",
    "name",
    "category_name",
    "brand_name",
    "unit",
    "pack_size_label",
    "price",
    "compare_at_price",
    "cost_price",
    "tax_class",
    "is_active",
    "is_age_restricted",
    "image_url",
    "quantity_on_hand",
    "reorder_level",
    "description",
]


def generate_sample_csv_template() -> str:
    """
    generates a ready-to-fill CSV template with sample data including variants
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
    writer.writeheader()

    sample_rows = [
        {
            "sku": "FLOUR-PEMBE-1KG",
            "barcode": "616110001001",
            "name": "Pembe Maize Meal 1kg",
            "category_name": "Grains & Flours",
            "brand_name": "Pembe",
            "unit": "piece",
            "pack_size_label": "1 kg",
            "price": "110.00",
            "compare_at_price": "125.00",
            "cost_price": "90.00",
            "tax_class": "zero_rated",
            "is_active": "true",
            "is_age_restricted": "false",
            "image_url": "/static/images/products/pembe_1kg.jpg",
            "quantity_on_hand": "150",
            "reorder_level": "20",
            "description": "Premium sifted maize meal for delicious ugali.",
        },
        {
            "sku": "FLOUR-PEMBE-2KG",
            "barcode": "616110001002",
            "name": "Pembe Maize Meal 2kg",
            "category_name": "Grains & Flours",
            "brand_name": "Pembe",
            "unit": "piece",
            "pack_size_label": "2 kg",
            "price": "215.00",
            "compare_at_price": "235.00",
            "cost_price": "178.00",
            "tax_class": "zero_rated",
            "is_active": "true",
            "is_age_restricted": "false",
            "image_url": "/static/images/products/pembe_2kg.jpg",
            "quantity_on_hand": "200",
            "reorder_level": "30",
            "description": "Premium sifted maize meal (family size pack).",
        },
        {
            "sku": "MILK-BROOKSIDE-500ML",
            "barcode": "616110002001",
            "name": "Brookside Whole Milk 500ml",
            "category_name": "Dairy & Eggs",
            "brand_name": "Brookside",
            "unit": "piece",
            "pack_size_label": "500 ml",
            "price": "65.00",
            "compare_at_price": "",
            "cost_price": "52.00",
            "tax_class": "standard",
            "is_active": "true",
            "is_age_restricted": "false",
            "image_url": "/static/images/products/brookside_500ml.jpg",
            "quantity_on_hand": "85",
            "reorder_level": "15",
            "description": "Fresh whole pasteurised cow milk.",
        },
    ]

    for row in sample_rows:
        writer.writerow(row)

    return output.getvalue()


async def export_products_to_csv(db: AsyncSession) -> str:
    """
    exports all products in the catalogue with their inventory, category, and brand to CSV string
    """
    stmt = (
        select(Product)
        .options(
            selectinload(Product.category),
            selectinload(Product.brand),
            selectinload(Product.inventory),
        )
        .order_by(Product.name, Product.id)
    )
    products = (await db.execute(stmt)).scalars().all()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
    writer.writeheader()

    for p in products:
        category_name = p.category.name if p.category else ""
        brand_name = p.brand.name if p.brand else ""
        qty_on_hand = str(p.inventory.quantity_on_hand) if p.inventory else "0"
        reorder_lvl = str(p.inventory.reorder_level) if p.inventory else "0"

        writer.writerow({
            "sku": p.sku,
            "barcode": p.barcode or "",
            "name": p.name,
            "category_name": category_name,
            "brand_name": brand_name,
            "unit": p.unit.value if hasattr(p.unit, "value") else str(p.unit),
            "pack_size_label": p.pack_size_label or "",
            "price": str(p.price),
            "compare_at_price": str(p.compare_at_price) if p.compare_at_price is not None else "",
            "cost_price": str(p.cost_price) if p.cost_price is not None else "",
            "tax_class": p.tax_class.value if hasattr(p.tax_class, "value") else str(p.tax_class),
            "is_active": "true" if p.is_active else "false",
            "is_age_restricted": "true" if p.is_age_restricted else "false",
            "image_url": p.image_url or "",
            "quantity_on_hand": qty_on_hand,
            "reorder_level": reorder_lvl,
            "description": p.description or "",
        })

    return output.getvalue()


async def import_products_from_csv(
    csv_text: str,
    actor_id: int,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    parses CSV data, validates lines, and inserts or updates products and their inventory balances.
    records audit log entries.
    """
    audit = AuditService(db)
    reader = csv.DictReader(io.StringIO(csv_text.strip()))

    created_count = 0
    updated_count = 0
    errors: list[dict[str, Any]] = []

    # Cache categories and brands for quick lookup
    cat_stmt = select(Category)
    categories = {c.name.strip().lower(): c for c in (await db.execute(cat_stmt)).scalars().all()}

    brand_stmt = select(Brand)
    brands = {b.name.strip().lower(): b for b in (await db.execute(brand_stmt)).scalars().all()}

    row_index = 1
    for row in reader:
        row_index += 1
        sku = (row.get("sku") or "").strip().upper()
        name = (row.get("name") or "").strip()
        cat_name = (row.get("category_name") or "").strip()

        if not sku or not name:
            errors.append({"row": row_index, "sku": sku, "error": "SKU and Name are mandatory"})
            continue

        # Validate or create category
        cat_key = cat_name.lower()
        if cat_key in categories:
            category = categories[cat_key]
        elif cat_name:
            cat_slug = slugify(cat_name)
            category = Category(
                name=cat_name,
                slug=cat_slug,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(category)
            await db.flush()
            categories[cat_key] = category
        else:
            errors.append({"row": row_index, "sku": sku, "error": "Category name is missing"})
            continue

        # Optional brand
        brand_name = (row.get("brand_name") or "").strip()
        brand: Brand | None = None
        if brand_name:
            brand_key = brand_name.lower()
            if brand_key in brands:
                brand = brands[brand_key]
            else:
                brand_slug = slugify(brand_name)
                brand = Brand(
                    name=brand_name,
                    slug=brand_slug,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                db.add(brand)
                await db.flush()
                brands[brand_key] = brand

        # Parse numeric and enum fields
        try:
            price = Decimal(str(row.get("price", "0")).strip())
            if price < 0:
                raise ValueError("Price cannot be negative")
        except (InvalidOperation, ValueError) as err:
            errors.append({"row": row_index, "sku": sku, "error": f"Invalid price: {err}"})
            continue

        compare_str = (row.get("compare_at_price") or "").strip()
        compare_at_price = Decimal(compare_str) if compare_str else None

        cost_str = (row.get("cost_price") or "").strip()
        cost_price = Decimal(cost_str) if cost_str else None

        unit_str = (row.get("unit") or "piece").strip().lower()
        try:
            unit = UnitType(unit_str)
        except ValueError:
            unit = UnitType.PIECE

        tax_str = (row.get("tax_class") or "standard").strip().lower()
        try:
            tax_class = TaxClass(tax_str)
        except ValueError:
            tax_class = TaxClass.STANDARD

        is_active = str(row.get("is_active", "true")).strip().lower() in ("true", "1", "yes")
        is_age = str(row.get("is_age_restricted", "false")).strip().lower() in ("true", "1", "yes")
        barcode = (row.get("barcode") or "").strip() or None
        pack_size = (row.get("pack_size_label") or "").strip() or None
        image_url = (row.get("image_url") or "").strip() or None
        description = (row.get("description") or "").strip() or None

        qty_str = (row.get("quantity_on_hand") or "").strip()
        qty_on_hand = Decimal(qty_str) if qty_str else Decimal("0")

        reorder_str = (row.get("reorder_level") or "").strip()
        reorder_level = Decimal(reorder_str) if reorder_str else Decimal("0")

        # Query existing product by SKU
        prod_stmt = (
            select(Product)
            .where(Product.sku == sku)
            .options(selectinload(Product.inventory))
        )
        existing = (await db.execute(prod_stmt)).scalar_one_or_none()

        if existing:
            # Update product
            before_snapshot = {
                "price": str(existing.price),
                "cost_price": str(existing.cost_price) if existing.cost_price else None,
                "is_active": existing.is_active,
            }
            existing.name = name
            existing.category_id = category.id
            existing.brand_id = brand.id if brand else None
            existing.barcode = barcode
            existing.unit = unit
            existing.pack_size_label = pack_size
            existing.price = price
            existing.compare_at_price = compare_at_price
            existing.cost_price = cost_price
            existing.tax_class = tax_class
            existing.is_active = is_active
            existing.is_age_restricted = is_age
            existing.image_url = image_url or existing.image_url
            existing.description = description or existing.description
            existing.updated_by = actor_id

            if existing.inventory:
                if qty_str:
                    existing.inventory.quantity_on_hand = qty_on_hand
                if reorder_str:
                    existing.inventory.reorder_level = reorder_level

            audit.record(
                actor_id=actor_id,
                action="product.bulk_update",
                entity_type="product",
                entity_id=existing.id,
                before=before_snapshot,
                after={"price": str(price), "cost_price": str(cost_price) if cost_price else None, "is_active": is_active},
            )
            updated_count += 1
        else:
            # Create new product
            slug = slugify(name, 140)
            # Ensure unique slug
            base_slug = slug
            n = 2
            while True:
                slug_check = (await db.execute(select(Product.id).where(Product.slug == slug))).scalar_one_or_none()
                if not slug_check:
                    break
                slug = f"{base_slug[:120]}-{n}"
                n += 1

            new_prod = Product(
                sku=sku,
                barcode=barcode,
                name=name,
                slug=slug,
                category_id=category.id,
                brand_id=brand.id if brand else None,
                unit=unit,
                pack_size_label=pack_size,
                price=price,
                compare_at_price=compare_at_price,
                cost_price=cost_price,
                tax_class=tax_class,
                is_active=is_active,
                is_age_restricted=is_age,
                image_url=image_url,
                description=description,
                created_by=actor_id,
                updated_by=actor_id,
            )
            inv = Inventory(
                quantity_on_hand=qty_on_hand,
                reorder_level=reorder_level,
            )
            new_prod.inventory = inv
            db.add(new_prod)
            await db.flush()

            audit.record(
                actor_id=actor_id,
                action="product.bulk_create",
                entity_type="product",
                entity_id=new_prod.id,
                before=None,
                after={"sku": sku, "name": name, "price": str(price)},
            )
            created_count += 1

    await db.commit()
    log.info("Bulk product import complete: %d created, %d updated, %d errors", created_count, updated_count, len(errors))
    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "errors": errors,
        "total_processed": row_index - 1,
    }
