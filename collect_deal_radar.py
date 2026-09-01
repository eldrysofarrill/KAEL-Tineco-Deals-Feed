import json
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from collect_deals import get_token, SEARCH_URL, MARKETPLACE

QUERIES = [
    ("ELECTRONICS", "Samsung Galaxy unlocked refurbished"),
    ("ELECTRONICS", "Apple iPad refurbished"),
    ("TOOLS", "DEWALT 20V tool new"),
    ("GAMING", "Nintendo Switch refurbished"),
    ("HOME", "KitchenAid mixer refurbished"),
    ("HOME", "Ninja air fryer new"),
    ("VACUUMS", "Tineco refurbished"),
]

MAX_PER_QUERY = 30
MAX_OUTPUT = 70
SCORING_VERSION = "2.0"


def money_value(obj):
    if not obj:
        return 0.0
    try:
        return float(obj.get("value") or 0)
    except Exception:
        return 0.0


def fetch_query(token, query):
    params = {
        "q": query,
        "limit": str(MAX_PER_QUERY),
        "filter": "buyingOptions:{FIXED_PRICE}",
    }
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("itemSummaries", [])


def normalize_discount(price, original, api_discount):
    try:
        api_discount = float(api_discount or 0)
    except Exception:
        api_discount = 0.0
    if api_discount > 0:
        return round(api_discount, 1)
    if original > price > 0:
        return round((original - price) * 100.0 / original, 1)
    return 0.0


def shipping_cost(item):
    shipping = item.get("shippingOptions") or []
    if not shipping:
        return 0.0
    return money_value((shipping[0] or {}).get("shippingCost"))


def condition_points(condition):
    c = (condition or "").lower()
    if "new" in c or "certified refurbished" in c:
        return 10
    if "excellent" in c or "very good" in c or "refurbished" in c:
        return 8
    if "good" in c:
        return 6
    if "used" in c:
        return 3
    return 5


def seller_points(feedback):
    if feedback >= 99.5:
        return 20
    if feedback >= 99:
        return 18
    if feedback >= 98:
        return 15
    if feedback >= 97:
        return 11
    if feedback >= 95:
        return 6
    return 0


def shipping_points(cost):
    if cost <= 0:
        return 10
    if cost <= 10:
        return 7
    if cost <= 20:
        return 4
    return 0


def market_points(savings_pct):
    if savings_pct >= 35:
        return 55
    if savings_pct >= 25:
        return 48
    if savings_pct >= 18:
        return 40
    if savings_pct >= 12:
        return 32
    if savings_pct >= 7:
        return 20
    if savings_pct >= 3:
        return 10
    return 0


