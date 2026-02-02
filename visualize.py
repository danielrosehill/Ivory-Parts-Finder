#!/usr/bin/env python3
"""
Generate price ratio visualizations from Ivory scraper data.
"""

import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns

SCRIPT_DIR = Path(__file__).parent
EXPORTS_DIR = SCRIPT_DIR / "exports"
CHARTS_DIR = SCRIPT_DIR / "charts"


def load_data(filepath=None):
    """Load the latest export data."""
    if filepath is None:
        filepath = EXPORTS_DIR / "ivory_products_latest.json"

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_ratios(data):
    """Extract price ratios by category."""
    category_ratios = {}

    for group_name, group_cats in data["categories"].items():
        for cat_key, cat_data in group_cats.items():
            desc = cat_data["description"]
            ratios = [p["price_ratio"] for p in cat_data["products"] if p.get("price_ratio")]
            if ratios:
                category_ratios[desc] = ratios

    return category_ratios


def create_bar_chart(category_ratios, output_path):
    """Create a horizontal bar chart of average price ratios."""
    # Calculate averages and sort
    avg_ratios = {cat: sum(r)/len(r) for cat, r in category_ratios.items()}
    sorted_cats = sorted(avg_ratios.keys(), key=lambda x: avg_ratios[x])

    fig, ax = plt.subplots(figsize=(10, 8))

    colors = ['#2ecc71' if avg_ratios[cat] < 1.5 else '#f39c12' if avg_ratios[cat] < 2.5 else '#e74c3c'
              for cat in sorted_cats]

    bars = ax.barh(sorted_cats, [avg_ratios[cat] for cat in sorted_cats], color=colors)

    # Add value labels
    for bar, cat in zip(bars, sorted_cats):
        width = bar.get_width()
        ax.text(width + 0.05, bar.get_y() + bar.get_height()/2,
                f'{width:.2f}x', va='center', fontsize=9)

    ax.axvline(x=1.0, color='#3498db', linestyle='--', linewidth=2, label='PARITY (1.0x)')
    ax.set_xlabel('Price Ratio (Israeli Price / US RRP)', fontsize=11)
    ax.set_title('Israeli vs US Prices by Category\n(Ivory.co.il)', fontsize=14, fontweight='bold')
    ax.legend(loc='lower right')
    ax.set_xlim(0, max(avg_ratios.values()) + 0.5)

    # Add color legend
    ax.text(0.02, 0.98, '● <1.5x  ● 1.5-2.5x  ● >2.5x',
            transform=ax.transAxes, fontsize=9, va='top',
            color='gray')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


def create_box_plot(category_ratios, output_path):
    """Create a box plot showing distribution of ratios."""
    # Sort by median
    medians = {cat: sorted(ratios)[len(ratios)//2] for cat, ratios in category_ratios.items()}
    sorted_cats = sorted(medians.keys(), key=lambda x: medians[x])

    fig, ax = plt.subplots(figsize=(12, 8))

    data_to_plot = [category_ratios[cat] for cat in sorted_cats]

    bp = ax.boxplot(data_to_plot, vert=False, patch_artist=True)

    # Color boxes
    for patch, cat in zip(bp['boxes'], sorted_cats):
        med = medians[cat]
        if med < 1.5:
            patch.set_facecolor('#2ecc71')
        elif med < 2.5:
            patch.set_facecolor('#f39c12')
        else:
            patch.set_facecolor('#e74c3c')
        patch.set_alpha(0.7)

    ax.set_yticklabels(sorted_cats)
    ax.axvline(x=1.0, color='#3498db', linestyle='--', linewidth=2, label='PARITY (1.0x)')
    ax.set_xlabel('Price Ratio (Israeli Price / US RRP)', fontsize=11)
    ax.set_title('Price Ratio Distribution by Category\n(Ivory.co.il)', fontsize=14, fontweight='bold')
    ax.legend(loc='lower right')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


def create_summary_chart(category_ratios, data, output_path):
    """Create a summary infographic."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Left: Bar chart
    avg_ratios = {cat: sum(r)/len(r) for cat, r in category_ratios.items()}
    sorted_cats = sorted(avg_ratios.keys(), key=lambda x: avg_ratios[x])

    colors = ['#2ecc71' if avg_ratios[cat] < 1.5 else '#f39c12' if avg_ratios[cat] < 2.5 else '#e74c3c'
              for cat in sorted_cats]

    axes[0].barh(sorted_cats, [avg_ratios[cat] for cat in sorted_cats], color=colors)
    axes[0].axvline(x=1.0, color='#3498db', linestyle='--', linewidth=2)
    axes[0].set_xlabel('Avg Price Ratio')
    axes[0].set_title('Average by Category', fontsize=12, fontweight='bold')
    axes[0].set_xlim(0, max(avg_ratios.values()) + 0.5)

    # Right: Overall stats
    all_ratios = [r for ratios in category_ratios.values() for r in ratios]

    axes[1].hist(all_ratios, bins=30, color='#3498db', alpha=0.7, edgecolor='white')
    axes[1].axvline(x=1.0, color='#e74c3c', linestyle='--', linewidth=2, label='PARITY')
    axes[1].axvline(x=sum(all_ratios)/len(all_ratios), color='#2ecc71', linestyle='-', linewidth=2, label=f'Avg: {sum(all_ratios)/len(all_ratios):.2f}x')
    axes[1].set_xlabel('Price Ratio')
    axes[1].set_ylabel('Number of Products')
    axes[1].set_title('Distribution of All Products', fontsize=12, fontweight='bold')
    axes[1].legend()

    # Main title
    fig.suptitle(f'Israeli Computer Parts Pricing Analysis\n{data["total_products"]} products from Ivory.co.il | {data["capture_date"][:10]}',
                 fontsize=14, fontweight='bold', y=1.02)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


def main():
    # Create output directory
    CHARTS_DIR.mkdir(exist_ok=True)

    # Load data
    print("Loading data...")
    data = load_data()
    print(f"Loaded {data['total_products']} products from {data['capture_date']}")

    # Extract ratios
    category_ratios = extract_ratios(data)
    total_with_ratios = sum(len(r) for r in category_ratios.values())
    print(f"Found {total_with_ratios} products with price ratios across {len(category_ratios)} categories")

    # Generate charts
    print("\nGenerating visualizations...")
    create_bar_chart(category_ratios, CHARTS_DIR / "price_ratio_by_category.png")
    create_box_plot(category_ratios, CHARTS_DIR / "price_ratio_distribution.png")
    create_summary_chart(category_ratios, data, CHARTS_DIR / "price_analysis_summary.png")

    print("\nDone!")


if __name__ == "__main__":
    main()
