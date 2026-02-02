#!/usr/bin/env python3
"""
Second pass to verify/correct US RRP estimates using Gemini.
"""

import json
import os
import re
import time
from pathlib import Path

from google import genai

SCRIPT_DIR = Path(__file__).parent
EXPORTS_DIR = SCRIPT_DIR / "exports"

LLM_DELAY = 0.5
BATCH_SIZE = 10  # Larger batches for efficiency


def load_data(filepath=None):
    """Load export data."""
    if filepath is None:
        filepath = EXPORTS_DIR / "ivory_products_latest.json"
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def init_gemini():
    """Initialize Gemini client."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


def verify_us_prices(client, products, category_name):
    """Re-verify US RRP for a batch of products."""

    product_list = "\n".join([
        f"{i+1}. {p.get('manufacturer', '?')} - {p.get('description_en', p['name'])} (Part: {p.get('part_number', 'N/A')})"
        for i, p in enumerate(products)
    ])

    prompt = f"""You are a computer hardware pricing expert. For each {category_name} product below, provide the CURRENT US retail price (MSRP/RRP) in USD.

Products:
{product_list}

IMPORTANT GUIDELINES:
- Use current 2024-2025 US retail prices from major retailers (Amazon, Newegg, Best Buy)
- For DDR5 RAM: 16GB kits typically $50-80, 32GB kits $80-150, 64GB kits $150-300
- For DDR4 RAM: 16GB kits typically $30-50, 32GB kits $50-90
- For NVMe SSDs: 500GB $40-60, 1TB $60-100, 2TB $100-180
- If exact product not available in US, estimate based on similar specs
- Return INTEGER prices only

Return a JSON array with objects containing:
- "index": product number (1, 2, 3...)
- "us_rrp_usd": integer US retail price in USD

Example: [{{"index": 1, "us_rrp_usd": 85}}, {{"index": 2, "us_rrp_usd": 120}}]

Return ONLY the JSON array, no markdown.
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        text = response.text.strip()

        # Clean markdown if present
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\n?', '', text)
            text = re.sub(r'\n?```$', '', text)

        results = json.loads(text)
        return {r["index"]: r["us_rrp_usd"] for r in results}

    except Exception as e:
        print(f"    Error: {e}")
        return {}


def recalculate_ratios(products, exchange_rate):
    """Recalculate price ratios after updating US RRP."""
    for p in products:
        price_ils = p.get("price")
        us_rrp = p.get("us_rrp_usd")

        if price_ils and us_rrp and us_rrp > 0:
            price_usd = price_ils * exchange_rate
            p["price_usd"] = round(price_usd, 2)
            p["price_ratio"] = round(price_usd / us_rrp, 2)
        else:
            p["price_usd"] = round(price_ils * exchange_rate, 2) if price_ils else None
            p["price_ratio"] = None

    return products


def main():
    print("=" * 60)
    print("US Price Verification (Second Pass)")
    print("=" * 60)

    # Load data
    data = load_data()
    exchange_rate = data["exchange_rate_ils_to_usd"]
    print(f"\nLoaded {data['total_products']} products")
    print(f"Exchange rate: {exchange_rate}")

    # Init Gemini
    client = init_gemini()
    print("Gemini initialized")

    # Process each category
    for group_name, group_cats in data["categories"].items():
        for cat_key, cat_data in group_cats.items():
            products = cat_data["products"]
            cat_name = cat_data["description"]

            print(f"\n{cat_name}: {len(products)} products")

            # Process in batches
            for i in range(0, len(products), BATCH_SIZE):
                batch = products[i:i + BATCH_SIZE]
                batch_num = i // BATCH_SIZE + 1
                total_batches = (len(products) + BATCH_SIZE - 1) // BATCH_SIZE

                print(f"  Batch {batch_num}/{total_batches}...", end=" ")

                updated_prices = verify_us_prices(client, batch, cat_name)

                # Apply updates
                updates = 0
                for j, p in enumerate(batch):
                    idx = j + 1
                    if idx in updated_prices:
                        old_price = p.get("us_rrp_usd")
                        new_price = updated_prices[idx]
                        if old_price != new_price:
                            p["us_rrp_usd"] = new_price
                            updates += 1

                print(f"{updates} prices updated")

                if i + BATCH_SIZE < len(products):
                    time.sleep(LLM_DELAY)

            # Recalculate ratios for this category
            cat_data["products"] = recalculate_ratios(products, exchange_rate)

    # Save updated data
    output_path = EXPORTS_DIR / "ivory_products_verified.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Saved verified data to: {output_path}")

    # Also update latest
    latest_path = EXPORTS_DIR / "ivory_products_latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Updated: {latest_path}")

    print("=" * 60)


if __name__ == "__main__":
    main()
