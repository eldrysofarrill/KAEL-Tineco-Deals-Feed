import json
import re
import statistics
import urllib.parse
import urllib.request
from collections import defaultdict
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
MAX_COMPARABLE_QUERY = 24
MAX_OUTPUT = 70
MAX_COMPARABLE_GROUPS = 48
SCORING_VERSION = "3.0"

KNOWN_BRANDS = (
    "SAMSUNG", "APPLE", "DEWALT", "NINTENDO", "KITCHENAID", "NINJA", "TINECO",
)

NOISE_MODEL_TOKENS = {
    "5G", "4G", "20V", "18V", "12V", "120V", "110V", "240V",
    "2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019",
}


def money_value(obj):
    if not obj:
        return 0.0
    try:
        return float(obj.get("value") or 0)
    except Exception:
        return 0.0


def fetch_query(token, query, limit=MAX_PER_QUERY):
    params = {
        "q": query,
        "limit": str(limit),
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


def normalize_text(value):
    value = (value or "").upper().replace("™", " ").replace("®", " ")
    value = re.sub(r"[^A-Z0-9.+-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def detect_brand(title):
    t = normalize_text(title)
    for brand in KNOWN_BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", t):
            return brand.title() if brand != "DEWALT" else "DEWALT"
    return ""


def storage_variant(title):
    t = normalize_text(title)
    tb = re.search(r"\b(1|2)\s*TB\b", t)
    if tb:
        return f"{tb.group(1)}TB"
    gb = re.search(r"\b(16|32|64|128|256|512)\s*GB\b", t)
    return f"{gb.group(1)}GB" if gb else ""


def condition_family(condition):
    c = (condition or "").lower()
    if "refurb" in c or "renewed" in c:
        return "REFURB"
    if "new" in c and "other" not in c:
        return "NEW"
    if any(x in c for x in ("used", "pre-owned", "preowned", "good", "excellent", "very good")):
        return "USED"
    return "OTHER"


def extract_model_identity(title, brand):
    t = normalize_text(title)

    if brand.upper() == "SAMSUNG":
        m = re.search(r"\bGALAXY\s+(S\d{1,2}(?:E|FE|ULTRA|PLUS|\+)?|A\d{1,2}|NOTE\s*\d{1,2}|Z\s*(?:FLIP|FOLD)\s*\d{0,2})\b", t)
        if m:
            model = re.sub(r"\s+", "", m.group(1)).replace("+", "PLUS")
            return model, "EXACT"
        m = re.search(r"\bSM[- ]?([A-Z0-9]{4,})\b", t)
        if m:
            return "SM-" + m.group(1), "EXACT"
        m = re.search(r"\b([SGA]\d{3,4}[A-Z]{0,2})\b", t)
        if m:
            return m.group(1), "MEDIUM"

    if brand.upper() == "APPLE":
        model_code = re.search(r"\bA\d{4}\b", t)
        if model_code:
            return model_code.group(0), "EXACT"
        gen = re.search(r"\bIPAD\b.*?\b(\d{1,2})(?:ST|ND|RD|TH)?\s*(?:GEN|GENERATION)\b", t)
        if gen:
            family = "IPAD"
            if "PRO" in t:
                family = "IPAD-PRO"
            elif "AIR" in t:
                family = "IPAD-AIR"
            elif "MINI" in t:
                family = "IPAD-MINI"
            return f"{family}-{gen.group(1)}GEN", "EXACT"
        year = re.search(r"\bIPAD\b.*?\b(201[5-9]|202[0-6])\b", t)
        if year:
            family = "IPAD"
            if "PRO" in t:
                family = "IPAD-PRO"
            elif "AIR" in t:
                family = "IPAD-AIR"
            elif "MINI" in t:
                family = "IPAD-MINI"
            return f"{family}-{year.group(1)}", "MEDIUM"

    if brand.upper() == "DEWALT":
        m = re.search(r"\b(D(?:CF|CD|CS|CK|CL|CH|CM|CV|CP|CB|CC|CR)\d{3,4}[A-Z0-9-]*)\b", t)
        if m:
            return m.group(1), "EXACT"

    if brand.upper() == "NINTENDO":
        if re.search(r"\bSWITCH\s+OLED\b", t):
            return "SWITCH-OLED", "EXACT"
        if re.search(r"\bSWITCH\s+LITE\b", t):
            return "SWITCH-LITE", "EXACT"
        if re.search(r"\bNINTENDO\s+SWITCH\b", t):
            return "SWITCH", "MEDIUM"

    if brand.upper() == "KITCHENAID":
        m = re.search(r"\b(KSM\d{2,4}[A-Z0-9-]*)\b", t)
        if m:
            return m.group(1), "EXACT"

    if brand.upper() == "NINJA":
        m = re.search(r"\b((?:AF|DZ|SP|OL|FD|OP|AG|DG|DT|SL|SF|CR|MC|BN)\d{2,4}[A-Z0-9-]*)\b", t)
        if m:
            return m.group(1), "EXACT"

    if brand.upper() == "TINECO":
        patterns = [
            r"\b(FLOOR\s+ONE\s+S\d+[A-Z0-9-]*)\b",
            r"\b(PURE\s+ONE\s+S\d+[A-Z0-9-]*)\b",
            r"\b(IFLOOR\s*\d*[A-Z0-9-]*)\b",
            r"\b(STRETCH\s+S\d+[A-Z0-9-]*)\b",
            r"\b(S\d+[A-Z0-9-]*)\b",
        ]
        for pattern in patterns:
            m = re.search(pattern, t)
            if m:
                return re.sub(r"\s+", "-", m.group(1)), "EXACT"

    generic = re.findall(r"\b[A-Z]{1,5}[-]?[A-Z0-9]*\d[A-Z0-9-]{2,}\b", t)
    for token in generic:
        token = token.strip("-")
        if token in NOISE_MODEL_TOKENS:
            continue
        if token.endswith("GB") or token.endswith("TB") or token.endswith("HZ"):
            continue
        if re.fullmatch(r"20\d{2}", token):
            continue
        return token, "MEDIUM"

    return "", "NONE"


def build_identity(title, condition, category):
    brand = detect_brand(title)
    model, quality = extract_model_identity(title, brand)
    storage = storage_variant(title) if category == "ELECTRONICS" else ""
    cond = condition_family(condition)

    if not brand or not model:
        quality = "NONE"

    key_parts = [brand.upper(), model.upper()]
    if storage:
        key_parts.append(storage.upper())
    key_parts.append(cond)
    key = "|".join(x for x in key_parts if x) if quality != "NONE" else ""

    query_parts = [brand, model]
    if storage:
        query_parts.append(storage)
    if cond == "REFURB":
        query_parts.append("refurbished")
    elif cond == "NEW":
        query_parts.append("new")
    elif cond == "USED":
        query_parts.append("used")
    query = " ".join(x for x in query_parts if x).strip()

    return {
        "brand": brand,
        "model": model,
        "variant": storage,
        "conditionFamily": cond,
        "comparableKey": key,
        "comparisonQuery": query,
        "matchQuality": quality,
    }


def identity_matches(target, candidate):
    if target["matchQuality"] == "NONE" or candidate["matchQuality"] == "NONE":
        return False
    if target["brand"].upper() != candidate["brand"].upper():
        return False
    if target["model"].upper() != candidate["model"].upper():
        return False
    if target["conditionFamily"] != candidate["conditionFamily"]:
        return False
    target_variant = target.get("variant") or ""
    candidate_variant = candidate.get("variant") or ""
    if target_variant and candidate_variant != target_variant:
        return False
    return True


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
    if landed <= 0 or market_median <= 0:
        return 0.0
    return round((market_median - landed) * 100.0 / market_median, 1)


def confidence_for(count, quality):
    if quality == "EXACT" and count >= 8:
        return "HIGH"
    if quality in ("EXACT", "MEDIUM") and count >= 4:
        return "MEDIUM"
    return "LOW"


def classify(deal, comparable_count, market_median):
    landed = round(deal["currentPrice"] + deal["shippingCost"], 2)
    savings = market_savings(landed, market_median)
    quality = deal.get("matchQuality", "NONE")
    confidence = confidence_for(comparable_count, quality)

    market_component = market_points(savings) if comparable_count >= 4 and quality != "NONE" else 0
    seller_component = seller_points(deal["sellerRating"])
    shipping_component = shipping_points(deal["shippingCost"])
    condition_component = condition_points(deal["condition"])

    promo_component = 0
    if market_component > 0 and deal["discountPercent"] >= 20:
        promo_component = min(4, int(deal["discountPercent"] // 20) + 1)

    score = min(100, market_component + seller_component + shipping_component + condition_component + promo_component)

    strong_allowed = quality == "EXACT" and comparable_count >= 5
    good_allowed = quality in ("EXACT", "MEDIUM") and comparable_count >= 4

    if strong_allowed and score >= 78 and savings >= 20 and deal["sellerRating"] >= 97:
        level = "STRONG BUY"
    elif good_allowed and score >= 58 and savings >= 10 and deal["sellerRating"] >= 95:
        level = "GOOD DEAL"
    else:
        level = "NORMAL"

    reasons = []
    if market_median > 0 and comparable_count >= 4:
        if savings >= 0:
            reasons.append(f"{savings:.0f}% below exact-match median")
        else:
            reasons.append(f"{abs(savings):.0f}% above exact-match median")
        reasons.append(f"{comparable_count} matched listings")
    else:
        reasons.append("Not enough same-model comparables")
    if deal["sellerRating"] > 0:
        reasons.append(f"Seller {deal['sellerRating']:.1f}% positive")
    reasons.append("Free shipping" if deal["shippingCost"] <= 0 else f"Shipping ${deal['shippingCost']:.2f}")

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


def simplify_base(item, category, seed_query):
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
    identity = build_identity(title, item.get("condition") or "", category)

    return {
        "id": item.get("itemId") or "",
        "source": "eBay",
        "sourceItemId": item.get("itemId") or "",
        "title": title,
        "brand": identity["brand"],
        "model": identity["model"],
        "variant": identity["variant"],
        "category": category,
        "seedQuery": seed_query,
        "comparisonQuery": identity["comparisonQuery"],
        "comparableKey": identity["comparableKey"],
        "matchQuality": identity["matchQuality"],
        "conditionFamily": identity["conditionFamily"],
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


def collect_exact_comparables(token, deal, cache):
    key = deal.get("comparableKey") or ""
    query = deal.get("comparisonQuery") or ""
    if not key or not query or deal.get("matchQuality") == "NONE":
        return [], 0.0
    if key in cache:
        return cache[key]

    try:
        raw = fetch_query(token, query, MAX_COMPARABLE_QUERY)
    except Exception:
        cache[key] = ([], 0.0)
        return cache[key]

    prices = []
    seller_counts = defaultdict(int)
    seen = set()
    target_identity = {
        "brand": deal.get("brand", ""),
        "model": deal.get("model", ""),
        "variant": deal.get("variant", ""),
        "conditionFamily": deal.get("conditionFamily", "OTHER"),
        "matchQuality": deal.get("matchQuality", "NONE"),
    }

    for item in raw:
        item_id = item.get("itemId") or ""
        if not item_id or item_id == deal.get("sourceItemId") or item_id in seen:
            continue
        price = money_value(item.get("price"))
        if price <= 0:
            continue
        candidate_identity = build_identity(item.get("title") or "", item.get("condition") or "", deal["category"])
        if not identity_matches(target_identity, candidate_identity):
            continue
        seller = ((item.get("seller") or {}).get("username") or "").lower()
        if seller and seller_counts[seller] >= 2:
            continue
        ship = shipping_cost(item)
        landed = round(price + ship, 2)
        if landed <= 0:
            continue
        seen.add(item_id)
        if seller:
            seller_counts[seller] += 1
        prices.append(landed)
        if len(prices) >= 20:
            break

    result = (prices, trimmed_median(prices))
    cache[key] = result
    return result


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
            deal = simplify_base(item, category, query)
            if not deal["sourceItemId"] or not deal["title"] or not deal["listingUrl"] or deal["currentPrice"] <= 0:
                continue
            if not deal["imageUrl"]:
                continue
            item_id = deal["sourceItemId"]
            if item_id in seen:
                continue
            seen.add(item_id)
            deals.append(deal)

    comparable_cache = {}
    scored_groups = 0
    for deal in deals:
        market_median = 0.0
        comparable_count = 0
        key = deal.get("comparableKey") or ""

        if key and key not in comparable_cache and scored_groups >= MAX_COMPARABLE_GROUPS:
            comparable_cache[key] = ([], 0.0)

        if key:
            is_new_group = key not in comparable_cache
            prices, market_median = collect_exact_comparables(token, deal, comparable_cache)
            if is_new_group:
                scored_groups += 1
            comparable_count = len(prices)

        deal.update(classify(deal, comparable_count, market_median))
        deal["scoringVersion"] = SCORING_VERSION
        deal["comparisonBasis"] = "same brand + model + variant when present + condition family; landed price includes shipping"
        deal["classificationRule"] = (
            "STRONG BUY requires exact identity, score >=78, >=20% below same-model landed-price median, "
            "seller >=97%, and 5+ matched listings. GOOD DEAL requires 4+ matched listings, score >=58, "
            ">=10% below median, seller >=95%. Insufficient exact comparables stays NORMAL."
        )

    deals.sort(
        key=lambda x: (
            0 if x["dealLevel"] == "STRONG BUY" else 1 if x["dealLevel"] == "GOOD DEAL" else 2,
            -x["dealScore"],
            -x["marketSavingsPercent"],
            x["landedPrice"],
        )
    )
    deals = deals[:MAX_OUTPUT]

    categories = sorted({d["category"] for d in deals})
    out = {
        "status": "ok",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "eBay Browse API",
        "marketplace": MARKETPLACE,
        "app": "KAEL Deal Radar",
        "feedVersion": 3,
        "scoringVersion": SCORING_VERSION,
        "scoringMethod": "same-product comparable landed-price median + seller + shipping + condition; broad seed-query medians are forbidden",
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
