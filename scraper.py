#!/usr/bin/env python3
"""
Ivory Parts Scraper

Scrapes product data from ivory.co.il and exports to JSON format.
Enriches data with LLM (Gemini) for manufacturer, product number, and US RRP.
Must be run from within Israel due to geo-restrictions.
"""

import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup

# Optional: Gemini for enrichment (try new SDK first, fall back to old)
GEMINI_AVAILABLE = False
GEMINI_NEW_SDK = False

try:
    from google import genai
    GEMINI_AVAILABLE = True
    GEMINI_NEW_SDK = True
except ImportError:
    try:
        import google.generativeai as genai_old
        GEMINI_AVAILABLE = True
    except ImportError:
        pass

BASE_URL = "https://www.ivory.co.il/"
SCRIPT_DIR = Path(__file__).parent
CATEGORIES_FILE = SCRIPT_DIR / "categories.json"

# Request settings
REQUEST_DELAY = 1.0  # seconds between requests
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# LLM settings
LLM_DELAY = 0.5  # seconds between LLM calls to avoid rate limiting
LLM_BATCH_SIZE = 5  # Number of products to process in one LLM call


def load_categories():
    """Load categories from categories.json file."""
    with open(CATEGORIES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["categories"]


def get_category_map():
    """Build a flat map of category keys to (description, link) for easy lookup."""
    categories = load_categories()
    cat_map = {}

    for cat_group in categories:
        group_name = cat_group["category"]
        for item in cat_group["items"]:
            # Create a key from the description (lowercase, spaces to dashes)
            key = item["description"].lower().replace(" ", "-").replace("(", "").replace(")", "")
            cat_map[key] = {
                "description": item["description"],
                "link": item["link"],
                "group": group_name,
            }

    return cat_map


def get_session():
    """Create a requests session with appropriate headers."""
    session = requests.Session()
    # Keep headers minimal - brotli encoding causes issues with response decoding
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    return session


def fetch_page(session, url):
    """Fetch a page and return BeautifulSoup object."""
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return BeautifulSoup(response.content, "lxml")
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None


def get_exchange_rate():
    """Fetch current NIS to USD exchange rate."""
    print("\nFetching NIS/USD exchange rate...")

    # Try multiple sources for reliability
    apis = [
        ("https://api.exchangerate-api.com/v4/latest/ILS", lambda d: d["rates"]["USD"]),
        ("https://open.er-api.com/v6/latest/ILS", lambda d: d["rates"]["USD"]),
    ]

    for url, extractor in apis:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            rate = extractor(data)
            rate = round(rate, 4)
            print(f"Exchange rate: 1 ILS = {rate} USD")
            return rate
        except Exception as e:
            print(f"Failed to fetch from {url}: {e}")
            continue

    # Fallback to approximate rate if APIs fail
    print("WARNING: Using fallback exchange rate (0.27)")
    return 0.27


def init_gemini():
    """Initialize Gemini API client."""
    if not GEMINI_AVAILABLE:
        print("WARNING: google-genai not installed. Run: pip install google-genai")
        return None

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("WARNING: GEMINI_API_KEY environment variable not set. Skipping LLM enrichment.")
        return None

    try:
        if GEMINI_NEW_SDK:
            # New SDK (google-genai)
            client = genai.Client(api_key=api_key)
            print("Gemini API initialized successfully (new SDK)")
            return ("new", client)
        else:
            # Old SDK (google-generativeai)
            genai_old.configure(api_key=api_key)
            model = genai_old.GenerativeModel("gemini-1.5-flash")
            print("Gemini API initialized successfully (legacy SDK)")
            return ("old", model)
    except Exception as e:
        print(f"WARNING: Failed to initialize Gemini: {e}")
        return None


def enrich_products_with_llm(gemini_client, products, category_hint):
    """Use Gemini to enrich product data with manufacturer, PN, description, and US RRP."""
    if not gemini_client or not products:
        return products

    sdk_type, client = gemini_client

    # Build prompt for batch processing
    product_list = "\n".join([
        f"{i+1}. {p['name']}"
        for i, p in enumerate(products)
    ])

    prompt = f"""Analyze these {category_hint} products from an Israeli retailer and extract information.

Products:
{product_list}

For EACH product, provide a JSON array with objects containing:
- "index": the product number (1, 2, 3...)
- "manufacturer": the brand/manufacturer name (e.g., "Samsung", "Kingston", "ASUS")
- "part_number": the product SKU/model number if identifiable (e.g., "MZ-V9P2T0BW", "SA400S37/960G")
- "description_en": a brief English description of the product
- "us_rrp_usd": estimated US retail price in USD (integer, your best estimate based on current market prices). If unknown, use null.

IMPORTANT:
- Return ONLY valid JSON array, no markdown formatting
- Use null for unknown values
- For US RRP, estimate based on typical US retail prices for this exact product or very similar products

Example response format:
[{{"index": 1, "manufacturer": "Samsung", "part_number": "990-PRO-2TB", "description_en": "Samsung 990 Pro 2TB NVMe SSD", "us_rrp_usd": 180}}]
"""

    try:
        # Call appropriate SDK
        if sdk_type == "new":
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
            text = response.text.strip()
        else:
            response = client.generate_content(prompt)
            text = response.text.strip()

        # Clean up response - remove markdown code blocks if present
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\n?', '', text)
            text = re.sub(r'\n?```$', '', text)

        enrichments = json.loads(text)

        # Apply enrichments to products
        enrichment_map = {e["index"]: e for e in enrichments}

        for i, product in enumerate(products):
            idx = i + 1
            if idx in enrichment_map:
                e = enrichment_map[idx]
                product["manufacturer"] = e.get("manufacturer")
                product["part_number"] = e.get("part_number")
                product["description_en"] = e.get("description_en")
                product["us_rrp_usd"] = e.get("us_rrp_usd")

        return products

    except json.JSONDecodeError as e:
        print(f"  Warning: Failed to parse LLM response as JSON: {e}")
        return products
    except Exception as e:
        print(f"  Warning: LLM enrichment failed: {e}")
        return products


def calculate_price_ratios(products, exchange_rate):
    """Calculate price ratio (Israeli price as fraction of US RRP)."""
    for product in products:
        price_ils = product.get("price")
        us_rrp = product.get("us_rrp_usd")

        if price_ils and us_rrp and us_rrp > 0:
            # Convert ILS to USD
            price_usd = price_ils * exchange_rate
            # Calculate ratio (Israeli price / US RRP)
            ratio = round(price_usd / us_rrp, 2)
            product["price_usd"] = round(price_usd, 2)
            product["price_ratio"] = ratio
        else:
            product["price_usd"] = round(price_ils * exchange_rate, 2) if price_ils else None
            product["price_ratio"] = None

    return products


def extract_product_data(product_element):
    """Extract product data from a single product element."""
    try:
        # Get product anchor with ID and URL
        anchor = product_element.select_one("a[data-product-id]")
        if not anchor:
            return None

        product_id = anchor.get("data-product-id", "")
        product_url = anchor.get("href", "")
        if product_url and not product_url.startswith("http"):
            product_url = urljoin(BASE_URL, product_url)

        # Get product name - try multiple selectors
        name = ""
        for selector in [".title_product_catalog", ".main-text-area", "div[class*='title']"]:
            name_elem = product_element.select_one(selector)
            if name_elem:
                name = name_elem.get_text(strip=True)
                if name:
                    break

        # If still no name, try getting text from the anchor itself
        if not name:
            # Look for any div with product title text
            for div in product_element.select("div"):
                text = div.get_text(strip=True)
                # Product names are typically longer and in Hebrew
                if len(text) > 10 and not text.startswith("₪") and "מחיר" not in text:
                    name = text
                    break

        # Get regular price (NOT Eilat price)
        price = None

        # First, try to find price in span.price that is NOT inside an eilatprice container
        all_prices = product_element.select("span.price")
        for price_elem in all_prices:
            # Check if this price element or its parents have 'eilatprice' class
            is_eilat = False
            for parent in [price_elem] + list(price_elem.parents):
                if parent.get("class") and "eilatprice" in parent.get("class", []):
                    is_eilat = True
                    break

            if not is_eilat:
                price_text = price_elem.get_text(strip=True)
                price_text = price_text.replace(",", "").replace("₪", "").strip()
                try:
                    price = int(price_text)
                    break
                except ValueError:
                    continue

        # Check stock status
        in_stock = bool(product_element.select_one(".in-stock, .available-n-branch-tag.in-stock"))

        if not product_id:
            return None

        return {
            "id": product_id,
            "name": name,
            "price": price,
            "currency": "ILS",
            "url": product_url,
            "in_stock": in_stock,
        }
    except Exception as e:
        print(f"Error extracting product data: {e}")
        return None


def get_pagination_info(soup):
    """Extract pagination information from the page."""
    # Look for pagination links with page numbers
    page_links = soup.select("a[href*='page=']")

    max_page = 1
    for link in page_links:
        href = link.get("href", "")
        match = re.search(r'page=(\d+)', href)
        if match:
            page_num = int(match.group(1))
            max_page = max(max_page, page_num)

    # Also look for text-based pagination (page numbers as link text)
    for link in soup.select(".pagination a, .paging a, .pages a"):
        text = link.get_text(strip=True)
        if text.isdigit():
            max_page = max(max_page, int(text))

    return max_page


def build_page_url(base_url, page_num):
    """Build URL for a specific page number."""
    parsed = urlparse(base_url)
    query_params = parse_qs(parsed.query)
    query_params['page'] = [str(page_num)]
    new_query = urlencode(query_params, doseq=True)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}"


