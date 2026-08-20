import base64
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CLIENT_ID = "EldrysOF-KAELVacu-PRD-d013d68a0-1d27dcb7"
CLIENT_SECRET = os.environ["EBAY_CLIENT_SECRET"]
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
MARKETPLACE = "EBAY_US"
SELLER = "tinecous"


def get_token():
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def fetch_items(token):
    params = {
        "q": "Tineco refurbished",
        "limit": "100",
        "filter": f"sellers:{{{SELLER}}}",
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


def money_value(obj):
    if not obj:
        return None
    try:
        return float(obj.get("value"))
    except Exception:
        return None


def simplify(item):
    price = money_value(item.get("price"))
    marketing = item.get("marketingPrice") or {}
    original = money_value(marketing.get("originalPrice"))
    discount_pct = marketing.get("discountPercentage")
    try:
        discount_pct = float(discount_pct) if discount_pct is not None else None
    except Exception:
        discount_pct = None

    seller = item.get("seller") or {}
    image = (item.get("image") or {}).get("imageUrl")
    return {
        "item_id": item.get("itemId"),
        "title": item.get("title"),
        "price": price,
        "currency": (item.get("price") or {}).get("currency", "USD"),
        "original_price": original,
        "discount_percent": discount_pct,
        "condition": item.get("condition"),
        "condition_id": item.get("conditionId"),
        "seller": seller.get("username"),
        "seller_feedback_percent": seller.get("feedbackPercentage"),
        "item_url": item.get("itemWebUrl"),
        "image_url": image,
        "buying_options": item.get("buyingOptions", []),
    }


def main():
    token = get_token()
    raw = fetch_items(token)
    items = [simplify(x) for x in raw]
    items = [x for x in items if x.get("seller", "").lower() == SELLER]
    items.sort(key=lambda x: (x["price"] is None, x["price"] if x["price"] is not None else 10**9))

    out = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "eBay Browse API",
        "marketplace": MARKETPLACE,
        "seller": SELLER,
        "query": "Tineco refurbished",
        "count": len(items),
        "items": items,
    }
    with open("deals.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