def trimmed_median(values):
    values = sorted(v for v in values if v > 0)
    if not values:
        return 0.0
    if len(values) >= 10:
        trim = max(1, len(values) // 10)
        values = values[trim:-trim] or values
    return round(float(statistics.median(values)), 2)


def market_savings(landed, market_median):
    if landed <= 0 or market_median <= 0 or landed >= market_median:
        return 0.0
    return round((market_median - landed) * 100.0 / market_median, 1)


def confidence_for(count):
    if count >= 10:
        return "HIGH"
    if count >= 5:
        return "MEDIUM"
    return "LOW"


def classify(deal, comparable_count, market_median):
    landed = round(deal["currentPrice"] + deal["shippingCost"], 2)
    savings = market_savings(landed, market_median)
    market_component = market_points(savings)
    seller_component = seller_points(deal["sellerRating"])
    shipping_component = shipping_points(deal["shippingCost"])
    condition_component = condition_points(deal["condition"])

    promo_component = 0
    # Marketing/list-price discount is only a small bonus and NEVER decides the label by itself.
    if savings >= 5 and deal["discountPercent"] >= 20:
        promo_component = min(5, int(deal["discountPercent"] // 15) + 1)

    score = min(100, market_component + seller_component + shipping_component + condition_component + promo_component)
    confidence = confidence_for(comparable_count)

    # Strong Buy requires a real market-price advantage, a trustworthy seller, and enough comparables.
    if score >= 78 and savings >= 20 and deal["sellerRating"] >= 97 and comparable_count >= 5:
        level = "STRONG BUY"
    elif score >= 58 and savings >= 10 and deal["sellerRating"] >= 95 and comparable_count >= 4:
        level = "GOOD DEAL"
    else:
        level = "NORMAL"

    reasons = []
    if savings > 0:
        reasons.append(f"{savings:.0f}% below comparable median")
    else:
        reasons.append("Not below comparable median")
    if deal["sellerRating"] > 0:
        reasons.append(f"Seller {deal['sellerRating']:.1f}% positive")
    reasons.append("Free shipping" if deal["shippingCost"] <= 0 else f"Shipping ${deal['shippingCost']:.2f}")
    reasons.append(f"{comparable_count} comparable listings")

    return {
        "dealScore": score,
        "dealLevel": level,
        "landedPrice": landed,
        "marketMedianPrice": market_median,
        "marketSavingsPercent": savings,
        "comparableCount": comparable_count,
        "dealConfidence": confidence,
        "scoreReasons": reasons[:4],
        "scoreBreakdown": {
            "market": market_component,
            "seller": seller_component,
            "shipping": shipping_component,
            "condition": condition_component,
            "promo": promo_component,
        },
    }


def simplify_base(item, category, query):
    title = (item.get("title") or "").strip()
    price = money_value(item.get("price"))
    marketing = item.get("marketingPrice") or {}
    original = money_value(marketing.get("originalPrice"))
    discount = normalize_discount(price, original, marketing.get("discountPercentage"))
    seller = item.get("seller") or {}
    try:
        feedback = float(seller.get("feedbackPercentage") or 0)
    except Exception:
        feedback = 0.0
    ship = shipping_cost(item)

    return {
        "id": item.get("itemId") or "",
        "source": "eBay",
        "sourceItemId": item.get("itemId") or "",
        "title": title,
        "brand": "",
        "model": "",
        "category": category,
        "comparisonQuery": query,
        "condition": item.get("condition") or "",
        "seller": seller.get("username") or "",
        "sellerRating": feedback,
        "imageUrl": (item.get("image") or {}).get("imageUrl") or "",
        "listingUrl": item.get("itemWebUrl") or "",
        "currentPrice": price,
        "originalPrice": original,
        "shippingCost": ship,
        "discountAmount": round(max(0.0, original - price), 2) if original else 0.0,
        "discountPercent": discount,
        "currency": (item.get("price") or {}).get("currency", "USD"),
    }


def main():
    token = get_token()
    seen = set()
    deals = []
    errors = []

    for category, query in QUERIES:
        try:
            raw = fetch_query(token, query)
        except Exception as exc:
            errors.append({"query": query, "error": str(exc)[:180]})
            continue

        candidates = []
        for item in raw:
            deal = simplify_base(item, category, query)
            if not deal["sourceItemId"] or not deal["title"] or not deal["listingUrl"] or deal["currentPrice"] <= 0:
                continue
            if not deal["imageUrl"]:
                continue
            candidates.append(deal)

        comparable_prices = [round(d["currentPrice"] + d["shippingCost"], 2) for d in candidates if d["currentPrice"] > 0]
        market_median = trimmed_median(comparable_prices)
        comparable_count = len(comparable_prices)

        for deal in candidates:
            item_id = deal["sourceItemId"]
            if item_id in seen:
                continue
            deal.update(classify(deal, comparable_count, market_median))
            deal["scoringVersion"] = SCORING_VERSION
            deal["classificationRule"] = (
                "STRONG BUY: score >=78, >=20% below comparable median, seller >=97%, 5+ comparables. "
                "GOOD DEAL: score >=58, >=10% below median, seller >=95%, 4+ comparables."
            )
            seen.add(item_id)
            deals.append(deal)

    deals.sort(key=lambda x: (-x["dealScore"], -x["marketSavingsPercent"], x["landedPrice"]))
    deals = deals[:MAX_OUTPUT]

    categories = sorted({d["category"] for d in deals})
    out = {
        "status": "ok",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "eBay Browse API",
        "marketplace": MARKETPLACE,
        "app": "KAEL Deal Radar",
        "feedVersion": 2,
        "scoringVersion": SCORING_VERSION,
        "scoringMethod": "query-level comparable landed-price median + seller + shipping + condition; list-price discount is only a small bonus",
        "count": len(deals),
        "categories": categories,
        "errors": errors,
        "items": deals,
    }
    with open("deal-radar.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
