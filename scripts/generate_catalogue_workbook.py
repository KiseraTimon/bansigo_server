# scripts/generate_catalogue_workbook.py

"""
Generates a comprehensive multi-sheet Excel workbook of popular Kenyan retail products
across 15 categories with authentic pack sizes, pricing in KES, barcodes, tax classifications,
and inventory levels. The structure aligns directly with BansiGo database models:
Product (src/models/catalogue.py) and Inventory (src/models/inventory.py).
"""

import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Output paths
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "catalogue")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "kenyan_products_catalogue.xlsx")
ROOT_COPY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kenyan_products_catalogue.xlsx")

HEADERS = [
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

# ---------------------------------------------------------------------------
# PRODUCT DATA DEFINITIONS
# ---------------------------------------------------------------------------

SNACKS_PRODUCTS = [
    # Stix Potato Crisps
    ("SNCK-STIX-CHIL-30G", "616110010001", "Stix Potato Crisps Chilli Lemon 30g", "Snacks & Confectionery", "Stix", "piece", "30g", 30.00, None, 22.00, "standard", True, False, "/static/images/products/stix_chilli_30g.jpg", 120, 20, "Crispy seasoned potato sticks bursting with zesty chilli and lemon flavor."),
    ("SNCK-STIX-CHIL-50G", "616110010002", "Stix Potato Crisps Chilli Lemon 50g", "Snacks & Confectionery", "Stix", "piece", "50g", 50.00, None, 38.00, "standard", True, False, "/static/images/products/stix_chilli_50g.jpg", 100, 15, "Medium pack of spicy chilli lemon seasoned potato crisps."),
    ("SNCK-STIX-CHIL-150G", "616110010003", "Stix Potato Crisps Chilli Lemon 150g", "Snacks & Confectionery", "Stix", "piece", "150g", 140.00, 155.00, 108.00, "standard", True, False, "/static/images/products/stix_chilli_150g.jpg", 60, 10, "Party size pack of crispy chilli lemon potato crisps."),
    ("SNCK-STIX-SALT-30G", "616110010004", "Stix Potato Crisps Simply Salted 30g", "Snacks & Confectionery", "Stix", "piece", "30g", 30.00, None, 22.00, "standard", True, False, "/static/images/products/stix_salted_30g.jpg", 120, 20, "Classic salted crispy potato sticks made from local highland potatoes."),
    ("SNCK-STIX-SALT-50G", "616110010005", "Stix Potato Crisps Simply Salted 50g", "Snacks & Confectionery", "Stix", "piece", "50g", 50.00, None, 38.00, "standard", True, False, "/static/images/products/stix_salted_50g.jpg", 90, 15, "Golden salted potato crisps in a convenient 50g snack pack."),
    ("SNCK-STIX-TOM-30G", "616110010006", "Stix Potato Crisps Tomato Tango 30g", "Snacks & Confectionery", "Stix", "piece", "30g", 30.00, None, 22.00, "standard", True, False, "/static/images/products/stix_tomato_30g.jpg", 110, 20, "Tangy sweet and savoury tomato seasoned potato sticks."),
    ("SNCK-STIX-TOM-50G", "616110010007", "Stix Potato Crisps Tomato Tango 50g", "Snacks & Confectionery", "Stix", "piece", "50g", 50.00, None, 38.00, "standard", True, False, "/static/images/products/stix_tomato_50g.jpg", 85, 15, "Tomato flavored crispy potato sticks snack pack."),
    # Urban Bites
    ("SNCK-URB-SALT-30G", "616110010010", "Urban Bites Potato Crisps Simply Salted 30g", "Snacks & Confectionery", "Urban Bites", "piece", "30g", 35.00, None, 26.00, "standard", True, False, "/static/images/products/urban_salted_30g.jpg", 90, 15, "Gourmet crinkle-cut Kenyan potato crisps, gently sea salted."),
    ("SNCK-URB-SALT-120G", "616110010011", "Urban Bites Potato Crisps Simply Salted 120g", "Snacks & Confectionery", "Urban Bites", "piece", "120g", 130.00, 145.00, 102.00, "standard", True, False, "/static/images/products/urban_salted_120g.jpg", 50, 10, "Sharing bag of crunchy salted gourmet potato crisps."),
    ("SNCK-URB-CHIL-30G", "616110010012", "Urban Bites Potato Crisps Sweet Chilli 30g", "Snacks & Confectionery", "Urban Bites", "piece", "30g", 35.00, None, 26.00, "standard", True, False, "/static/images/products/urban_chilli_30g.jpg", 95, 15, "Sweet and spicy artisanal cut Kenyan potato crisps."),
    ("SNCK-URB-CHIL-120G", "616110010013", "Urban Bites Potato Crisps Sweet Chilli 120g", "Snacks & Confectionery", "Urban Bites", "piece", "120g", 130.00, 145.00, 102.00, "standard", True, False, "/static/images/products/urban_chilli_120g.jpg", 55, 10, "Large bag of Sweet Chilli flavoured artisanal potato crisps."),
    # Tropical Heat
    ("SNCK-TH-CHEV-M-150G", "616110010020", "Tropical Heat Kenyan Chevda Mild 150g", "Snacks & Confectionery", "Tropical Heat", "piece", "150g", 135.00, None, 105.00, "standard", True, False, "/static/images/products/th_chevda_mild_150g.jpg", 80, 15, "Iconic Kenyan savory snack mix made from potatoes, peanuts, lentils and spices."),
    ("SNCK-TH-CHEV-M-300G", "616110010021", "Tropical Heat Kenyan Chevda Mild 300g", "Snacks & Confectionery", "Tropical Heat", "piece", "300g", 260.00, 280.00, 205.00, "standard", True, False, "/static/images/products/th_chevda_mild_300g.jpg", 45, 10, "Family pack of mild spiced authentic Kenyan chevda mix."),
    ("SNCK-TH-CHEV-H-150G", "616110010022", "Tropical Heat Kenyan Chevda Hot 150g", "Snacks & Confectionery", "Tropical Heat", "piece", "150g", 135.00, None, 105.00, "standard", True, False, "/static/images/products/th_chevda_hot_150g.jpg", 75, 15, "Fiery spicy Kenyan chevda seasoned with natural chilli blend."),
    ("SNCK-TH-PEAN-SALT-50G", "616110010023", "Tropical Heat Salted Peanuts 50g", "Snacks & Confectionery", "Tropical Heat", "piece", "50g", 45.00, None, 34.00, "standard", True, False, "/static/images/products/th_peanuts_salted_50g.jpg", 100, 20, "Fresh roasted Kenyan peanuts lightly dusted with fine table salt."),
    ("SNCK-TH-PEAN-MAS-150G", "616110010024", "Tropical Heat Masala Peanuts 150g", "Snacks & Confectionery", "Tropical Heat", "piece", "150g", 125.00, None, 95.00, "standard", True, False, "/static/images/products/th_peanuts_masala_150g.jpg", 60, 10, "Crispy coated peanuts tossed in signature aromatic masala spices."),
    # Peptang Crisps & Krackles
    ("SNCK-PEP-TOM-30G", "616110010030", "Peptang Tomato Crisps 30g", "Snacks & Confectionery", "Peptang", "piece", "30g", 30.00, None, 23.00, "standard", True, False, "/static/images/products/peptang_crisps_tomato_30g.jpg", 80, 15, "Delicious potato crisps made with the authentic Peptang tomato seasoning."),
    ("SNCK-KRAK-CHON-50G", "616110010031", "Krackles Cheese & Onion Crisps 50g", "Snacks & Confectionery", "Krackles", "piece", "50g", 50.00, None, 38.00, "standard", True, False, "/static/images/products/krackles_cheese_50g.jpg", 70, 15, "Rich cheddar cheese and sweet onion seasoned potato chips."),
    # Chocolates & Sweets
    ("SNCK-CAD-DM-38G", "616110010040", "Cadbury Dairy Milk Chocolate 38g", "Snacks & Confectionery", "Cadbury", "piece", "38g", 90.00, None, 72.00, "standard", True, False, "/static/images/products/cadbury_dm_38g.jpg", 110, 20, "Smooth, creamy milk chocolate bar made with a glass and a half of fresh milk."),
    ("SNCK-CAD-DM-80G", "616110010041", "Cadbury Dairy Milk Chocolate 80g", "Snacks & Confectionery", "Cadbury", "piece", "80g", 180.00, None, 145.00, "standard", True, False, "/static/images/products/cadbury_dm_80g.jpg", 85, 15, "Medium bar of classic Cadbury creamy dairy milk chocolate."),
    ("SNCK-CAD-LBAR-48G", "616110010042", "Cadbury LunchBar Max 48g", "Snacks & Confectionery", "Cadbury", "piece", "48g", 75.00, None, 58.00, "standard", True, False, "/static/images/products/cadbury_lunchbar_48g.jpg", 90, 15, "Crispy wafer, chewy caramel, peanuts and crisped rice coated in milk chocolate."),
    ("SNCK-CAD-PERK-15G", "616110010043", "Cadbury Perk Chocolate Wafer 15g", "Snacks & Confectionery", "Cadbury", "piece", "15g", 20.00, None, 15.00, "standard", True, False, "/static/images/products/cadbury_perk_15g.jpg", 200, 30, "Light and crispy wafer finger coated in smooth milk chocolate."),
    ("SNCK-DAIR-DARK-80G", "616110010044", "Dairyland 70% Dark Chocolate 80g", "Snacks & Confectionery", "Dairyland", "piece", "80g", 210.00, 230.00, 165.00, "standard", True, False, "/static/images/products/dairyland_dark_80g.jpg", 45, 10, "Premium rich Kenyan-crafted dark chocolate with 70% cocoa solids."),
    ("SNCK-PATCO-MINT-50S", "616110010050", "Patco Peppermint Sweets Pack of 50", "Snacks & Confectionery", "Patco", "piece", "Pack of 50", 100.00, None, 78.00, "standard", True, False, "/static/images/products/patco_mints_50s.jpg", 65, 10, "Refreshing traditional Kenyan hard boiled peppermint sweets."),
    ("SNCK-ORBIT-PEP-10S", "616110010051", "Orbit Sugarfree Peppermint Gum 10 Pellets", "Snacks & Confectionery", "Orbit", "piece", "10 Pellets", 50.00, None, 39.00, "standard", True, False, "/static/images/products/orbit_peppermint_10s.jpg", 150, 25, "Sugar-free peppermint chewing gum for instant fresh breath confidence."),
]

BAKERY_PRODUCTS = [
    # Broadways
    ("BAK-BROAD-WHT-400G", "616110020001", "Broadways Premium White Bread 400g", "Bakery & Pastries", "Broadways", "piece", "400g", 65.00, None, 54.00, "zero_rated", True, False, "/static/images/products/broadways_white_400g.jpg", 90, 20, "Soft, freshly baked premium white sliced sandwich bread."),
    ("BAK-BROAD-WHT-600G", "616110020002", "Broadways Premium White Bread 600g", "Bakery & Pastries", "Broadways", "piece", "600g", 95.00, None, 80.00, "zero_rated", True, False, "/static/images/products/broadways_white_600g.jpg", 70, 15, "Medium-sized family loaf of fresh sliced white bread."),
    ("BAK-BROAD-WHT-800G", "616110020003", "Broadways Premium White Bread 800g", "Bakery & Pastries", "Broadways", "piece", "800g", 125.00, None, 105.00, "zero_rated", True, False, "/static/images/products/broadways_white_800g.jpg", 80, 15, "Double family loaf of Broadways sliced white bread."),
    ("BAK-BROAD-BRN-400G", "616110020004", "Broadways Brown Bread 400g", "Bakery & Pastries", "Broadways", "piece", "400g", 70.00, None, 58.00, "zero_rated", True, False, "/static/images/products/broadways_brown_400g.jpg", 75, 15, "Nutritious whole wheat sliced brown bread packed with dietary fibre."),
    ("BAK-BROAD-BRN-800G", "616110020005", "Broadways Brown Bread 800g", "Bakery & Pastries", "Broadways", "piece", "800g", 135.00, None, 112.00, "zero_rated", True, False, "/static/images/products/broadways_brown_800g.jpg", 60, 10, "Large family size loaf of sliced wholemeal brown bread."),
    # Festive & Supa Loaf
    ("BAK-FEST-WHT-400G", "616110020010", "Festive Sliced White Bread 400g", "Bakery & Pastries", "Festive", "piece", "400g", 65.00, None, 54.00, "zero_rated", True, False, "/static/images/products/festive_white_400g.jpg", 85, 20, "Fresh and pillowy soft sliced white bread from Festive bakers."),
    ("BAK-FEST-WHT-800G", "616110020011", "Festive Sliced White Bread 800g", "Bakery & Pastries", "Festive", "piece", "800g", 125.00, None, 105.00, "zero_rated", True, False, "/static/images/products/festive_white_800g.jpg", 70, 15, "Large family loaf of Festive white bread."),
    ("BAK-FEST-MLK-400G", "616110020012", "Festive Milk Bread 400g", "Bakery & Pastries", "Festive", "piece", "400g", 70.00, None, 59.00, "zero_rated", True, False, "/static/images/products/festive_milk_400g.jpg", 65, 15, "Enriched sliced bread baked with pure cow milk for extra fluffiness."),
    ("BAK-SUPA-WHT-400G", "616110020020", "Supa Loaf White Bread 400g", "Bakery & Pastries", "Supa Loaf", "piece", "400g", 65.00, None, 54.00, "zero_rated", True, False, "/static/images/products/supaloaf_white_400g.jpg", 90, 20, "The iconic Kenyan Supa Loaf sliced white bread."),
    ("BAK-SUPA-WHT-800G", "616110020021", "Supa Loaf White Bread 800g", "Bakery & Pastries", "Supa Loaf", "piece", "800g", 125.00, None, 105.00, "zero_rated", True, False, "/static/images/products/supaloaf_white_800g.jpg", 75, 15, "Family sized 800g loaf of soft Supa Loaf white bread."),
    # Kenblest & Pastries
    ("BAK-KENB-BUNS-6S", "616110020030", "Kenblest Sweet Buns Pack of 6", "Bakery & Pastries", "Kenblest", "piece", "Pack of 6", 90.00, None, 72.00, "standard", True, False, "/static/images/products/kenblest_buns_6s.jpg", 50, 10, "Golden baked sweet breakfast buns, perfect with morning chai."),
    ("BAK-INHOUSE-MAND-4S", "616110020040", "Bansi Bakery Fresh Mandazi Pack of 4", "Bakery & Pastries", "Bansi Bakery", "piece", "Pack of 4", 60.00, None, 40.00, "standard", True, False, "/static/images/products/bansi_mandazi_4s.jpg", 60, 15, "Authentic coastal style cardamom flavoured fried mandazi."),
    ("BAK-INHOUSE-SAM-B3S", "616110020041", "Bansi Deli Beef Samosas Pack of 3", "Bakery & Pastries", "Bansi Bakery", "piece", "Pack of 3", 120.00, None, 80.00, "standard", True, False, "/static/images/products/bansi_samosa_beef_3s.jpg", 40, 10, "Crispy golden fried pastry pockets filled with spiced minced beef and coriander."),
    ("BAK-INHOUSE-SCON-4S", "616110020042", "Bansi Bakery Plain Scones Pack of 4", "Bakery & Pastries", "Bansi Bakery", "piece", "Pack of 4", 80.00, None, 55.00, "standard", True, False, "/static/images/products/bansi_scones_4s.jpg", 45, 10, "Crumbly and tender baked tea scones, delightful with butter or jam."),
    ("BAK-INHOUSE-QUEEN-6S", "616110020043", "Bansi Bakery Queen Cakes Pack of 6", "Bakery & Pastries", "Bansi Bakery", "piece", "Pack of 6", 120.00, None, 85.00, "standard", True, False, "/static/images/products/bansi_queen_cakes_6s.jpg", 50, 10, "Soft vanilla sponge queen cakes studded with sweet sultanas."),
    ("BAK-INHOUSE-BAGU-250G", "616110020044", "Artisan French Baguette 250g", "Bakery & Pastries", "Bansi Bakery", "piece", "1 Piece", 90.00, None, 60.00, "standard", True, False, "/static/images/products/baguette_250g.jpg", 30, 8, "Crusty golden artisan French baguette with a soft and airy interior."),
    ("BAK-INHOUSE-BF-SLICE", "616110020045", "Black Forest Cake Fresh Slice", "Bakery & Pastries", "Bansi Bakery", "piece", "1 Slice", 180.00, 200.00, 120.00, "standard", True, False, "/static/images/products/black_forest_slice.jpg", 25, 5, "Rich chocolate sponge layered with whipped dairy cream and dark cherries."),
]

BEVERAGES_PRODUCTS = [
    # Coca-Cola & Sodas
    ("BEV-COKE-500ML", "616110030001", "Coca-Cola Original Taste 500ml", "Beverages & Soft Drinks", "Coca-Cola", "piece", "500ml", 70.00, None, 56.00, "standard", True, False, "/static/images/products/coke_500ml.jpg", 150, 30, "The world's favourite sparkling soft drink, refreshing and uplifting in a 500ml PET bottle."),
    ("BEV-COKE-1250ML", "616110030002", "Coca-Cola Original Taste 1.25L", "Beverages & Soft Drinks", "Coca-Cola", "piece", "1.25L", 130.00, None, 105.00, "standard", True, False, "/static/images/products/coke_125l.jpg", 90, 20, "Sharing size bottle of crisp Coca-Cola Original."),
    ("BEV-COKE-2000ML", "616110030003", "Coca-Cola Original Taste 2L", "Beverages & Soft Drinks", "Coca-Cola", "piece", "2L", 190.00, 210.00, 155.00, "standard", True, False, "/static/images/products/coke_2l.jpg", 80, 15, "Party size 2-litre bottle of Coca-Cola Original."),
    ("BEV-COKE-ZERO-500ML", "616110030004", "Coca-Cola Zero Sugar 500ml", "Beverages & Soft Drinks", "Coca-Cola", "piece", "500ml", 75.00, None, 60.00, "standard", True, False, "/static/images/products/coke_zero_500ml.jpg", 80, 15, "Zero sugar, zero calories with the legendary Coca-Cola taste."),
    ("BEV-FANTA-ORG-500ML", "616110030005", "Fanta Orange 500ml", "Beverages & Soft Drinks", "Fanta", "piece", "500ml", 70.00, None, 56.00, "standard", True, False, "/static/images/products/fanta_orange_500ml.jpg", 120, 25, "Bright, bubbly orange flavoured soft drink with vibrant citrus flavor."),
    ("BEV-FANTA-ORG-1250ML", "616110030006", "Fanta Orange 1.25L", "Beverages & Soft Drinks", "Fanta", "piece", "1.25L", 130.00, None, 105.00, "standard", True, False, "/static/images/products/fanta_orange_125l.jpg", 80, 15, "Family sharing 1.25L bottle of tangy Fanta Orange."),
    ("BEV-FANTA-PAS-500ML", "616110030007", "Fanta Passion 500ml", "Beverages & Soft Drinks", "Fanta", "piece", "500ml", 70.00, None, 56.00, "standard", True, False, "/static/images/products/fanta_passion_500ml.jpg", 110, 20, "Kenyan fan favourite sweet and tropical passion fruit soda."),
    ("BEV-SPRITE-500ML", "616110030008", "Sprite Lemon-Lime 500ml", "Beverages & Soft Drinks", "Sprite", "piece", "500ml", 70.00, None, 56.00, "standard", True, False, "/static/images/products/sprite_500ml.jpg", 130, 25, "Clean, crisp lemon-lime sparkling thirst quencher with 100% natural flavours."),
    ("BEV-STONEY-500ML", "616110030009", "Stoney Tangawizi Ginger Beer 500ml", "Beverages & Soft Drinks", "Stoney", "piece", "500ml", 70.00, None, 56.00, "standard", True, False, "/static/images/products/stoney_500ml.jpg", 140, 25, "Strong, punchy African ginger flavoured sparkling soda with natural kick."),
    ("BEV-KREST-BITT-500ML", "616110030010", "Krest Bitter Lemon 500ml", "Beverages & Soft Drinks", "Krest", "piece", "500ml", 75.00, None, 60.00, "standard", True, False, "/static/images/products/krest_500ml.jpg", 60, 12, "Sophisticated sparkling bitter lemon beverage, perfect on ice or as a mixer."),
    # Juices
    ("BEV-DELM-MNG-1L", "616110030020", "Del Monte 100% Mango Juice 1L", "Beverages & Soft Drinks", "Del Monte", "piece", "1L", 220.00, 240.00, 178.00, "standard", True, False, "/static/images/products/delmonte_mango_1l.jpg", 75, 15, "Thick, tropical Kenyan sun-ripened mango juice blend."),
    ("BEV-DELM-PIN-1L", "616110030021", "Del Monte 100% Pineapple Juice 1L", "Beverages & Soft Drinks", "Del Monte", "piece", "1L", 220.00, 240.00, 178.00, "standard", True, False, "/static/images/products/delmonte_pineapple_1l.jpg", 70, 15, "Sweet and tangy pineapple juice made from Del Monte Thika pineapples."),
    ("BEV-PNP-MNG-1L", "616110030022", "Pick 'N' Peel Mango Nectar 1L", "Beverages & Soft Drinks", "Pick 'N' Peel", "piece", "1L", 210.00, None, 170.00, "standard", True, False, "/static/images/products/picknpeel_mango_1l.jpg", 80, 15, "Rich fruit nectar bursting with smooth Kenyan mango puree."),
    ("BEV-AFIA-MNG-500ML", "616110030023", "Afia Mango Fruit Juice Drink 500ml", "Beverages & Soft Drinks", "Afia", "piece", "500ml", 80.00, None, 62.00, "standard", True, False, "/static/images/products/afia_mango_500ml.jpg", 100, 20, "Refreshing mango juice drink fortified with vitamin C."),
    # Packaged Water
    ("BEV-DASANI-500ML", "616110030030", "Dasani Purified Drinking Water 500ml", "Beverages & Soft Drinks", "Dasani", "piece", "500ml", 40.00, None, 28.00, "standard", True, False, "/static/images/products/dasani_500ml.jpg", 200, 40, "Clean, pure drinking water enhanced with minerals for crisp taste."),
    ("BEV-DASANI-1L", "616110030031", "Dasani Purified Drinking Water 1L", "Beverages & Soft Drinks", "Dasani", "piece", "1L", 70.00, None, 50.00, "standard", True, False, "/static/images/products/dasani_1l.jpg", 150, 30, "1-litre bottle of pure refreshing Dasani mineral-enhanced water."),
    ("BEV-DASANI-5L", "616110030032", "Dasani Purified Drinking Water 5L", "Beverages & Soft Drinks", "Dasani", "piece", "5L", 210.00, None, 165.00, "standard", True, False, "/static/images/products/dasani_5l.jpg", 60, 15, "Convenient 5L family water dispenser bottle with easy-carry handle."),
    ("BEV-KERING-500ML", "616110030033", "Keringet Natural Mineral Water 500ml", "Beverages & Soft Drinks", "Keringet", "piece", "500ml", 55.00, None, 40.00, "standard", True, False, "/static/images/products/keringet_500ml.jpg", 120, 20, "Natural mineral spring water sourced from the Great Rift Valley."),
    # Tea & Coffee
    ("BEV-KER-GOLD-50S", "616110030040", "Kericho Gold Premium Tea Bags 50s", "Beverages & Soft Drinks", "Kericho Gold", "piece", "50 Bags", 185.00, None, 145.00, "zero_rated", True, False, "/static/images/products/kericho_gold_50s.jpg", 90, 15, "World renowned Kenyan highland black tea known for bright amber color and aroma."),
    ("BEV-KER-GOLD-100S", "616110030041", "Kericho Gold Premium Tea Bags 100s", "Beverages & Soft Drinks", "Kericho Gold", "piece", "100 Bags", 340.00, 365.00, 275.00, "zero_rated", True, False, "/static/images/products/kericho_gold_100s.jpg", 65, 12, "Economy pack of 100 enveloped premium tea bags."),
    ("BEV-FAHARI-250G", "616110030042", "Fahari ya Kenya Loose Tea 250g", "Beverages & Soft Drinks", "Fahari ya Kenya", "piece", "250g", 135.00, None, 108.00, "zero_rated", True, False, "/static/images/products/fahari_tea_250g.jpg", 100, 20, "Full-bodied traditional loose black tea leaves, Kenya's morning chai standard."),
    ("BEV-FAHARI-500G", "616110030043", "Fahari ya Kenya Loose Tea 500g", "Beverages & Soft Drinks", "Fahari ya Kenya", "piece", "500g", 260.00, None, 210.00, "zero_rated", True, False, "/static/images/products/fahari_tea_500g.jpg", 70, 15, "Half kilogram packet of authentic Kenyan rich loose chai."),
    ("BEV-NESC-CLAS-100G", "616110030044", "Nescafe Classic Instant Coffee Jar 100g", "Beverages & Soft Drinks", "Nescafe", "piece", "100g", 540.00, 580.00, 435.00, "standard", True, False, "/static/images/products/nescafe_classic_100g.jpg", 50, 10, "100% pure instant soluble coffee granulated for rich aroma and bold morning taste."),
    ("BEV-DORM-INST-100G", "616110030045", "Dormans Supreme Instant Coffee 100g", "Beverages & Soft Drinks", "Dormans", "piece", "100g", 420.00, None, 335.00, "standard", True, False, "/static/images/products/dormans_instant_100g.jpg", 45, 10, "Blended from premium Arabica beans roasted and freeze-dried in Kenya."),
]

ALCOHOL_PRODUCTS = [
    # Beers & Ciders
    ("ALC-TUSK-LAG-500B", "616110040001", "Tusker Lager 4.2% Bottle 500ml", "Alcoholic Drinks & Spirits", "Tusker", "piece", "500ml", 220.00, None, 175.00, "standard", True, True, "/static/images/products/tusker_lager_500b.jpg", 180, 36, "Kenya's signature beer brewed from 100% African ingredients since 1922."),
    ("ALC-TUSK-LAG-500C", "616110040002", "Tusker Lager 4.2% Can 500ml", "Alcoholic Drinks & Spirits", "Tusker", "piece", "500ml", 240.00, None, 190.00, "standard", True, True, "/static/images/products/tusker_lager_500c.jpg", 140, 24, "Chilled canned Tusker lager, crisp and refreshing."),
    ("ALC-TUSK-MLT-330B", "616110040003", "Tusker Malt Lager 5.0% Bottle 330ml", "Alcoholic Drinks & Spirits", "Tusker", "piece", "330ml", 230.00, None, 185.00, "standard", True, True, "/static/images/products/tusker_malt_330b.jpg", 120, 24, "100% premium malted barley lager with a rich, smooth finish."),
    ("ALC-TUSK-CID-500B", "616110040004", "Tusker Premium Cider 4.5% Bottle 500ml", "Alcoholic Drinks & Spirits", "Tusker", "piece", "500ml", 240.00, None, 192.00, "standard", True, True, "/static/images/products/tusker_cider_500b.jpg", 130, 24, "Crisp and delightfully refreshing real apple cider."),
    ("ALC-WHIT-CAP-500B", "616110040005", "White Cap Lager 4.2% Bottle 500ml", "Alcoholic Drinks & Spirits", "White Cap", "piece", "500ml", 220.00, None, 175.00, "standard", True, True, "/static/images/products/whitecap_500b.jpg", 110, 24, "Distinctive crisp taste inspired by the snow on Mt. Kenya, no added sugar."),
    ("ALC-GUIN-FES-500B", "616110040006", "Guinness Foreign Extra Stout 7.5% 500ml", "Alcoholic Drinks & Spirits", "Guinness", "piece", "500ml", 250.00, None, 200.00, "standard", True, True, "/static/images/products/guinness_fes_500b.jpg", 120, 24, "Rich and complex stout beer with roasted barley character and bold 7.5% ABV."),
    ("ALC-BALO-LAG-500B", "616110040007", "Balozi Lager 4.2% Bottle 500ml", "Alcoholic Drinks & Spirits", "Balozi", "piece", "500ml", 200.00, None, 160.00, "standard", True, True, "/static/images/products/balozi_500b.jpg", 90, 20, "Smooth, unhurried Kenyan lager brewed for everyday celebration."),
    # Spirits & Gin
    ("ALC-GILB-GIN-250ML", "616110040010", "Gilbey's Special Dry Gin 250ml", "Alcoholic Drinks & Spirits", "Gilbey's", "piece", "250ml", 380.00, None, 305.00, "standard", True, True, "/static/images/products/gilbeys_250ml.jpg", 100, 20, "Pocket size bottle of London dry gin flavored with juniper berries and botanicals."),
    ("ALC-GILB-GIN-750ML", "616110040011", "Gilbey's Special Dry Gin 750ml", "Alcoholic Drinks & Spirits", "Gilbey's", "piece", "750ml", 1150.00, 1250.00, 920.00, "standard", True, True, "/static/images/products/gilbeys_750ml.jpg", 75, 15, "Full size bottle of classic dry gin, ideal for gin and tonic cocktails."),
    ("ALC-CHRM-VOD-250ML", "616110040012", "Chrome Vodka 250ml", "Alcoholic Drinks & Spirits", "Chrome", "piece", "250ml", 260.00, None, 208.00, "standard", True, True, "/static/images/products/chrome_250ml.jpg", 120, 25, "Quadruple distilled smooth grain vodka crafted for easy mixing."),
    ("ALC-CHRM-VOD-750ML", "616110040013", "Chrome Vodka 750ml", "Alcoholic Drinks & Spirits", "Chrome", "piece", "750ml", 720.00, None, 580.00, "standard", True, True, "/static/images/products/chrome_750ml.jpg", 80, 15, "Standard 750ml bottle of crisp Chrome vodka."),
    ("ALC-KC-ORIG-250ML", "616110040014", "Kenya Cane Original Spirit 250ml", "Alcoholic Drinks & Spirits", "Kenya Cane", "piece", "250ml", 290.00, None, 230.00, "standard", True, True, "/static/images/products/kc_orig_250ml.jpg", 110, 25, "Kenya's timeless sugarcane spirit, smooth and versatile."),
    ("ALC-KC-ORIG-750ML", "616110040015", "Kenya Cane Original Spirit 750ml", "Alcoholic Drinks & Spirits", "Kenya Cane", "piece", "750ml", 820.00, None, 660.00, "standard", True, True, "/static/images/products/kc_orig_750ml.jpg", 70, 15, "Full bottle of Kenya Cane sugarcane spirit 40% ABV."),
    ("ALC-CM-GOLD-750ML", "616110040016", "Captain Morgan Spiced Gold 750ml", "Alcoholic Drinks & Spirits", "Captain Morgan", "piece", "750ml", 1250.00, 1380.00, 1010.00, "standard", True, True, "/static/images/products/captain_morgan_750ml.jpg", 60, 12, "Smooth blend of Caribbean rum with spice and other natural flavours."),
    ("ALC-JW-RED-750ML", "616110040020", "Johnnie Walker Red Label Whisky 750ml", "Alcoholic Drinks & Spirits", "Johnnie Walker", "piece", "750ml", 1850.00, 1990.00, 1520.00, "standard", True, True, "/static/images/products/jw_red_750ml.jpg", 50, 10, "Pioneering blended Scotch whisky with vibrant smoky and spicy notes."),
    ("ALC-JW-BLK-750ML", "616110040021", "Johnnie Walker Black Label 12YO 750ml", "Alcoholic Drinks & Spirits", "Johnnie Walker", "piece", "750ml", 3600.00, 3850.00, 2950.00, "standard", True, True, "/static/images/products/jw_black_750ml.jpg", 35, 8, "Iconic 12-year-old blended Scotch whisky, rich, complex and remarkably balanced."),
    # Wines
    ("ALC-4TH-RED-750ML", "616110040030", "4th Street Sweet Red Wine 750ml", "Alcoholic Drinks & Spirits", "4th Street", "piece", "750ml", 850.00, None, 680.00, "standard", True, True, "/static/images/products/4th_street_red_750ml.jpg", 80, 15, "Fruity, naturally sweet South African red wine for social gatherings."),
    ("ALC-4TH-RED-5L", "616110040031", "4th Street Sweet Red Wine Box 5L", "Alcoholic Drinks & Spirits", "4th Street", "piece", "5L", 3400.00, 3650.00, 2750.00, "standard", True, True, "/static/images/products/4th_street_red_5l.jpg", 30, 6, "5-litre bag-in-box sweet red wine, stays fresh for weeks after tapping."),
]

DAIRY_PRODUCTS = [
    # Brookside Milk
    ("DAI-BRK-FRSH-500P", "616110050001", "Brookside Fresh Whole Milk Pouch 500ml", "Dairy & Eggs", "Brookside", "piece", "500ml", 65.00, None, 52.00, "zero_rated", True, False, "/static/images/products/brookside_pouch_500ml.jpg", 160, 30, "Pasteurised and homogenised pure cow milk in an easy-to-use poly pouch."),
    ("DAI-BRK-LL-500T", "616110050002", "Brookside Long Life Whole Milk 500ml", "Dairy & Eggs", "Brookside", "piece", "500ml", 75.00, None, 60.00, "zero_rated", True, False, "/static/images/products/brookside_tetra_500ml.jpg", 120, 25, "UHT treated long life whole milk in aseptic Tetra Pak carton."),
    ("DAI-BRK-LL-1000T", "616110050003", "Brookside Long Life Whole Milk 1L", "Dairy & Eggs", "Brookside", "piece", "1L", 145.00, None, 118.00, "zero_rated", True, False, "/static/images/products/brookside_tetra_1l.jpg", 100, 20, "1-litre UHT whole milk, pantry staple requiring no refrigeration until opened."),
    ("DAI-BRK-LF-500T", "616110050004", "Brookside Low Fat Milk 500ml", "Dairy & Eggs", "Brookside", "piece", "500ml", 75.00, None, 61.00, "zero_rated", True, False, "/static/images/products/brookside_lowfat_500ml.jpg", 80, 15, "Low fat milk with under 1.5% fat content, high calcium and protein."),
    # New KCC Milk
    ("DAI-KCC-FRSH-500P", "616110050010", "KCC Gold Crown Fresh Milk 500ml", "Dairy & Eggs", "KCC", "piece", "500ml", 60.00, None, 48.00, "zero_rated", True, False, "/static/images/products/kcc_pouch_500ml.jpg", 140, 30, "Pure pasteurised cow milk from Kenya's historic cooperative farmers."),
    ("DAI-KCC-MALA-500P", "616110050011", "KCC Mala Cultured Sour Milk 500ml", "Dairy & Eggs", "KCC", "piece", "500ml", 75.00, None, 60.00, "zero_rated", True, False, "/static/images/products/kcc_mala_500ml.jpg", 90, 20, "Traditional thick cultured milk (mala), the ultimate accompaniment for ugali."),
    ("DAI-KCC-MALA-1L", "616110050012", "KCC Mala Cultured Sour Milk 1L", "Dairy & Eggs", "KCC", "piece", "1L", 140.00, None, 114.00, "zero_rated", True, False, "/static/images/products/kcc_mala_1l.jpg", 70, 15, "Family 1-litre carton of tangy thick cultured mala milk."),
    # Yoghurt
    ("DAI-BIO-YOG-STR-150G", "616110050020", "Bio Organic Strawberry Yoghurt 150g", "Dairy & Eggs", "Bio", "piece", "150g", 95.00, None, 75.00, "standard", True, False, "/static/images/products/bio_yoghurt_strawberry_150g.jpg", 80, 15, "Gourmet probiotic yoghurt infused with real wild strawberry fruit pieces."),
    ("DAI-BIO-YOG-STR-450G", "616110050021", "Bio Organic Strawberry Yoghurt 450g", "Dairy & Eggs", "Bio", "piece", "450g", 220.00, None, 175.00, "standard", True, False, "/static/images/products/bio_yoghurt_strawberry_450g.jpg", 50, 10, "Tub of creamy Bio probiotic yoghurt with real strawberry coulis."),
    ("DAI-BRK-YOG-VAN-500ML", "616110050022", "Brookside Dairy Fresh Vanilla Yoghurt 500ml", "Dairy & Eggs", "Brookside", "piece", "500ml", 150.00, None, 120.00, "standard", True, False, "/static/images/products/brookside_yog_vanilla_500ml.jpg", 75, 15, "Smooth drinking vanilla flavoured yoghurt made with whole dairy milk."),
    # Butter & Cheese
    ("DAI-BRK-BUTT-250G", "616110050030", "Brookside Pure Salted Butter 250g", "Dairy & Eggs", "Brookside", "piece", "250g", 380.00, None, 305.00, "standard", True, False, "/static/images/products/brookside_butter_250g.jpg", 60, 12, "Rich creamery butter churned from pure pasture-fed cow cream."),
    ("DAI-BRK-BUTT-500G", "616110050031", "Brookside Pure Salted Butter 500g", "Dairy & Eggs", "Brookside", "piece", "500g", 740.00, 780.00, 600.00, "standard", True, False, "/static/images/products/brookside_butter_500g.jpg", 40, 8, "Catering size block of salted dairy butter."),
    ("DAI-RAKA-CHED-250G", "616110050032", "Raka Mild Cheddar Cheese Block 250g", "Dairy & Eggs", "Raka", "piece", "250g", 480.00, None, 385.00, "standard", True, False, "/static/images/products/raka_cheddar_250g.jpg", 45, 10, "Artisan Kenyan matured cheddar cheese block with creamy mild tang."),
    ("DAI-RAKA-MOZZ-250G", "616110050033", "Raka Mozzarella Cheese Block 250g", "Dairy & Eggs", "Raka", "piece", "250g", 460.00, None, 370.00, "standard", True, False, "/static/images/products/raka_mozzarella_250g.jpg", 40, 8, "Superior stretch mozzarella cheese, ideal for homemade pizzas and pasta bakes."),
    # Eggs
    ("DAI-EGG-TRAY-30S", "616110050040", "Fresh Farm Large Eggs Tray of 30", "Dairy & Eggs", "Bansi Farms", "piece", "Tray of 30", 480.00, 520.00, 400.00, "zero_rated", True, False, "/static/images/products/eggs_tray_30s.jpg", 80, 15, "Full tray of 30 graded farm-fresh brown eggs with golden yolks."),
    ("DAI-EGG-PACK-6S", "616110050041", "Fresh Farm Large Eggs Pack of 6", "Dairy & Eggs", "Bansi Farms", "piece", "Pack of 6", 110.00, None, 88.00, "zero_rated", True, False, "/static/images/products/eggs_pack_6s.jpg", 100, 20, "Carton pack of 6 fresh free-range chicken eggs."),
]

ICECREAM_PRODUCTS = [
    # Dairyland Tubs
    ("ICE-DAIR-VAN-500ML", "616110060001", "Dairyland Classic Vanilla Ice Cream 500ml", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "500ml", 320.00, None, 255.00, "standard", True, False, "/static/images/products/dairyland_vanilla_500ml.jpg", 40, 8, "Velvety smooth vanilla ice cream churned with natural vanilla extract."),
    ("ICE-DAIR-VAN-1L", "616110060002", "Dairyland Classic Vanilla Ice Cream 1L", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "1L", 580.00, None, 460.00, "standard", True, False, "/static/images/products/dairyland_vanilla_1l.jpg", 35, 8, "Family 1-litre tub of rich dairy vanilla ice cream."),
    ("ICE-DAIR-VAN-2L", "616110060003", "Dairyland Classic Vanilla Ice Cream 2L", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "2L", 990.00, 1080.00, 790.00, "standard", True, False, "/static/images/products/dairyland_vanilla_2l.jpg", 25, 5, "Party tub of premium vanilla ice cream."),
    ("ICE-DAIR-CHOC-500ML", "616110060004", "Dairyland Rich Chocolate Ice Cream 500ml", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "500ml", 340.00, None, 270.00, "standard", True, False, "/static/images/products/dairyland_choc_500ml.jpg", 40, 8, "Indulgent cocoa ice cream made with real cocoa butter."),
    ("ICE-DAIR-CHOC-1L", "616110060005", "Dairyland Rich Chocolate Ice Cream 1L", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "1L", 610.00, None, 485.00, "standard", True, False, "/static/images/products/dairyland_choc_1l.jpg", 30, 6, "1-litre tub of decadent deep chocolate ice cream."),
    ("ICE-DAIR-STRAW-1L", "616110060006", "Dairyland Strawberry Delight Ice Cream 1L", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "1L", 580.00, None, 460.00, "standard", True, False, "/static/images/products/dairyland_straw_1l.jpg", 30, 6, "Smooth strawberry ice cream with swirls of real strawberry puree."),
    ("ICE-DAIR-CARM-1L", "616110060007", "Dairyland Salted Caramel Fudge Ice Cream 1L", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "1L", 650.00, 700.00, 520.00, "standard", True, False, "/static/images/products/dairyland_caramel_1l.jpg", 25, 5, "Rich caramel dairy ice cream rippled with salted butter fudge ribbons."),
    # Single Serve & Sticks
    ("ICE-DAIR-STK-VAN", "616110060010", "Dairyland Choc Bar Vanilla on Stick 90ml", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "90ml", 120.00, None, 92.00, "standard", True, False, "/static/images/products/dairyland_chocbar_90ml.jpg", 70, 15, "Creamy vanilla ice cream bar coated in crisp Belgian milk chocolate."),
    ("ICE-DAIR-STK-ALM", "616110060011", "Dairyland Choc Bar Almond on Stick 90ml", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "90ml", 140.00, None, 108.00, "standard", True, False, "/static/images/products/dairyland_almond_90ml.jpg", 65, 15, "Vanilla ice cream on a stick enrobed in milk chocolate with roasted almond nibs."),
    ("ICE-DAIR-CONE-120ML", "616110060012", "Dairyland Cone King Vanilla & Chocolate 120ml", "Ice Cream & Frozen Desserts", "Dairyland", "piece", "120ml", 150.00, None, 115.00, "standard", True, False, "/static/images/products/dairyland_cone_120ml.jpg", 60, 12, "Crispy waffle cone filled with vanilla and chocolate ice cream and a chocolate tip."),
    ("ICE-LYON-CHOC-75ML", "616110060020", "Lyons Maid Classic Choc Bar 75ml", "Ice Cream & Frozen Desserts", "Lyons Maid", "piece", "75ml", 90.00, None, 68.00, "standard", True, False, "/static/images/products/lyons_chocbar_75ml.jpg", 80, 15, "Kenyan heritage ice cream bar drenched in cracking chocolate coating."),
    ("ICE-BIO-GEL-VAN-500ML", "616110060030", "Bio Gourmet Vanilla Bean Artisanal Gelato 500ml", "Ice Cream & Frozen Desserts", "Bio", "piece", "500ml", 590.00, None, 470.00, "standard", True, False, "/static/images/products/bio_gelato_vanilla_500ml.jpg", 25, 5, "Ultra-dense Italian style gelato crafted from organic whole milk and Madagascar vanilla pods."),
]

GRAINS_PRODUCTS = [
    # Maize Meal (Unga wa Mahindi)
    ("GRN-PEMB-MZ-1KG", "616110070001", "Pembe Sifted Maize Meal 1kg", "Grains, Flours & Staple Foods", "Pembe", "piece", "1kg", 110.00, None, 90.00, "zero_rated", True, False, "/static/images/products/pembe_1kg.jpg", 150, 30, "Grade one sifted white maize flour, finely milled for soft white ugali."),
    ("GRN-PEMB-MZ-2KG", "616110070002", "Pembe Sifted Maize Meal 2kg", "Grains, Flours & Staple Foods", "Pembe", "piece", "2kg", 215.00, 235.00, 178.00, "zero_rated", True, False, "/static/images/products/pembe_2kg.jpg", 200, 40, "Kenya's favourite 2kg unga pack for everyday family cooking."),
    ("GRN-PEMB-MZ-5KG", "616110070003", "Pembe Sifted Maize Meal 5kg Bale", "Grains, Flours & Staple Foods", "Pembe", "piece", "5kg", 520.00, None, 440.00, "zero_rated", True, False, "/static/images/products/pembe_5kg.jpg", 60, 15, "5kg economy family pack of sifted maize flour."),
    ("GRN-JOGO-MZ-1KG", "616110070004", "Jogoo Sifted Maize Meal 1kg", "Grains, Flours & Staple Foods", "Jogoo", "piece", "1kg", 115.00, None, 92.00, "zero_rated", True, False, "/static/images/products/jogoo_1kg.jpg", 130, 25, "Enriched sifted white maize meal fortified with vitamins and iron."),
    ("GRN-JOGO-MZ-2KG", "616110070005", "Jogoo Sifted Maize Meal 2kg", "Grains, Flours & Staple Foods", "Jogoo", "piece", "2kg", 220.00, None, 180.00, "zero_rated", True, False, "/static/images/products/jogoo_2kg.jpg", 180, 35, "The legendary 2kg Jogoo maize flour pack for firm, nutritious ugali."),
    ("GRN-HOST-MZ-2KG", "616110070006", "Hostess Premium Maize Meal 2kg", "Grains, Flours & Staple Foods", "Hostess", "piece", "2kg", 250.00, 270.00, 205.00, "zero_rated", True, False, "/static/images/products/hostess_2kg.jpg", 80, 15, "Premium ultra-white sifted unga for special occasions and superior texture."),
    # Wheat Flour (Unga wa Ngano)
    ("GRN-AJAB-WT-1KG", "616110070010", "Ajab All-Purpose Wheat Flour 1kg", "Grains, Flours & Staple Foods", "Ajab", "piece", "1kg", 105.00, None, 85.00, "zero_rated", True, False, "/static/images/products/ajab_1kg.jpg", 120, 25, "Premium refined wheat flour with high elasticity for layered chapatis and mandazi."),
    ("GRN-AJAB-WT-2KG", "616110070011", "Ajab All-Purpose Wheat Flour 2kg", "Grains, Flours & Staple Foods", "Ajab", "piece", "2kg", 200.00, None, 165.00, "zero_rated", True, False, "/static/images/products/ajab_2kg.jpg", 160, 30, "2kg home baking wheat flour for soft, flaky Kenyan chapatis."),
    ("GRN-EXE-MAND-2KG", "616110070012", "Exe Mandazi Flour Self-Raising 2kg", "Grains, Flours & Staple Foods", "Exe", "piece", "2kg", 225.00, None, 182.00, "zero_rated", True, False, "/static/images/products/exe_mandazi_2kg.jpg", 90, 20, "Specially blended self-raising flour guaranteed to yield golden puffy mandazis."),
    ("GRN-EXE-CHAP-2KG", "616110070013", "Exe Chapati Flour Atta Mark 1 2kg", "Grains, Flours & Staple Foods", "Exe", "piece", "2kg", 215.00, None, 175.00, "zero_rated", True, False, "/static/images/products/exe_chapati_2kg.jpg", 100, 20, "Whole wheat atta flour milled specifically for layered, soft brown chapatis."),
    # Rice
    ("GRN-DAAW-BAS-1KG", "616110070020", "Daawat Traditional Basmati Rice 1kg", "Grains, Flours & Staple Foods", "Daawat", "piece", "1kg", 290.00, None, 235.00, "standard", True, False, "/static/images/products/daawat_basmati_1kg.jpg", 100, 20, "Aged Himalayan long-grain basmati rice with slender, fragrant grains."),
    ("GRN-DAAW-BAS-2KG", "616110070021", "Daawat Traditional Basmati Rice 2kg", "Grains, Flours & Staple Foods", "Daawat", "piece", "2kg", 570.00, 610.00, 465.00, "standard", True, False, "/static/images/products/daawat_basmati_2kg.jpg", 80, 15, "2kg bag of aromatic slender Basmati rice, non-sticky when cooked."),
    ("GRN-DAAW-BAS-5KG", "616110070022", "Daawat Traditional Basmati Rice 5kg", "Grains, Flours & Staple Foods", "Daawat", "piece", "5kg", 1380.00, 1490.00, 1140.00, "standard", True, False, "/static/images/products/daawat_basmati_5kg.jpg", 50, 10, "5kg zip-lock pack of Daawat premium aged basmati rice."),
    ("GRN-PEARL-PIS-2KG", "616110070023", "Pearl Pure Pishori Kenya Rice 2kg", "Grains, Flours & Staple Foods", "Pearl", "piece", "2kg", 470.00, None, 385.00, "standard", True, False, "/static/images/products/pearl_pishori_2kg.jpg", 90, 15, "Grown in Mwea irrigation scheme, naturally fragrant Kenyan pishori rice."),
    # Pulses & Sugar
    ("GRN-BUTT-NDEN-1KG", "616110070030", "Butterfly Polished Green Grams (Ndengu) 1kg", "Grains, Flours & Staple Foods", "Butterfly", "piece", "1kg", 270.00, None, 215.00, "zero_rated", True, False, "/static/images/products/butterfly_ndengu_1kg.jpg", 80, 15, "Cleaned, polished green grams packed with plant-based protein."),
    ("GRN-BUTT-YELB-1KG", "616110070031", "Butterfly Yellow Beans 1kg", "Grains, Flours & Staple Foods", "Butterfly", "piece", "1kg", 280.00, None, 225.00, "zero_rated", True, False, "/static/images/products/butterfly_yellow_beans_1kg.jpg", 70, 15, "Premium yellow beans, easy to boil and gentle on digestion."),
    ("GRN-KABR-SUG-1KG", "616110070040", "Kabras Pure White Sugar 1kg", "Grains, Flours & Staple Foods", "Kabras", "piece", "1kg", 160.00, None, 132.00, "standard", True, False, "/static/images/products/kabras_sugar_1kg.jpg", 150, 30, "Locally processed white cane sugar milled in Western Kenya."),
    ("GRN-KABR-SUG-2KG", "616110070041", "Kabras Pure White Sugar 2kg", "Grains, Flours & Staple Foods", "Kabras", "piece", "2kg", 310.00, None, 260.00, "standard", True, False, "/static/images/products/kabras_sugar_2kg.jpg", 120, 25, "2kg moisture-proof bag of fine crystal cane sugar."),
    ("GRN-INDO-CHIK-70G", "616110070050", "Indomie Instant Noodles Chicken Flavour 70g", "Grains, Flours & Staple Foods", "Indomie", "piece", "70g", 35.00, None, 27.00, "standard", True, False, "/static/images/products/indomie_chicken_70g.jpg", 250, 40, "Quick 3-minute chicken flavoured instant noodles with spice and oil sachets."),
]

OILS_SPICES_PRODUCTS = [
    # Cooking Oils
    ("OIL-FRSH-VEG-1L", "616110080001", "Fresh Fri Vegetable Cooking Oil 1L", "Oils, Spices & Condiments", "Fresh Fri", "piece", "1L", 280.00, None, 230.00, "standard", True, False, "/static/images/products/freshfri_1l.jpg", 100, 20, "Triple refined pure vegetable cooking oil with Ginger & Garlic extract."),
    ("OIL-FRSH-VEG-2L", "616110080002", "Fresh Fri Vegetable Cooking Oil 2L", "Oils, Spices & Condiments", "Fresh Fri", "piece", "2L", 540.00, 570.00, 445.00, "standard", True, False, "/static/images/products/freshfri_2l.jpg", 90, 20, "2-litre bottle of cholesterol-free vegetable cooking oil with measuring cap."),
    ("OIL-FRSH-VEG-3L", "616110080003", "Fresh Fri Vegetable Cooking Oil 3L", "Oils, Spices & Condiments", "Fresh Fri", "piece", "3L", 810.00, None, 675.00, "standard", True, False, "/static/images/products/freshfri_3l.jpg", 60, 15, "3-litre jerrycan of triple refined clear cooking oil."),
    ("OIL-FRSH-VEG-5L", "616110080004", "Fresh Fri Vegetable Cooking Oil 5L", "Oils, Spices & Condiments", "Fresh Fri", "piece", "5L", 1320.00, 1420.00, 1100.00, "standard", True, False, "/static/images/products/freshfri_5l.jpg", 50, 10, "5-litre family jerrycan of pure cooking oil."),
    ("OIL-ELIA-CORN-1L", "616110080005", "Elianto Pure Corn Oil 1L", "Oils, Spices & Condiments", "Elianto", "piece", "1L", 360.00, None, 295.00, "standard", True, False, "/static/images/products/elianto_1l.jpg", 70, 15, "100% natural pure corn oil, golden in color and rich in polyunsaturates."),
    ("OIL-ELIA-CORN-2L", "616110080006", "Elianto Pure Corn Oil 2L", "Oils, Spices & Condiments", "Elianto", "piece", "2L", 690.00, 730.00, 570.00, "standard", True, False, "/static/images/products/elianto_2l.jpg", 60, 12, "2-litre bottle of heart-friendly 100% corn cooking oil."),
    # Cooking Fats & Margarine
    ("OIL-KIMB-FAT-500G", "616110080010", "Kimbo Pure White Cooking Fat 500g", "Oils, Spices & Condiments", "Kimbo", "piece", "500g", 195.00, None, 160.00, "standard", True, False, "/static/images/products/kimbo_500g.jpg", 85, 15, "Kenya's traditional white vegetable cooking fat for frying and fluffy chapatis."),
    ("OIL-KIMB-FAT-1KG", "616110080011", "Kimbo Pure White Cooking Fat 1kg", "Oils, Spices & Condiments", "Kimbo", "piece", "1kg", 380.00, None, 310.00, "standard", True, False, "/static/images/products/kimbo_1kg.jpg", 65, 12, "1kg tub of pure vegetable cooking fat."),
    ("OIL-BB-ORIG-250G", "616110080020", "Blue Band Original Margarine 250g", "Oils, Spices & Condiments", "Blue Band", "piece", "250g", 140.00, None, 112.00, "standard", True, False, "/static/images/products/blueband_250g.jpg", 110, 20, "Fortified spread with Omega 3 & 6 and 7 essential vitamins for kids growth."),
    ("OIL-BB-ORIG-500G", "616110080021", "Blue Band Original Margarine 500g", "Oils, Spices & Condiments", "Blue Band", "piece", "500g", 260.00, None, 212.00, "standard", True, False, "/static/images/products/blueband_500g.jpg", 95, 20, "Medium 500g tub of nutritious Blue Band spread."),
    ("OIL-BB-ORIG-1KG", "616110080022", "Blue Band Original Margarine 1kg", "Oils, Spices & Condiments", "Blue Band", "piece", "1kg", 500.00, 540.00, 410.00, "standard", True, False, "/static/images/products/blueband_1kg.jpg", 60, 10, "Family 1kg tub of Blue Band enriched margarine."),
    ("OIL-BB-PBUT-400G", "616110080023", "Blue Band Creamy Peanut Butter 400g", "Oils, Spices & Condiments", "Blue Band", "piece", "400g", 310.00, None, 250.00, "standard", True, False, "/static/images/products/blueband_pb_400g.jpg", 55, 10, "Smooth roasted peanut butter spread, rich in natural protein."),
    # Seasonings & Spices
    ("OIL-KEN-SALT-1KG", "616110080030", "Kensalt Iodised Table Salt 1kg", "Oils, Spices & Condiments", "Kensalt", "piece", "1kg", 45.00, None, 35.00, "standard", True, False, "/static/images/products/kensalt_1kg.jpg", 200, 40, "Finely refined iodised sea salt from Malindi salt works."),
    ("OIL-KEN-SALT-2KG", "616110080031", "Kensalt Iodised Table Salt 2kg", "Oils, Spices & Condiments", "Kensalt", "piece", "2kg", 85.00, None, 68.00, "standard", True, False, "/static/images/products/kensalt_2kg.jpg", 150, 30, "2kg value packet of pure free-flowing table salt."),
    ("OIL-ROY-MCH-B200G", "616110080040", "Royco Mchuzi Mix Beef Jar 200g", "Oils, Spices & Condiments", "Royco", "piece", "200g", 145.00, None, 118.00, "standard", True, False, "/static/images/products/royco_beef_200g.jpg", 120, 25, "Kenya's essential savoury seasoning powder for thickening stews and deepening beef flavor."),
    ("OIL-ROY-MCH-C200G", "616110080041", "Royco Mchuzi Mix Chicken Jar 200g", "Oils, Spices & Condiments", "Royco", "piece", "200g", 145.00, None, 118.00, "standard", True, False, "/static/images/products/royco_chicken_200g.jpg", 90, 20, "Aromatic chicken flavoured stew thickener and seasoning powder."),
    ("OIL-ROY-CUBE-B40S", "616110080042", "Royco Beef Seasoning Cubes Pack of 40", "Oils, Spices & Condiments", "Royco", "piece", "Pack of 40", 160.00, None, 128.00, "standard", True, False, "/static/images/products/royco_cubes_40s.jpg", 80, 15, "Concentrated beef seasoning stock cubes with natural herbs and spices."),
    ("OIL-TH-PILAU-100G", "616110080043", "Tropical Heat Pilau Masala Ground 100g", "Oils, Spices & Condiments", "Tropical Heat", "piece", "100g", 115.00, None, 90.00, "standard", True, False, "/static/images/products/th_pilau_100g.jpg", 85, 15, "Authentic blend of cumin, cinnamon, cardamom and cloves for festive Swahili pilau."),
    ("OIL-PEP-SAUC-400G", "616110080050", "Peptang Tomato Sauce 400g", "Oils, Spices & Condiments", "Peptang", "piece", "400g", 135.00, None, 108.00, "standard", True, False, "/static/images/products/peptang_sauce_400g.jpg", 90, 20, "Traditional rich tomato ketchup made with ripe Kenyan tomatoes."),
]

PRODUCE_MEAT_PRODUCTS = [
    # Kenchic & Poultry
    ("PRD-KENC-CHIK-12KG", "616110090001", "Kenchic Fresh Whole Broiler Chicken ~1.2kg", "Meat, Poultry & Fresh Produce", "Kenchic", "piece", "1.2kg", 680.00, 720.00, 560.00, "zero_rated", True, False, "/static/images/products/kenchic_whole_12kg.jpg", 40, 10, "Fresh whole broiler chicken, hygienically cleaned, dressed and chilled."),
    ("PRD-KENC-BREA-500G", "616110090002", "Kenchic Fresh Chicken Breast Fillets 500g", "Meat, Poultry & Fresh Produce", "Kenchic", "piece", "500g", 490.00, None, 400.00, "zero_rated", True, False, "/static/images/products/kenchic_breast_500g.jpg", 35, 8, "Lean, skinless and boneless tender chicken breast fillets."),
    ("PRD-KENC-DRUM-1KG", "616110090003", "Kenchic Fresh Chicken Drumsticks 1kg", "Meat, Poultry & Fresh Produce", "Kenchic", "piece", "1kg", 720.00, None, 590.00, "zero_rated", True, False, "/static/images/products/kenchic_drumsticks_1kg.jpg", 30, 8, "Succulent chicken drumsticks, perfect for grilling, braising or frying."),
    # Butchery & Sausages
    ("PRD-FC-BEEF-SAUS-1K", "616110090010", "Farmer's Choice Beef Sausages 1kg", "Meat, Poultry & Fresh Produce", "Farmer's Choice", "piece", "1kg", 690.00, 740.00, 565.00, "standard", True, False, "/static/images/products/fc_beef_sausages_1kg.jpg", 50, 10, "Kenya's premier spiced beef breakfast sausages."),
    ("PRD-FC-SMOK-500G", "616110090011", "Farmer's Choice Smokies 500g", "Meat, Poultry & Fresh Produce", "Farmer's Choice", "piece", "500g", 290.00, None, 235.00, "standard", True, False, "/static/images/products/fc_smokies_500g.jpg", 70, 15, "Ready-to-eat smoked sausages, the iconic street food staple."),
    ("PRD-MEAT-BEEF-STK-1K", "616110090020", "Prime Beef Steak Boneless 1kg", "Meat, Poultry & Fresh Produce", "Bansi Butchery", "kg", "1kg", 650.00, None, 530.00, "zero_rated", True, False, "/static/images/products/beef_steak_1kg.jpg", 60, 15, "Tender cut pasture-grazed boneless beef steak, freshly trimmed daily."),
    ("PRD-MEAT-BEEF-MINC-1K", "616110090021", "Lean Minced Beef 1kg", "Meat, Poultry & Fresh Produce", "Bansi Butchery", "kg", "1kg", 680.00, None, 550.00, "zero_rated", True, False, "/static/images/products/beef_mince_1kg.jpg", 45, 10, "Freshly ground extra lean beef mince, 90% lean meat ratio."),
    ("PRD-MEAT-GOAT-NYAM-1K", "616110090022", "Goat Meat Nyama Choma Cut 1kg", "Meat, Poultry & Fresh Produce", "Bansi Butchery", "kg", "1kg", 750.00, None, 610.00, "zero_rated", True, False, "/static/images/products/goat_nyama_1kg.jpg", 50, 12, "Prime goat ribs and shoulder cuts portioned for traditional barbecue (nyama choma)."),
    ("PRD-FISH-TILAP-MED", "616110090023", "Fresh Lake Victoria Whole Tilapia Medium 500g", "Meat, Poultry & Fresh Produce", "Bansi Fishmonger", "piece", "500g", 350.00, None, 280.00, "zero_rated", True, False, "/static/images/products/tilapia_500g.jpg", 30, 8, "Fresh wild-caught whole Lake Victoria tilapia fish, descaled and gutted."),
    # Fresh Vegetables & Fruits
    ("PRD-VEG-SUKU-BUN", "616110090030", "Sukuma Wiki (Collard Greens) Fresh Bunch ~500g", "Meat, Poultry & Fresh Produce", "Bansi Greens", "piece", "Bunch (~500g)", 30.00, None, 18.00, "exempt", True, False, "/static/images/products/sukuma_wiki.jpg", 80, 20, "Crisp, dark green local collard greens harvested fresh from local farms."),
    ("PRD-VEG-SPIN-BUN", "616110090031", "Fresh Spinach Bunch ~500g", "Meat, Poultry & Fresh Produce", "Bansi Greens", "piece", "Bunch (~500g)", 35.00, None, 22.00, "exempt", True, False, "/static/images/products/spinach_bunch.jpg", 70, 15, "Tender spinach leaves, freshly picked and rinsed."),
    ("PRD-VEG-ONIO-RED-1KG", "616110090032", "Local Red Onions 1kg Net", "Meat, Poultry & Fresh Produce", "Bansi Greens", "kg", "1kg", 140.00, None, 105.00, "exempt", True, False, "/static/images/products/red_onions_1kg.jpg", 100, 25, "Firm, dry-skinned pungent red onions packed in breathable 1kg netting."),
    ("PRD-VEG-POTA-SHAN-2KG", "616110090033", "Fresh Irish Potatoes (Shangi) 2kg Bag", "Meat, Poultry & Fresh Produce", "Bansi Greens", "piece", "2kg", 190.00, None, 145.00, "exempt", True, False, "/static/images/products/shangi_potatoes_2kg.jpg", 90, 20, "Highland Shangi variety potatoes, excellent for boiling, mashing or deep frying."),
    ("PRD-VEG-TOMA-RED-1KG", "616110090034", "Fresh Salad Tomatoes 1kg", "Meat, Poultry & Fresh Produce", "Bansi Greens", "kg", "1kg", 130.00, None, 95.00, "exempt", True, False, "/static/images/products/tomatoes_1kg.jpg", 90, 20, "Firm, sun-ripened red greenhouse tomatoes, juicy and flavorful."),
    ("PRD-FRU-AVOC-HASS", "616110090040", "Export Quality Hass Avocado 1 Piece", "Meat, Poultry & Fresh Produce", "Bansi Greens", "piece", "1 Piece", 40.00, None, 25.00, "exempt", True, False, "/static/images/products/hass_avocado.jpg", 150, 30, "Creamy, rich Hass variety avocado with dark pebbled skin when ripe."),
]

PERSONAL_CARE_PRODUCTS = [
    # Bathing Soaps
    ("PER-GEIS-ALOE-225G", "616110100001", "Geisha Aloe Vera Long Lasting Soap 225g", "Personal Care & Grooming", "Geisha", "piece", "225g", 120.00, None, 96.00, "standard", True, False, "/static/images/products/geisha_aloe_225g.jpg", 120, 25, "Infused with natural aloe vera extracts, long-lasting bar for soft healthy skin."),
    ("PER-GEIS-SHEA-225G", "616110100002", "Geisha Shea Butter Soap 225g", "Personal Care & Grooming", "Geisha", "piece", "225g", 120.00, None, 96.00, "standard", True, False, "/static/images/products/geisha_shea_225g.jpg", 100, 20, "Moisturizing bath soap bar with African shea butter."),
    ("PER-DETT-ORIG-175G", "616110100003", "Dettol Original Antiseptic Bathing Soap 175g", "Personal Care & Grooming", "Dettol", "piece", "175g", 155.00, None, 124.00, "standard", True, False, "/static/images/products/dettol_soap_175g.jpg", 110, 20, "Trusted pine fragrance antibacterial bar soap protecting against 99.9% of germs."),
    ("PER-LIFE-TOT10-175G", "616110100004", "Lifebuoy Total 10 Germ Protection Soap 175g", "Personal Care & Grooming", "Lifebuoy", "piece", "175g", 115.00, None, 92.00, "standard", True, False, "/static/images/products/lifebuoy_total10_175g.jpg", 90, 20, "Advanced germ protection bar soap powered by Activ Silver formula."),
    # Oral Care
    ("PER-COLG-MAXC-140ML", "616110100010", "Colgate Maximum Cavity Protection 140ml", "Personal Care & Grooming", "Colgate", "piece", "140ml", 165.00, None, 130.00, "standard", True, False, "/static/images/products/colgate_cavity_140ml.jpg", 110, 25, "Great regular flavour fluoride toothpaste with calcium for stronger teeth."),
    ("PER-COLG-TOT12-100ML", "616110100011", "Colgate Total 12 Pro Gum Health 100ml", "Personal Care & Grooming", "Colgate", "piece", "100ml", 280.00, 310.00, 222.00, "standard", True, False, "/static/images/products/colgate_total_100ml.jpg", 70, 15, "12-hour antibacterial protection for whole mouth health and fresh breath."),
    ("PER-CLOS-REDH-140G", "616110100012", "Close Up Red Hot Gel Toothpaste 140g", "Personal Care & Grooming", "Close Up", "piece", "140g", 175.00, None, 138.00, "standard", True, False, "/static/images/products/closeup_redhot_140g.jpg", 85, 15, "Anti-bacterial zinc gel toothpaste with spicy red hot clove breath freshener."),
    # Skin & Hair Care
    ("PER-VASE-BLUE-100ML", "616110100020", "Vaseline Pure Petroleum Jelly Blue Seal 100ml", "Personal Care & Grooming", "Vaseline", "piece", "100ml", 120.00, None, 95.00, "standard", True, False, "/static/images/products/vaseline_100ml.jpg", 100, 20, "Triple-purified original petroleum jelly, locks in moisture to heal dry skin."),
    ("PER-VASE-BLUE-250ML", "616110100021", "Vaseline Pure Petroleum Jelly Blue Seal 250ml", "Personal Care & Grooming", "Vaseline", "piece", "250ml", 240.00, None, 190.00, "standard", True, False, "/static/images/products/vaseline_250ml.jpg", 80, 15, "Family tub of authentic Vaseline Blue Seal petroleum jelly."),
    ("PER-NIVE-RICH-400ML", "616110100022", "Nivea Rich Nourishing Body Lotion 400ml", "Personal Care & Grooming", "Nivea", "piece", "400ml", 580.00, 620.00, 460.00, "standard", True, False, "/static/images/products/nivea_rich_400ml.jpg", 65, 12, "48-hour intensive moisturizing lotion enriched with natural almond oil."),
    ("PER-NIVE-ROLL-MEN50", "616110100023", "Nivea Men Deep Black Carbon Roll-On 50ml", "Personal Care & Grooming", "Nivea", "piece", "50ml", 260.00, None, 205.00, "standard", True, False, "/static/images/products/nivea_men_deep_50ml.jpg", 75, 15, "Anti-perspirant roll-on with black charcoal, 48-hour powerful dry protection."),
    ("PER-NL-COCO-400ML", "616110100024", "Nice & Lovely Cocoa Butter Body Lotion 400ml", "Personal Care & Grooming", "Nice & Lovely", "piece", "400ml", 280.00, None, 220.00, "standard", True, False, "/static/images/products/nl_cocoa_400ml.jpg", 90, 15, "Enriched with cocoa butter, shea butter, almond oil and sunscreen for radiant glow."),
    # Sanitary & Shaving
    ("PER-ALW-MAXI-16S", "616110100030", "Always Maxi Thick Sanitary Pads 16s", "Personal Care & Grooming", "Always", "piece", "Pack of 16", 180.00, None, 142.00, "standard", True, False, "/static/images/products/always_maxi_16s.jpg", 110, 20, "Extra absorbent thick sanitary pads with leak guard barriers and wings."),
    ("PER-ALW-ULTR-16S", "616110100031", "Always Ultra Thin Long Pads with Wings 16s", "Personal Care & Grooming", "Always", "piece", "Pack of 16", 220.00, None, 175.00, "standard", True, False, "/static/images/products/always_ultra_16s.jpg", 95, 20, "Ultra-thin flexible pads with gel core for maximum discreet comfort."),
    ("PER-GIL-BLUE2-5S", "616110100040", "Gillette Blue II Plus Disposable Razors 5s", "Personal Care & Grooming", "Gillette", "piece", "Pack of 5", 260.00, None, 205.00, "standard", True, False, "/static/images/products/gillette_blue2_5s.jpg", 70, 15, "Twin blade pivoting head disposable razors with lubricating aloe strip."),
]

HOUSEHOLD_PRODUCTS = [
    # Laundry Powders & Bar Soaps
    ("HOU-ARIE-DOWN-1KG", "616110110001", "Ariel Downy Hand Wash Washing Powder 1kg", "Household & Cleaning", "Ariel", "piece", "1kg", 350.00, None, 280.00, "standard", True, False, "/static/images/products/ariel_downy_1kg.jpg", 100, 20, "Tough stain removal in one wash with floral freshness of Downy perfume."),
    ("HOU-ARIE-DOWN-2KG", "616110110002", "Ariel Downy Hand Wash Washing Powder 2kg", "Household & Cleaning", "Ariel", "piece", "2kg", 680.00, 720.00, 545.00, "standard", True, False, "/static/images/products/ariel_downy_2kg.jpg", 75, 15, "2kg family pack of Ariel with Downy fragrance."),
    ("HOU-OMO-FAST-1KG", "616110110003", "Omo Fast Action Hand Wash Powder 1kg", "Household & Cleaning", "Omo", "piece", "1kg", 340.00, None, 272.00, "standard", True, False, "/static/images/products/omo_fast_1kg.jpg", 90, 20, "Power foam formula penetrates deep fibres to remove stubborn oily stains fast."),
    ("HOU-SUNL-PWDR-1KG", "616110110004", "Sunlight 2in1 Spring Sensations Powder 1kg", "Household & Cleaning", "Sunlight", "piece", "1kg", 310.00, None, 248.00, "standard", True, False, "/static/images/products/sunlight_powder_1kg.jpg", 95, 20, "Cleans thoroughly and leaves a burst of long-lasting spring sensation fragrance."),
    ("HOU-MENE-BAR-800G", "616110110010", "Menengai White Laundry Bar Soap 800g", "Household & Cleaning", "Menengai", "piece", "800g", 175.00, None, 140.00, "standard", True, False, "/static/images/products/menengai_bar_800g.jpg", 120, 25, "Traditional solid white laundry bar soap, gentle on hands and tough on dirt."),
    ("HOU-SUNL-BAR-800G", "616110110011", "Sunlight Lemon Fresh Bar Soap 800g", "Household & Cleaning", "Sunlight", "piece", "800g", 185.00, None, 148.00, "standard", True, False, "/static/images/products/sunlight_bar_800g.jpg", 100, 20, "Yellow laundry bar soap with real lemon juice for sparkling clean clothes."),
    # Dishwashing & Bleach
    ("HOU-SUNL-DISH-750ML", "616110110020", "Sunlight Dishwashing Liquid Lemon 750ml", "Household & Cleaning", "Sunlight", "piece", "750ml", 270.00, None, 215.00, "standard", True, False, "/static/images/products/sunlight_dish_750ml.jpg", 80, 15, "Cuts grease fast with real lemon juice, leaving dishes sparkling clean."),
    ("HOU-MORN-DISH-450ML", "616110110021", "Morning Fresh Dishwashing Liquid 450ml", "Household & Cleaning", "Morning Fresh", "piece", "450ml", 220.00, None, 175.00, "standard", True, False, "/static/images/products/morning_fresh_450ml.jpg", 85, 15, "Super concentrated formula: just one drop washes up to 100 plates."),
    ("HOU-JIK-REG-750ML", "616110110030", "Jik Regular Bleach 750ml", "Household & Cleaning", "Jik", "piece", "750ml", 195.00, None, 155.00, "standard", True, False, "/static/images/products/jik_regular_750ml.jpg", 90, 20, "All-purpose household bleach, whitens whites and kills 99.9% of germs."),
    ("HOU-HARP-POW-500ML", "616110110031", "Harpic Power Plus Toilet Cleaner 500ml", "Household & Cleaning", "Harpic", "piece", "500ml", 270.00, None, 215.00, "standard", True, False, "/static/images/products/harpic_original_500ml.jpg", 80, 15, "10x better limescale and stain removal than standard bleach."),
    # Pest Control & Paper
    ("HOU-DOOM-AERO-400ML", "616110110040", "Doom Multi-Insect Killer Aerosol 400ml", "Household & Cleaning", "Doom", "piece", "400ml", 450.00, 480.00, 360.00, "standard", True, False, "/static/images/products/doom_aerosol_400ml.jpg", 70, 15, "Fast knockdown spray deadly to mosquitoes, flies, cockroaches and ants."),
    ("HOU-VELV-TOIL-10S", "616110110050", "Velvet 2-Ply Toilet Rolls Pack of 10", "Household & Cleaning", "Velvet", "piece", "Pack of 10", 520.00, 560.00, 415.00, "standard", True, False, "/static/images/products/velvet_toilet_10s.jpg", 75, 15, "Ultra soft and absorbent embossed 2-ply white virgin tissue rolls."),
    ("HOU-HANA-TISS-150S", "616110110051", "Hanan Facial Tissues 2-Ply 150 Sheets", "Household & Cleaning", "Hanan", "piece", "150 Sheets", 140.00, None, 110.00, "standard", True, False, "/static/images/products/hanan_tissues_150s.jpg", 90, 20, "Soft, strong, and gentle facial tissue box for family use."),
]

BABY_PRODUCTS = [
    # Diapers & Wipes
    ("BAB-PAMP-BDRY-SZ3", "616110120001", "Pampers Baby-Dry Pants Size 3 (6-11kg) 54s", "Baby Care & Kids", "Pampers", "piece", "Pack of 54", 1450.00, 1550.00, 1180.00, "standard", True, False, "/static/images/products/pampers_dry_sz3.jpg", 50, 10, "Up to 12 hours of all-round leakage protection with absorbent micro-pearls."),
    ("BAB-PAMP-BDRY-SZ4", "616110120002", "Pampers Baby-Dry Pants Size 4 (9-14kg) 48s", "Baby Care & Kids", "Pampers", "piece", "Pack of 48", 1450.00, 1550.00, 1180.00, "standard", True, False, "/static/images/products/pampers_dry_sz4.jpg", 55, 10, "Pull-up pants diaper for active crawling and walking toddlers."),
    ("BAB-SOFT-DIAP-MIDI", "616110120003", "Softcare Baby Diapers Midi (Size 3) 32s", "Baby Care & Kids", "Softcare", "piece", "Pack of 32", 620.00, None, 500.00, "standard", True, False, "/static/images/products/softcare_midi_32s.jpg", 70, 15, "Soft, breathable diaper core with wetness indicator at affordable value."),
    ("BAB-JOH-WIPES-56S", "616110120010", "Johnson's Baby Gentle Cleansing Wipes 56s", "Baby Care & Kids", "Johnson's", "piece", "Pack of 56", 240.00, None, 190.00, "standard", True, False, "/static/images/products/johnsons_wipes_56s.jpg", 80, 15, "Alcohol-free wipes formulated with pure water to gently cleanse delicate baby skin."),
    # Toiletries & Food
    ("BAB-JOH-OIL-200ML", "616110120020", "Johnson's Baby Oil Regular 200ml", "Baby Care & Kids", "Johnson's", "piece", "200ml", 390.00, None, 310.00, "standard", True, False, "/static/images/products/johnsons_oil_200ml.jpg", 60, 12, "Locks in up to 10 times more moisture on wet skin than ordinary lotions."),
    ("BAB-JOH-POWD-200G", "616110120021", "Johnson's Baby Powder Regular 200g", "Baby Care & Kids", "Johnson's", "piece", "200g", 290.00, None, 230.00, "standard", True, False, "/static/images/products/johnsons_powder_200g.jpg", 65, 12, "Clinically proven mild formula, absorbs moisture to keep baby skin cool and dry."),
    ("BAB-CUSS-SOAP-100G", "616110120022", "Cussons Baby Soap Mild & Gentle 100g", "Baby Care & Kids", "Cussons", "piece", "100g", 90.00, None, 70.00, "standard", True, False, "/static/images/products/cussons_soap_100g.jpg", 90, 20, "Dermatologically tested gentle baby bath soap with milk and chamomile."),
    ("BAB-CER-WHT-400G", "616110120030", "Nestle Cerelac Wheat & Milk Baby Cereal 400g", "Baby Care & Kids", "Nestle", "piece", "400g", 490.00, None, 395.00, "standard", True, False, "/static/images/products/cerelac_wheat_400g.jpg", 75, 15, "Fortified infant cereal with iron, vitamins A, C & B12 for infants from 6 months."),
    ("BAB-NAN-PRO1-400G", "616110120031", "Nestle Nan Pro 1 Infant Formula 400g", "Baby Care & Kids", "Nestle", "piece", "400g", 1350.00, 1420.00, 1100.00, "standard", True, False, "/static/images/products/nan_pro_1_400g.jpg", 40, 8, "Starter infant formula with probiotic Bifidus BL and DHA for babies 0-6 months."),
]

ELECTRONICS_PRODUCTS = [
    # Kitchen & Appliances
    ("ELE-RAM-GAS-2BRN", "616110130001", "Ramtons 2-Burner Glass Table Top Cooker RM/281", "Electronics & Appliances", "Ramtons", "piece", "1 Unit", 4800.00, 5200.00, 3900.00, "standard", True, False, "/static/images/products/ramtons_cooker_rm281.jpg", 20, 5, "Toughened black glass top 2-burner gas stove with auto-ignition and high efficiency burners."),
    ("ELE-RAM-MICR-20L", "616110130002", "Ramtons 20L Solo Microwave Oven RM/385", "Electronics & Appliances", "Ramtons", "piece", "1 Unit", 9200.00, 9900.00, 7500.00, "standard", True, False, "/static/images/products/ramtons_microwave_rm385.jpg", 15, 3, "Compact 20-litre microwave with 5 power levels, defrost timer and easy manual dial controls."),
    ("ELE-RAM-KETT-17L", "616110130003", "Ramtons Stainless Steel Electric Kettle 1.7L RM/338", "Electronics & Appliances", "Ramtons", "piece", "1 Unit", 2400.00, None, 1920.00, "standard", True, False, "/static/images/products/ramtons_kettle_rm338.jpg", 35, 8, "Fast boil cordless kettle with 360-degree rotational base and concealed heating element."),
    ("ELE-BRU-IRON-1000W", "616110130004", "Bruhm Heavy Dry Iron Box 1000W BDI-100", "Electronics & Appliances", "Bruhm", "piece", "1 Unit", 1600.00, None, 1280.00, "standard", True, False, "/static/images/products/bruhm_iron_bdi100.jpg", 40, 8, "Classic heavyweight non-stick soleplate dry iron with adjustable thermostat."),
    ("ELE-MIKA-BLEN-15L", "616110130005", "Mika 1.5L Table Blender with Mill Grinder MBLR451", "Electronics & Appliances", "Mika", "piece", "1 Unit", 3450.00, 3800.00, 2750.00, "standard", True, False, "/static/images/products/mika_blender_mblr451.jpg", 25, 5, "Durable stainless steel 4-blade motor, 2 speeds with pulse and dry mill attachment."),
    ("ELE-SAYO-SUB-21CH", "616110130006", "Sayona 2.1 Channel Subwoofer Sound System SHT-1132", "Electronics & Appliances", "Sayona", "piece", "1 Unit", 6800.00, 7400.00, 5400.00, "standard", True, False, "/static/images/products/sayona_subwoofer_1132.jpg", 18, 4, "Deep bass multimedia sound system with Bluetooth, USB/SD playback and FM radio."),
    # TVs & Smart Entertainment
    ("ELE-VIT-TV-32SM", "616110130010", "Vitron 32-Inch Frameless Smart Android TV HTC3200S", "Electronics & Appliances", "Vitron", "piece", "1 Unit", 13500.00, 14800.00, 11200.00, "standard", True, False, "/static/images/products/vitron_32_smart.jpg", 20, 4, "HD resolution frameless design Smart TV with built-in Netflix, YouTube and Wi-Fi."),
    ("ELE-VIT-TV-43UHD", "616110130011", "Vitron 43-Inch 4K UHD Smart Android TV HTC4300S", "Electronics & Appliances", "Vitron", "piece", "1 Unit", 24900.00, 26900.00, 20500.00, "standard", True, False, "/static/images/products/vitron_43_uhd.jpg", 12, 3, "Ultra High Definition 4K Smart TV with Dolby Audio and voice remote control."),
    # Mobile Accessories & Power
    ("ELE-ORA-PB-20000", "616110130020", "Oraimo 20000mAh Toast 10 Flash Power Bank OPB-P204DQ", "Electronics & Appliances", "Oraimo", "piece", "1 Unit", 2700.00, 3000.00, 2150.00, "standard", True, False, "/static/images/products/oraimo_powerbank_20k.jpg", 45, 10, "High-capacity power bank with 20W dual fast charging and multi-protect safety chip."),
    ("ELE-ORA-CHG-20W", "616110130021", "Oraimo 20W USB-C Fast Charger Kit OCW-U67S", "Electronics & Appliances", "Oraimo", "piece", "1 Kit", 1150.00, None, 880.00, "standard", True, False, "/static/images/products/oraimo_charger_20w.jpg", 60, 15, "Power Delivery 20W fast wall charger with durable braided Type-C cable."),
    ("ELE-ORA-BUDS-FP4", "616110130022", "Oraimo FreePods 4 Active Noise Cancelling Earbuds", "Electronics & Appliances", "Oraimo", "piece", "1 Unit", 3600.00, 3950.00, 2850.00, "standard", True, False, "/static/images/products/oraimo_freepods_4.jpg", 30, 8, "Wireless Bluetooth 5.2 earbuds with ANC, 35.5-hour total playtime and bass boost."),
    ("ELE-SON-EXT-4WAY", "616110130030", "Sonlink 4-Way Surge Protector Extension Socket 3M", "Electronics & Appliances", "Sonlink", "piece", "1 Unit", 850.00, None, 650.00, "standard", True, False, "/static/images/products/sonlink_4way_3m.jpg", 50, 10, "Heavy-duty power extension cord with individual power switches and surge indicator."),
]

FURNITURE_PRODUCTS = [
    # Kenpoly Furniture
    ("FUR-KENP-ARM-MAR", "616110140001", "Kenpoly Heavy Duty Marina Plastic Armchair", "Furniture & Home Living", "Kenpoly", "piece", "1 Piece", 1250.00, None, 980.00, "standard", True, False, "/static/images/products/kenpoly_armchair_marina.jpg", 50, 10, "Stackable heavy-gauge virgin plastic armchair with ergonomic backrest and arms."),
    ("FUR-KENP-DIN-CLAS", "616110140002", "Kenpoly Classic Restaurant Dining Chair", "Furniture & Home Living", "Kenpoly", "piece", "1 Piece", 950.00, None, 750.00, "standard", True, False, "/static/images/products/kenpoly_dining_chair.jpg", 60, 12, "Durable armless plastic chair designed for commercial and domestic dining setups."),
    ("FUR-KENP-TAB-R90", "616110140003", "Kenpoly Round 4-Seater Plastic Dining Table 90cm", "Furniture & Home Living", "Kenpoly", "piece", "1 Unit", 3800.00, 4200.00, 3000.00, "standard", True, False, "/static/images/products/kenpoly_round_table.jpg", 20, 5, "Weather-proof round plastic dining and patio table with sturdy detachable legs."),
    # Mattresses & Bedding
    ("FUR-SUPR-MAT-3X6", "616110140010", "Supreme High Density Foam Mattress 3x6x6 inches", "Furniture & Home Living", "Supreme", "piece", "1 Unit", 6800.00, 7400.00, 5400.00, "standard", True, False, "/static/images/products/supreme_mattress_3x6.jpg", 25, 5, "Single bed high density firm mattress engineered for lasting spine support."),
    ("FUR-SUPR-MAT-4X6", "616110140011", "Supreme High Density Foam Mattress 4x6x6 inches", "Furniture & Home Living", "Supreme", "piece", "1 Unit", 8900.00, 9600.00, 7100.00, "standard", True, False, "/static/images/products/supreme_mattress_4x6.jpg", 20, 4, "Double bed durable foam mattress wrapped in quilted jacquard fabric."),
    ("FUR-SUPR-ORTH-5X6", "616110140012", "Supreme Orthopedic Rebonded Mattress 5x6x8 inches", "Furniture & Home Living", "Supreme", "piece", "1 Unit", 16500.00, 18000.00, 13200.00, "standard", True, False, "/static/images/products/supreme_ortho_5x6.jpg", 12, 3, "Queen size medical grade high-resilience orthopedic mattress for back ache relief."),
    ("FUR-BEDS-COT-5X6", "616110140020", "Superform Pure Cotton Bed Sheet Set 5x6 with 2 Pillowcases", "Furniture & Home Living", "Superform", "piece", "1 Set", 1850.00, None, 1450.00, "standard", True, False, "/static/images/products/bedsheet_set_5x6.jpg", 40, 8, "Breathable 100% natural cotton fitted bedsheet set with matching pillow covers."),
    # Storage & Home Living
    ("FUR-RACK-SHOE-4T", "616110140030", "Metallic 4-Tier Shoe Rack Stainless Steel Frame", "Furniture & Home Living", "HomeStyle", "piece", "1 Unit", 1800.00, None, 1380.00, "standard", True, False, "/static/images/products/shoe_rack_4tier.jpg", 35, 8, "Sturdy multi-layer shoe organizer rack holding up to 16 pairs of footwear."),
    ("FUR-RACK-DISH-3T", "616110140031", "Chrome 3-Tier Kitchen Dish Drainer Rack with Tray", "Furniture & Home Living", "HomeStyle", "piece", "1 Unit", 2400.00, None, 1850.00, "standard", True, False, "/static/images/products/dish_rack_3tier.jpg", 30, 6, "Anti-rust chrome plated dish organizer with removable plastic drain tray."),
    ("FUR-KENP-BUCK-20L", "616110140040", "Kenpoly 20-Litre Plastic Bucket with Handle & Lid", "Furniture & Home Living", "Kenpoly", "piece", "1 Piece", 420.00, None, 320.00, "standard", True, False, "/static/images/products/kenpoly_bucket_20l.jpg", 60, 15, "Multi-purpose water storage bucket with airtight lid and galvanized steel wire handle."),
    ("FUR-WOOD-COFF-TAB", "616110140050", "Modern 2-Tier Wooden Living Room Coffee Table", "Furniture & Home Living", "Bansi Home", "piece", "1 Unit", 5600.00, 6200.00, 4300.00, "standard", True, False, "/static/images/products/wooden_coffee_table.jpg", 15, 3, "Laminated dark walnut finish coffee table with convenient lower storage shelf."),
]

PHARMACY_PRODUCTS = [
    # Pain & Fever
    ("MED-PAN-ADV-10S", "616110150001", "Panadol Advance 500mg Paracetamol 10 Tablets", "Pharmacy & Healthcare", "Panadol", "piece", "Pack of 10", 60.00, None, 45.00, "exempt", True, False, "/static/images/products/panadol_advance_10s.jpg", 200, 40, "Fast-absorbing paracetamol with Optizorb technology for rapid headache relief."),
    ("MED-PAN-ADV-100S", "616110150002", "Panadol Advance 500mg Paracetamol Box 100 Tablets", "Pharmacy & Healthcare", "Panadol", "piece", "Box of 100", 550.00, 600.00, 420.00, "exempt", True, False, "/static/images/products/panadol_advance_100s.jpg", 60, 15, "Dispensing box of 10 blister strips of 10 Panadol Advance tablets."),
    ("MED-PAN-EXT-10S", "616110150003", "Panadol Extra with Caffeine 10 Tablets", "Pharmacy & Healthcare", "Panadol", "piece", "Pack of 10", 90.00, None, 70.00, "exempt", True, False, "/static/images/products/panadol_extra_10s.jpg", 150, 30, "Formulated with caffeine to amplify paracetamol pain relief against tough headaches."),
    ("MED-HEDX-EXT-10S", "616110150004", "Hedex Extra Strength Pain Relief 10 Tablets", "Pharmacy & Healthcare", "Hedex", "piece", "Pack of 10", 85.00, None, 65.00, "exempt", True, False, "/static/images/products/hedex_extra_10s.jpg", 140, 25, "Dual action headache and muscle ache relief tablets."),
    ("MED-MARA-MOJ-10S", "616110150005", "Mara Moja Fast Pain Relief 10 Tablets", "Pharmacy & Healthcare", "Mara Moja", "piece", "Pack of 10", 70.00, None, 52.00, "exempt", True, False, "/static/images/products/maramoja_10s.jpg", 160, 30, "Trusted quick acting pain killer formulation for severe headaches and body pains."),
    ("MED-CALP-INF-100ML", "616110150006", "Calpol Infant Paracetamol Suspension 120mg/5ml 100ml", "Pharmacy & Healthcare", "Calpol", "piece", "100ml", 340.00, None, 270.00, "exempt", True, False, "/static/images/products/calpol_infant_100ml.jpg", 70, 15, "Strawberry flavored sugar-free oral suspension soothing fever and pain in infants."),
    # Cold & Throat
    ("MED-STRP-HON-24S", "616110150010", "Strepsils Honey & Lemon Sore Throat Lozenges 24s", "Pharmacy & Healthcare", "Strepsils", "piece", "Pack of 24", 380.00, None, 300.00, "exempt", True, False, "/static/images/products/strepsils_honey_24s.jpg", 90, 20, "Dual antibacterial action for soothing relief from sore throats and mouth infections."),
    ("MED-VIC-VAPO-50G", "616110150011", "Vicks VapoRub Ointment 50g", "Pharmacy & Healthcare", "Vicks", "piece", "50g", 210.00, None, 165.00, "exempt", True, False, "/static/images/products/vicks_vaporub_50g.jpg", 80, 15, "Menthol, eucalyptus and camphor vapour ointment relieving nasal catarrh and coughs."),
    ("MED-FLUM-NSP-30ML", "616110150012", "Flumist Saline Nasal Spray 30ml", "Pharmacy & Healthcare", "Flumist", "piece", "30ml", 420.00, None, 330.00, "exempt", True, False, "/static/images/products/flumist_nasal_spray_30ml.jpg", 50, 10, "Isotonic sterile saline spray for gentle unblocking of congested nasal passages."),
    # Stomach & Antiseptics
    ("MED-ENO-FRUT-10S", "616110150020", "ENO Fruit Salt Regular Antacid 10 Sachets", "Pharmacy & Healthcare", "ENO", "piece", "Pack of 10", 250.00, None, 195.00, "exempt", True, False, "/static/images/products/eno_fruit_salt_10s.jpg", 100, 20, "Fast-acting effervescent antacid powder relieving acid indigestion and heartburn in 6 seconds."),
    ("MED-DETT-LIQ-250ML", "616110150030", "Dettol Antiseptic Disinfectant Liquid 250ml", "Pharmacy & Healthcare", "Dettol", "piece", "250ml", 360.00, None, 285.00, "exempt", True, False, "/static/images/products/dettol_liquid_250ml.jpg", 75, 15, "Concentrated antiseptic liquid for wound cleansing, personal hygiene and household disinfection."),
    ("MED-BETA-SOL-100ML", "616110150031", "Betadine 10% Povidone-Iodine Antiseptic 100ml", "Pharmacy & Healthcare", "Betadine", "piece", "100ml", 340.00, None, 270.00, "exempt", True, False, "/static/images/products/betadine_100ml.jpg", 60, 12, "Gold standard topical antiseptic solution for cuts, scrapes and minor burns."),
    ("MED-DHEA-RUB-100G", "616110150032", "Deep Heat Pain Relief Rub Cream 100g", "Pharmacy & Healthcare", "Deep Heat", "piece", "100g", 680.00, 740.00, 540.00, "exempt", True, False, "/static/images/products/deep_heat_100g.jpg", 45, 10, "Fast-acting warming cream generating penetrating warmth for aching muscles and joints."),
    ("MED-ELAS-PLAS-20S", "616110150040", "Elastoplast Fabric Breathable Adhesive Plasters 20s", "Pharmacy & Healthcare", "Elastoplast", "piece", "Pack of 20", 160.00, None, 125.00, "exempt", True, False, "/static/images/products/elastoplast_20s.jpg", 110, 25, "Extra flexible, durable fabric adhesive bandages with strong adhesion."),
]

# Sheet metadata dictionary
CATEGORIES_CATALOGUE = [
    ("Snacks & Confectionery", SNACKS_PRODUCTS, "4B5320"),       # Olive Green
    ("Bakery & Pastries", BAKERY_PRODUCTS, "D97706"),            # Amber / Gold
    ("Beverages & Soft Drinks", BEVERAGES_PRODUCTS, "0284C7"),   # Sky Blue
    ("Alcoholic Drinks & Spirits", ALCOHOL_PRODUCTS, "991B1B"),  # Burgundy Red
    ("Dairy & Eggs", DAIRY_PRODUCTS, "2563EB"),                 # Cobalt Blue
    ("Ice Cream & Frozen Desserts", ICECREAM_PRODUCTS, "DB2777"),# Pink / Magenta
    ("Grains, Flours & Staples", GRAINS_PRODUCTS, "B45309"),     # Warm Brown
    ("Oils, Spices & Condiments", OILS_SPICES_PRODUCTS, "CA8A04"),# Golden Mustard
    ("Meat, Poultry & Fresh Produce", PRODUCE_MEAT_PRODUCTS, "15803D"), # Forest Green
    ("Personal Care & Grooming", PERSONAL_CARE_PRODUCTS, "7C3AED"),     # Purple
    ("Household & Cleaning", HOUSEHOLD_PRODUCTS, "0D9488"),     # Teal
    ("Baby Care & Kids", BABY_PRODUCTS, "EC4899"),              # Rose Pink
    ("Electronics & Appliances", ELECTRONICS_PRODUCTS, "1E293B"),# Slate / Dark
    ("Furniture & Home Living", FURNITURE_PRODUCTS, "6D28D9"),  # Deep Violet
    ("Pharmacy & Healthcare", PHARMACY_PRODUCTS, "DC2626"),     # Medical Red
]

# ---------------------------------------------------------------------------
# STYLING DEFINITIONS
# ---------------------------------------------------------------------------

FONT_FAMILY = "Segoe UI"

FONT_HEADER = Font(name=FONT_FAMILY, size=11, bold=True, color="FFFFFF")
FILL_HEADER = PatternFill(start_color="0F2C59", end_color="0F2C59", fill_type="solid")  # Royal Navy

FONT_DATA = Font(name=FONT_FAMILY, size=10, color="1E293B")
FONT_DATA_BOLD = Font(name=FONT_FAMILY, size=10, bold=True, color="0F2C59")
FONT_DATA_MUTED = Font(name=FONT_FAMILY, size=9, italic=True, color="64748B")

BORDER_THIN = Border(
    left=Side(style="thin", color="E2E8F0"),
    right=Side(style="thin", color="E2E8F0"),
    top=Side(style="thin", color="E2E8F0"),
    bottom=Side(style="thin", color="E2E8F0"),
)

BORDER_HEADER = Border(
    left=Side(style="thin", color="1E3A8A"),
    right=Side(style="thin", color="1E3A8A"),
    top=Side(style="medium", color="0F2C59"),
    bottom=Side(style="medium", color="0F2C59"),
)

FILL_ZEBRA_ODD = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
FILL_ZEBRA_EVEN = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")


def format_table_headers(ws, headers):
    """Writes and styles table headers on row 1."""
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER
        cell.border = BORDER_HEADER
    ws.row_dimensions[1].height = 26


def append_product_row(ws, row_idx, product_tuple):
    """Writes a product tuple to the worksheet with appropriate cell types and formatting."""
    fill = FILL_ZEBRA_EVEN if row_idx % 2 == 0 else FILL_ZEBRA_ODD
    (
        sku, barcode, name, cat, brand, unit, pack_size,
        price, compare_at, cost, tax, is_active, is_age,
        img, qty, reorder, desc
    ) = product_tuple

    row_data = [
        (sku, ALIGN_LEFT, FONT_DATA_BOLD, None),
        (barcode, ALIGN_CENTER, FONT_DATA, "@"),
        (name, ALIGN_LEFT, FONT_DATA, None),
        (cat, ALIGN_LEFT, FONT_DATA, None),
        (brand, ALIGN_LEFT, FONT_DATA, None),
        (unit, ALIGN_CENTER, FONT_DATA, None),
        (pack_size, ALIGN_CENTER, FONT_DATA, None),
        (price, ALIGN_RIGHT, FONT_DATA, "#,##0.00"),
        (compare_at, ALIGN_RIGHT, FONT_DATA_MUTED, "#,##0.00"),
        (cost, ALIGN_RIGHT, FONT_DATA, "#,##0.00"),
        (tax, ALIGN_CENTER, FONT_DATA, None),
        ("true" if is_active else "false", ALIGN_CENTER, FONT_DATA, None),
        ("true" if is_age else "false", ALIGN_CENTER, FONT_DATA, None),
        (img, ALIGN_LEFT, FONT_DATA_MUTED, None),
        (qty, ALIGN_RIGHT, FONT_DATA, "#,##0"),
        (reorder, ALIGN_RIGHT, FONT_DATA, "#,##0"),
        (desc, ALIGN_LEFT, FONT_DATA, None),
    ]

    for col_idx, (val, alignment, font, num_fmt) in enumerate(row_data, 1):
        cell = ws.cell(row=row_idx, column=col_idx, value=val)
        cell.alignment = alignment
        cell.font = font
        cell.fill = fill
        cell.border = BORDER_THIN
        if num_fmt and val is not None:
            cell.number_format = num_fmt

    ws.row_dimensions[row_idx].height = 20


def auto_fit_columns(ws, min_width=12, max_width=45):
    """Adjusts column widths based on maximum string lengths."""
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        width = min(max(max_len + 3, min_width), max_width)
        ws.column_dimensions[col_letter].width = width


def create_overview_sheet(wb, total_products):
    """Creates the Readme & Data Dictionary cover sheet."""
    ws = wb.active
    ws.title = "Overview & Data Dictionary"
    ws.sheet_properties.tabColor = "0F2C59"

    # Title Banner
    ws.merge_cells("A1:G1")
    title_cell = ws["A1"]
    title_cell.value = "BansiGo Multi-Category Kenyan Retail Catalogue"
    title_cell.font = Font(name=FONT_FAMILY, size=16, bold=True, color="FFFFFF")
    title_cell.fill = FILL_HEADER
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 40

    # Subtitle
    ws.merge_cells("A2:G2")
    sub_cell = ws["A2"]
    sub_cell.value = f"Harmonized database workbook | 15 Categories | {total_products} Products & Variants | Bansi Mega Supermarket Standard"
    sub_cell.font = Font(name=FONT_FAMILY, size=10, italic=True, color="0F2C59")
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")
    sub_cell.fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    ws.row_dimensions[2].height = 24

    # Section 1: Field Mappings
    ws.cell(row=4, column=1, value="1. Database Schema Field Specifications").font = Font(name=FONT_FAMILY, size=12, bold=True, color="0F2C59")
    
    schema_headers = ["Field Name", "Database Model Target", "Data Type", "Constraints / Allowed Values", "Example", "Description"]
    for col_idx, h in enumerate(schema_headers, 1):
        c = ws.cell(row=5, column=col_idx, value=h)
        c.font = FONT_HEADER
        c.fill = FILL_HEADER
        c.alignment = ALIGN_CENTER
        c.border = BORDER_HEADER
    ws.row_dimensions[5].height = 24

    specs = [
        ("sku", "Product.sku", "VARCHAR(40)", "Mandatory, Unique Alphanumeric", "SNCK-STIX-CHIL-30G", "Unique stock keeping unit code"),
        ("barcode", "Product.barcode", "VARCHAR(14)", "Unique EAN-13, Kenya prefix 616", "616110010001", "Standard GTIN/EAN barcode for POS scanning"),
        ("name", "Product.name", "VARCHAR(150)", "Mandatory, Title string", "Stix Potato Crisps Chilli Lemon 30g", "Full commercial product display name"),
        ("category_name", "Category.name", "VARCHAR(100)", "Mandatory, Auto-provisioned if missing", "Snacks & Confectionery", "Hierarchy category under which product is organized"),
        ("brand_name", "Brand.name", "VARCHAR(100)", "Optional, Auto-provisioned if missing", "Stix", "Manufacturer or brand trade identity"),
        ("unit", "Product.unit", "VARCHAR(20)", "ENUM: 'piece', 'kg', 'litre'", "piece", "Unit of measure for price quotation"),
        ("pack_size_label", "Product.pack_size_label", "VARCHAR(40)", "Descriptive string", "30g", "Packaging size visible to customer"),
        ("price", "Product.price", "NUMERIC(12,2)", "Mandatory, >= 0.00, VAT-inclusive KES", "30.00", "Current retail selling price"),
        ("compare_at_price", "Product.compare_at_price", "NUMERIC(12,2)", "Optional, > price if specified", "35.00", "Original struck-through price for discounts"),
        ("cost_price", "Product.cost_price", "NUMERIC(12,2)", "Optional, >= 0.00 (Staff only)", "22.00", "Wholesale inventory purchase unit cost"),
        ("tax_class", "Product.tax_class", "VARCHAR(20)", "ENUM: 'standard', 'zero_rated', 'exempt'", "standard", "VAT status (standard 16%, zero_rated 0%, exempt)"),
        ("is_active", "Product.is_active", "BOOLEAN", "'true' or 'false'", "true", "Controls live visibility in storefront catalog"),
        ("is_age_restricted", "Product.is_age_restricted", "BOOLEAN", "'true' or 'false' (Alcohol/Tobacco)", "false", "Requires rider age verification upon delivery"),
        ("image_url", "Product.image_url", "VARCHAR(255)", "URL or static asset path", "/static/images/products/...", "Cover product picture"),
        ("quantity_on_hand", "Inventory.quantity_on_hand", "NUMERIC(12,3)", ">= 0.000 (Physical balance)", "120", "Stock available for dispatch in warehouse"),
        ("reorder_level", "Inventory.reorder_level", "NUMERIC(12,3)", ">= 0.000 (Replenishment threshold)", "20", "Low stock alert trigger level"),
        ("description", "Product.description", "TEXT", "Optional freeform text", "Crispy seasoned potato sticks...", "Detailed customer information and benefits"),
    ]

    for idx, row in enumerate(specs, 6):
        fill = FILL_ZEBRA_EVEN if idx % 2 == 0 else FILL_ZEBRA_ODD
        for c_idx, val in enumerate(row, 1):
            cell = ws.cell(row=idx, column=c_idx, value=val)
            cell.font = FONT_DATA
            cell.fill = fill
            cell.border = BORDER_THIN
            if c_idx in (1, 2, 4):
                cell.font = FONT_DATA_BOLD
        ws.row_dimensions[idx].height = 20

    # Section 2: Summary of Categories
    start_cat_row = len(specs) + 8
    ws.cell(row=start_cat_row, column=1, value="2. Included Product Category Worksheets").font = Font(name=FONT_FAMILY, size=12, bold=True, color="0F2C59")
    
    cat_headers = ["No.", "Worksheet Tab", "Category Domain", "Total SKUs", "Sample Leading Brands", "Primary Tax Treatment"]
    for col_idx, h in enumerate(cat_headers, 1):
        c = ws.cell(row=start_cat_row + 1, column=col_idx, value=h)
        c.font = FONT_HEADER
        c.fill = FILL_HEADER
        c.alignment = ALIGN_CENTER
        c.border = BORDER_HEADER
    ws.row_dimensions[start_cat_row + 1].height = 24

    for cat_idx, (cat_name, products, color) in enumerate(CATEGORIES_CATALOGUE, 1):
        r_idx = start_cat_row + 1 + cat_idx
        fill = FILL_ZEBRA_EVEN if cat_idx % 2 == 0 else FILL_ZEBRA_ODD
        brands = list(dict.fromkeys(p[4] for p in products))[:4]
        primary_tax = "standard (16%)"
        if any(p[10] == "zero_rated" for p in products):
            primary_tax = "zero_rated / mixed"
        if any(p[10] == "exempt" for p in products):
            primary_tax = "exempt / mixed"

        cat_row_data = [
            cat_idx,
            cat_name[:31],
            cat_name,
            len(products),
            ", ".join(brands),
            primary_tax
        ]
        for c_idx, val in enumerate(cat_row_data, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = FONT_DATA
            cell.fill = fill
            cell.border = BORDER_THIN
            if c_idx in (1, 4):
                cell.alignment = ALIGN_CENTER
            if c_idx == 4:
                cell.font = FONT_DATA_BOLD

        ws.row_dimensions[r_idx].height = 20

    auto_fit_columns(ws, min_width=10, max_width=50)


def generate_workbook():
    """Builds and saves the complete multi-sheet Kenyan retail catalog."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    wb = Workbook()

    total_products = sum(len(prods) for _, prods, _ in CATEGORIES_CATALOGUE)

    # 1. Overview sheet
    create_overview_sheet(wb, total_products)

    # 2. Master Consolidated sheet
    ws_all = wb.create_sheet(title="All Products (Consolidated)")
    ws_all.sheet_properties.tabColor = "0F2C59"
    format_table_headers(ws_all, HEADERS)

    all_row_idx = 2
    for _, prods, _ in CATEGORIES_CATALOGUE:
        for p in prods:
            append_product_row(ws_all, all_row_idx, p)
            all_row_idx += 1
    auto_fit_columns(ws_all)

    # 3. Individual category worksheets
    for cat_name, prods, tab_color in CATEGORIES_CATALOGUE:
        # Excel sheet titles max 31 chars
        sheet_title = cat_name[:31]
        ws_cat = wb.create_sheet(title=sheet_title)
        ws_cat.sheet_properties.tabColor = tab_color
        format_table_headers(ws_cat, HEADERS)

        for row_idx, p in enumerate(prods, 2):
            append_product_row(ws_cat, row_idx, p)

        auto_fit_columns(ws_cat)

    # Save to data/catalogue/
    wb.save(OUTPUT_PATH)
    # Also save a convenient root copy
    wb.save(ROOT_COPY_PATH)
    print(f"Workbook successfully generated at: {OUTPUT_PATH}")
    print(f"Root copy saved at: {ROOT_COPY_PATH}")
    print(f"Total Categories: {len(CATEGORIES_CATALOGUE)}")
    print(f"Total Products & Variants: {total_products}")


if __name__ == "__main__":
    generate_workbook()