def scrape_category(session, cat_key, cat_info, gemini_model=None, exchange_rate=None):
    """Scrape all products from a category, handling pagination."""
    description = cat_info["description"]
    full_url = cat_info["link"]
    group = cat_info["group"]

    print(f"\nScraping: {description} ({group})")
    print(f"URL: {full_url}")

    all_products = []
    seen_ids = set()

    # Fetch first page
    soup = fetch_page(session, full_url)
    if not soup:
        return {
            "description": description,
            "group": group,
            "url": full_url,
            "product_count": 0,
            "products": [],
            "error": "Failed to fetch page",
        }

    # Check for pagination
    max_page = get_pagination_info(soup)
    print(f"Found {max_page} page(s)")

    # Process all pages
    for page_num in range(1, max_page + 1):
        if page_num > 1:
            time.sleep(REQUEST_DELAY)
            page_url = build_page_url(full_url, page_num)
            soup = fetch_page(session, page_url)
            if not soup:
                print(f"Page {page_num}: Failed to fetch")
                continue

        # Find product elements
        products = soup.select(".entry-wrapper")
        page_new = 0

        for product_elem in products:
            product_data = extract_product_data(product_elem)
            if product_data and product_data["id"] not in seen_ids:
                all_products.append(product_data)
                seen_ids.add(product_data["id"])
                page_new += 1

        print(f"Page {page_num}: {len(products)} items, {page_new} new products extracted")

    print(f"Total: {len(all_products)} unique products")

    # Enrich with LLM in batches
    if gemini_model and all_products:
        print(f"Enriching {len(all_products)} products with Gemini...")
        enriched_products = []

        for i in range(0, len(all_products), LLM_BATCH_SIZE):
            batch = all_products[i:i + LLM_BATCH_SIZE]
            print(f"  Processing batch {i//LLM_BATCH_SIZE + 1}/{(len(all_products) + LLM_BATCH_SIZE - 1)//LLM_BATCH_SIZE}...")

            batch = enrich_products_with_llm(gemini_model, batch, description)
            enriched_products.extend(batch)

            if i + LLM_BATCH_SIZE < len(all_products):
                time.sleep(LLM_DELAY)

        all_products = enriched_products

    # Calculate price ratios
    if exchange_rate:
        all_products = calculate_price_ratios(all_products, exchange_rate)

    return {
        "description": description,
        "group": group,
        "url": full_url,
        "product_count": len(all_products),
        "products": all_products,
    }


