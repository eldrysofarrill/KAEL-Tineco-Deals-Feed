import base64
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CLIENT_ID = "EldrysOF-KAELVacu-PRD-d013d68a0-1d27dcb7"
CLIENT_SECRET = os.environ["EBAY_CLIENT_SECRET"]
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
MARKETPLACE = "EBAY_US"
SELLER = "tinecous"

MODEL_RULES = [
    ("FLOOR ONE S5 COMBO", ["FLOOR ONE S5 COMBO", "S5 COMBO"]),
    ("FLOOR ONE S3 PRO", ["FLOOR ONE S3 PRO", "S3 PRO"]),
    ("FLOOR ONE STRETCH S6", ["FLOOR ONE STRETCH S6", "STRETCH S6"]),
    ("FLOOR ONE S7", ["FLOOR ONE S7", " S7 "]),
    ("FLOOR ONE S6", ["FLOOR ONE S6", " S6 "]),
    ("FLOOR ONE S5", ["FLOOR ONE S5", " S5 "]),
    ("FLOOR ONE S3", ["FLOOR ONE S3", " S3 "]),
    ("iFLOOR 5", ["IFLOOR 5"]),
    ("iFLOOR 3", ["IFLOOR 3"]),
    ("iFLOOR 2", ["IFLOOR 2"]),
    ("iFLOOR", ["IFLOOR"]),
    ("GO XL 503", ["GO XL 503", "XL 503"]),
]

KNOWN_CODES = {
    "FW051800US": "FLOOR ONE S3 PRO",
}


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
        return 0.0
    try:
        return float(obj.get("value") or 0)
    except Exception:
        return 0.0


def detect_code(title):
    m = re.search(r"\b([A-Z]{2,4}\d{4,}[A-Z]{0,3})\b", title.upper())
    return m.group(1) if m else ""


def detect_model(title, code):
    if code in KNOWN_CODES:
        return KNOWN_CODES[code]
    hay = " " + title.upper().replace("-", " ") + " "
    for model, needles in MODEL_RULES:
        if any(n in hay for n in needles):
            return model
    return "TINECO"


def simplify(item):
    title = item.get("title") or "Tineco"
    code = detect_code(title)
    model = detect_model(title, code)
    price = money_value(item.get("price"))
    marketing = item.get("marketingPrice") or {}
    original = money_value(marketing.get("originalPrice"))
    discount_pct = marketing.get("discountPercentage")
    try:
        discount_pct = float(discount_pct) if discount_pct is not None else 0.0
    except Exception:
        discount_pct = 0.0

    seller = item.get("seller") or {}
    return {
        "itemId": item.get("itemId") or "",
        "title": title,
        "model": model,
        "modelCode": code,
        "price": price,
        "currency": (item.get("price") or {}).get("currency", "USD"),
        "originalPrice": original,
        "discountPercent": discount_pct,
        "condition": item.get("condition") or "Refurbished",
        "conditionId": item.get("conditionId") or "",
        "seller": seller.get("username") or SELLER,
        "sellerFeedbackPercent": seller.get("feedbackPercentage"),
        "url": item.get("itemWebUrl") or "https://www.ebay.com/str/tinecoofficialshop",
        "imageUrl": (item.get("image") or {}).get("imageUrl") or "",
    }


def main():
    token = get_token()
    raw = fetch_items(token)
    items = [simplify(x) for x in raw]
    items = [x for x in items if x.get("seller", "").lower() == SELLER]
    items.sort(key=lambda x: (x["price"] <= 0, x["price"] if x["price"] > 0 else 10**9))

    out = {
        "status": "ok",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
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
