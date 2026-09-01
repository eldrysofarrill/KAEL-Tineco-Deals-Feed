import json
import math
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


def classify(discount, feedback, price):
    score = 0
    if discount >= 60:
        score += 70
    elif discount >= 50:
        score += 62
    elif discount >= 40:
        score += 52
    elif discount >= 30:
        score += 40
    elif discount >= 20:
        score += 25
    else:
        score += max(0, int(discount))

    if feedback >= 99:
        score += 20
    elif feedback >= 97:
        score += 15
    elif feedback >= 95:
        score += 10

    if 20 <= price <= 500:
        score += 8

    score = min(100, score)
    if score >= 75 and discount >= 40:
        level = "STRONG BUY"
    elif score >= 50 and discount >= 25:
        level = "GOOD DEAL"
    else:
        level = "NORMAL"
    return score, level


def simplify(item, category):
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
    score, level = classify(discount, feedback, price)
    shipping = item.get("shippingOptions") or []
    shipping_cost = 0.0
    if shipping:
        shipping_cost = money_value((shipping[0] or {}).get("shippingCost"))

    return {
        "id": item.get("itemId") or "",
        "source": "eBay",
        "sourceItemId": item.get("itemId") or "",
        "title": title,
        "brand": "",
        "model": "",
        "category": category,
        "condition": item.get("condition") or "",
        "seller": seller.get("username") or "",
        "sellerRating": feedback,
        "imageUrl": (item.get("image") or {}).get("imageUrl") or "",
        "listingUrl": item.get("itemWebUrl") or "",
        "currentPrice": price,
        "originalPrice": original,
        "shippingCost": shipping_cost,
        "discountAmount": round(max(0.0, original - price), 2) if original else 0.0,
        "discountPercent": discount,
        "currency": (item.get("price") or {}).get("currency", "USD"),
        "dealScore": score,
        "dealLevel": level,
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
        for item in raw:
            deal = simplify(item, category)
            item_id = deal["sourceItemId"]
            if not item_id or item_id in seen:
                continue
            if not deal["title"] or not deal["listingUrl"] or deal["currentPrice"] <= 0:
                continue
            if not deal["imageUrl"]:
                continue
            # Keep the radar focused on actual bargains when eBay exposes a comparison price.
            if deal["discountPercent"] < 15:
                continue
            seen.add(item_id)
            deals.append(deal)

    deals.sort(key=lambda x: (-x["dealScore"], -x["discountPercent"], x["currentPrice"]))
    deals = deals[:MAX_OUTPUT]

    categories = sorted({d["category"] for d in deals})
    out = {
        "status": "ok",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "eBay Browse API",
        "marketplace": MARKETPLACE,
        "app": "KAEL Deal Radar",
        "feedVersion": 1,
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