def scrape_all(session, categories_to_scrape=None, gemini_model=None, exchange_rate=None):
    """Scrape all (or specified) categories."""
    cat_map = get_category_map()

    if categories_to_scrape is None:
        categories_to_scrape = list(cat_map.keys())

    results = {}

    for cat_key in categories_to_scrape:
        if cat_key not in cat_map:
            print(f"Unknown category: {cat_key}")
            print(f"Available: {', '.join(sorted(cat_map.keys()))}")
            continue

        results[cat_key] = scrape_category(
            session, cat_key, cat_map[cat_key],
            gemini_model=gemini_model,
            exchange_rate=exchange_rate
        )
        time.sleep(REQUEST_DELAY)

    return results


def save_results(results, output_dir="exports", prefix="ivory_products", exchange_rate=None):
    """Save results to JSON file with timestamp."""
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now()
    timestamp_str = timestamp.strftime("%Y-%m-%dT%H-%M-%S")

    # Build hierarchical output grouped by category
    grouped = {}
    for cat_key, cat_data in results.items():
        group = cat_data.get("group", "Other")
        if group not in grouped:
            grouped[group] = {}
        grouped[group][cat_key] = cat_data

    output = {
        "capture_date": timestamp.isoformat(),
        "source": "ivory.co.il",
        "exchange_rate_ils_to_usd": exchange_rate,
        "total_products": sum(c["product_count"] for c in results.values()),
        "categories": grouped,
    }

    filename = f"{prefix}_{timestamp_str}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved results to: {filepath}")

    # Also save a "latest" copy for easy access
    latest_path = os.path.join(output_dir, f"{prefix}_latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return filepath


def validate_json(filepath):
    """Validate the generated JSON file."""
    print(f"\nValidating JSON: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Check required fields
    assert "capture_date" in data, "Missing capture_date"
    assert "source" in data, "Missing source"
    assert "categories" in data, "Missing categories"

    total_products = 0
    enriched_count = 0
    ratio_count = 0

    for group_name, group_cats in data["categories"].items():
        print(f"\n{group_name}:")
        for cat_key, cat_data in group_cats.items():
            assert "description" in cat_data, f"Category {cat_key} missing description"
            assert "url" in cat_data, f"Category {cat_key} missing url"
            assert "products" in cat_data, f"Category {cat_key} missing products"

            for product in cat_data["products"]:
                assert "id" in product, f"Product missing id in {cat_key}"
                assert "name" in product, f"Product missing name in {cat_key}"
                assert "url" in product, f"Product missing url in {cat_key}"

                if product.get("manufacturer"):
                    enriched_count += 1
                if product.get("price_ratio") is not None:
                    ratio_count += 1

            total_products += len(cat_data["products"])
            print(f"  {cat_data['description']}: {len(cat_data['products'])} products")

    print(f"\nTotal products: {total_products}")
    print(f"Products with LLM enrichment: {enriched_count}")
    print(f"Products with price ratio: {ratio_count}")
    print("JSON validation passed!")
    return True


def main():
    parser = argparse.ArgumentParser(description="Scrape Ivory product data to JSON")
    parser.add_argument(
        "--category", "-c",
        help="Specific category to scrape. Can be repeated.",
        action="append",
        dest="categories"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="exports",
        help="Output directory for JSON files (default: exports)"
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List available categories and exit"
    )
    parser.add_argument(
        "--validate-only",
        help="Validate an existing JSON file instead of scraping"
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip LLM enrichment (faster, but no manufacturer/PN/US RRP)"
    )

    args = parser.parse_args()

    cat_map = get_category_map()

    if args.list_categories:
        print("Available categories:\n")
        categories = load_categories()
        for cat_group in categories:
            print(f"{cat_group['category']}:")
            for item in cat_group["items"]:
                key = item["description"].lower().replace(" ", "-").replace("(", "").replace(")", "")
                print(f"  {key:25} - {item['description']}")
            print()
        return

    if args.validate_only:
        validate_json(args.validate_only)
        return

    print("=" * 60)
    print("Ivory Parts Scraper")
    print(f"Started at: {datetime.now().isoformat()}")
    print(f"Categories file: {CATEGORIES_FILE}")
    print("=" * 60)

    session = get_session()

    # Test connection
    print("\nTesting connection to ivory.co.il...")
    test_soup = fetch_page(session, BASE_URL)
    if not test_soup:
        print("ERROR: Cannot connect to ivory.co.il")
        print("This script must be run from within Israel.")
        return
    print("Connection successful!")

    # Get exchange rate
    exchange_rate = get_exchange_rate()

    # Initialize Gemini if not skipped
    gemini_model = None
    if not args.no_enrich:
        gemini_model = init_gemini()

    # Scrape
    results = scrape_all(
        session,
        args.categories,
        gemini_model=gemini_model,
        exchange_rate=exchange_rate
    )

    # Determine output prefix
    if args.categories and len(args.categories) == 1:
        prefix = args.categories[0]
    else:
        prefix = "ivory_products"

    # Save and validate
    filepath = save_results(results, args.output_dir, prefix, exchange_rate=exchange_rate)
    validate_json(filepath)

    print("\n" + "=" * 60)
    print("Scraping complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
