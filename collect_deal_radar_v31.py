import re

import collect_deal_radar as radar

radar.SCORING_VERSION = "3.1"


def strict_storage_variant(title):
    t = radar.normalize_text(title)
    matches = []
    for m in re.finditer(r"\b(1|2)\s*TB\b", t):
        matches.append(f"{m.group(1)}TB")
    # Accept common seller shorthand/typos such as 64G or 64B, but reject listings
    # that advertise multiple capacities because their displayed price is ambiguous.
    for m in re.finditer(r"\b(16|32|64|128|256|512)\s*(?:GB|G|B)\b", t):
        matches.append(f"{m.group(1)}GB")
    unique = []
    for value in matches:
        if value not in unique:
            unique.append(value)
    return unique[0] if len(unique) == 1 else ""


radar.storage_variant = strict_storage_variant
_original_build_identity = radar.build_identity


def strict_build_identity(title, condition, category):
    result = _original_build_identity(title, condition, category)
    # Phones/tablets vary heavily by capacity. If capacity cannot be determined
    # unambiguously, do not allow a market-backed rating for that listing.
    if category == "ELECTRONICS" and result.get("brand", "").upper() in ("APPLE", "SAMSUNG") and not result.get("variant"):
        result["matchQuality"] = "NONE"
        result["comparableKey"] = ""
        result["comparisonQuery"] = ""
    return result


radar.build_identity = strict_build_identity


if __name__ == "__main__":
    radar.main()
