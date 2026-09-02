"""Home Depot Penny Radar experimental signal engine."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

OBSERVATIONS = Path("home-depot-observations.json")
HISTORY = Path("home-depot-history.json")
OUTPUT = Path("penny-radar.json")
ENGINE_VERSION = "1.0-experimental"

def _number(value, default=0.0):
    try: return float(value)
    except (TypeError, ValueError): return default

def _key(item):
    return f"{str(item.get('storeId', '')).strip()}|{str(item.get('sku', '')).strip()}"

def _discount(item):
    price, regular = _number(item.get("price")), _number(item.get("regularPrice"))
    return round((regular-price)*100/regular, 1) if regular > price >= 0 else 0.0

def classify(current, previous=None, disappeared=False):
    price, discount = _number(current.get("price"), -1), _discount(current)
    method = str(current.get("confirmationMethod") or "").strip().lower()
    confirmed = bool(current.get("manualConfirmed")) or method in {"receipt","register","store_scan"}
    reasons, score = [], 0
    if confirmed and 0 <= price <= .01:
        return "CONFIRMED", 100, ["Penny price physically confirmed"]
    if 0 <= price <= .01:
        score, reasons = 90, ["Penny price observed but not physically confirmed"]
    elif disappeared:
        score, reasons = 75, ["Price/product disappeared after prior clearance"]
    elif discount >= 75:
        score, reasons = 65, [f"Deep clearance: {discount:.0f}% off"]
    elif discount >= 40:
        score, reasons = 35, [f"Clearance markdown: {discount:.0f}% off"]
    else:
        reasons = ["No strong penny signal yet"]
    if previous:
        old_price = _number(previous.get("price"), -1)
        if price >= 0 and old_price > price:
            drop = (old_price-price)*100/old_price if old_price else 0
            if drop >= 50:
                score += 10; reasons.append(f"Price dropped {drop:.0f}% since previous observation")
        if _number(previous.get("stock"), -1) > 0 and _number(current.get("stock"), -1) == 0:
            score += 5; reasons.append("Store stock changed from available to zero")
    score = min(99, score)
    status = "PENNY CANDIDATE" if score >= 75 else "HIGH PROBABILITY" if score >= 55 else "WATCH"
    return status, score, reasons

def run(observations_path=OBSERVATIONS, history_path=HISTORY, output_path=OUTPUT):
    now = datetime.now(timezone.utc).isoformat()
    payload = json.loads(Path(observations_path).read_text(encoding="utf-8"))
    observations = payload.get("items", [])
    complete = bool(payload.get("captureComplete"))
    stores = {str(x) for x in payload.get("capturedStoreIds", [])}
    hp = Path(history_path)
    history = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {"engineVersion":ENGINE_VERSION,"products":{}}
    products, current_keys, results = history.setdefault("products", {}), set(), []
    for item in observations:
        key = _key(item)
        if key == "|": continue
        current_keys.add(key)
        previous = products.get(key, {}).get("latest")
        status, score, reasons = classify(item, previous)
        result = dict(item)
        result.update({"retailer":"Home Depot","signalStatus":status,"signalScore":score,"signalReasons":reasons,
                       "requiresPhysicalConfirmation":status!="CONFIRMED","observedAt":item.get("observedAt") or now})
        results.append(result)
        entry = products.setdefault(key, {"history":[]})
        entry["latest"] = dict(item, observedAt=result["observedAt"])
        entry["history"] = (entry.get("history", []) + [entry["latest"]])[-30:]
    if complete:
        for key, entry in list(products.items()):
            if key in current_keys: continue
            store_id, sku = key.split("|", 1)
            if stores and store_id not in stores: continue
            previous = entry.get("latest") or {}
            if _discount(previous) < 40: continue
            item = dict(previous, storeId=store_id, sku=sku, priceAvailable=False)
            status, score, reasons = classify(item, previous, disappeared=True)
            item.update({"retailer":"Home Depot","signalStatus":status,"signalScore":score,"signalReasons":reasons,
                         "requiresPhysicalConfirmation":True,"observedAt":now})
            results.append(item)
    rank={"CONFIRMED":0,"PENNY CANDIDATE":1,"HIGH PROBABILITY":2,"WATCH":3}
    results.sort(key=lambda x:(rank[x["signalStatus"]],-x["signalScore"],str(x.get("storeId")),str(x.get("sku"))))
    output={"status":"ok","experimental":True,"retailer":"Home Depot","engineVersion":ENGINE_VERSION,"updatedAt":now,
            "captureComplete":complete,"count":len(results),
            "method":"SKU + storeId price history; disappearance after clearance is a candidate signal, never confirmation",
            "items":results}
    Path(output_path).write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    history.update({"engineVersion":ENGINE_VERSION,"updatedAt":now})
    hp.write_text(json.dumps(history,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return output

if __name__ == "__main__": run()
