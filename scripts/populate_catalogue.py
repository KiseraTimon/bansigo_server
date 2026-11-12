# scripts/populate_catalogue.py

"""
Standalone CLI script to bulk-populate the BansiGo database with the multi-sheet
Kenyan products catalogue workbook (or any compatible CSV/XLSX file).

Usage:
    python scripts/populate_catalogue.py [path_to_workbook.xlsx]
"""

import asyncio
import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy import select, func
from src.database import AsyncSessionLocal
from src.helpers.catalogue_import_export import (
    import_products_from_excel,
    import_products_from_csv,
)
from src.models import Admin, AdminLevel, Category, Brand, Product, User, UserRole
from src.security import hash_password_async


async def get_or_create_system_actor(db) -> int:
    """Finds an existing admin user, or provisions a system administrator actor."""
    stmt = (
        select(User.id)
        .join(Admin, Admin.user_id == User.id)
        .where(User.role == UserRole.ADMIN, User.is_active == True)
        .order_by(User.id)
        .limit(1)
    )
    admin_id = (await db.execute(stmt)).scalar_one_or_none()
    if admin_id:
        return admin_id

    # Fallback to any active user
    stmt_any = select(User.id).where(User.is_active == True).order_by(User.id).limit(1)
    any_user_id = (await db.execute(stmt_any)).scalar_one_or_none()
    if any_user_id:
        return any_user_id

    # Create default system catalogue manager
    sys_user = User(
        first_name="System",
        last_name="Catalogue Manager",
        username="sys_catalogue",
        email="catalogue@bansigo.store",
        phone="+254700000000",
        password_hash=await hash_password_async("BansiStoreHq2026!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    db.add(sys_user)
    await db.flush()

    admin_row = Admin(user_id=sys_user.id, level=AdminLevel.SUPER)
    db.add(admin_row)
    await db.flush()
    return sys_user.id


async def populate(file_path: str):
    """Executes bulk population from Excel or CSV file."""
    if not os.path.exists(file_path):
        print(f"Error: Catalogue file '{file_path}' does not exist.")
        sys.exit(1)

    print(f"==================================================")
    print(f" BansiGo Retail Catalogue Database Ingestion ")
    print(f" Target File: {os.path.basename(file_path)}")
    print(f"==================================================")

    async with AsyncSessionLocal() as db:
        actor_id = await get_or_create_system_actor(db)
        print(f"-> Ingesting catalogue as Actor User ID: {actor_id}")

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        filename_lower = file_path.lower()
        if filename_lower.endswith(".xlsx") or filename_lower.endswith(".xls"):
            print("-> Detected Excel format. Parsing multi-sheet workbook...")
            report = await import_products_from_excel(file_bytes, actor_id=actor_id, db=db)
        else:
            print("-> Detected CSV format. Decoding text lines...")
            try:
                csv_text = file_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                csv_text = file_bytes.decode("latin-1")
            report = await import_products_from_csv(csv_text, actor_id=actor_id, db=db)

        # Database counts verification
        cat_count = (await db.execute(select(func.count(Category.id)))).scalar_one()
        brand_count = (await db.execute(select(func.count(Brand.id)))).scalar_one()
        prod_count = (await db.execute(select(func.count(Product.id)))).scalar_one()

        print("\n=== Ingestion Report ===")
        print(f" Total Rows Processed : {report['total_processed']}")
        print(f" Products Created     : {report['created_count']}")
        print(f" Products Updated     : {report['updated_count']}")
        print(f" Ingestion Errors     : {len(report['errors'])}")

        if report['errors']:
            print("\nError Details (First 5):")
            for err in report['errors'][:5]:
                print(f"   Row {err.get('row')}: SKU {err.get('sku')} - {err.get('error')}")

        print("\n=== Live Database Totals ===")
        print(f" Active Categories    : {cat_count}")
        print(f" Active Brands        : {brand_count}")
        print(f" Total Products/SKUs  : {prod_count}")
        print(f"==================================================")
        print("Catalogue population completed successfully!\n")


def main():
    default_excel = os.path.join(PROJECT_ROOT, "data", "catalogue", "kenyan_products_catalogue.xlsx")
    fallback_excel = os.path.join(PROJECT_ROOT, "kenyan_products_catalogue.xlsx")

    if len(sys.argv) > 1:
        target_path = sys.argv[1]
    elif os.path.exists(default_excel):
        target_path = default_excel
    elif os.path.exists(fallback_excel):
        target_path = fallback_excel
    else:
        print("Catalogue workbook not found. Running generator first...")
        from scripts.generate_catalogue_workbook import generate_workbook
        generate_workbook()
        target_path = default_excel

    asyncio.run(populate(target_path))


if __name__ == "__main__":
    main()
