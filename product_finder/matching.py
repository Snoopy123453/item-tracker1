from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from .models import ProductResult
from .utils import clean_text

MODEL_RE = re.compile(r"\b(?=[A-Z0-9._/-]{4,}\b)(?=[A-Z0-9._/-]*\d)[A-Z0-9]+(?:[-./][A-Z0-9]+)+\b", re.I)
TOKEN_RE = re.compile(r"\b[A-Z0-9]+(?:[-./][A-Z0-9]+)*\b", re.I)
DIMENSION_RE = re.compile(r"\b\d+(?:-\d+/\d+|/\d+|\.\d+)?\s*(?:\"|IN(?:CH(?:ES)?)?|MM|CM|FT|FOOT|FEET)\b", re.I)
STORAGE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(TB|GB)\b", re.I)
VOLTAGE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*V(?:OLT(?:S)?)?\b", re.I)
SIZE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(INCH|IN|\")\b", re.I)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "body", "complete", "for", "from", "in", "is",
    "it", "no", "of", "on", "or", "product", "series", "the", "to", "type", "with", "without",
    "floor", "drain", "sink", "faucet", "fixture", "equipment", "model", "round", "provided", "new",
    "sale", "buy", "online", "shipping", "free", "each", "unit", "item",
}

BRANDS = {
    "apple", "samsung", "google", "sony", "lg", "dell", "hp", "lenovo", "asus", "acer", "microsoft",
    "dewalt", "milwaukee", "makita", "bosch", "ridgid", "ryobi", "just", "josam", "mcguire", "chicago",
    "watersaver", "water saver", "kohler", "moen", "delta", "zurn", "sloan", "toto", "american standard",
    "grainger", "uline", "nvidia", "amd", "intel", "crucial", "seagate", "western digital",
}

CATEGORY_TERMS = {
    "electronics": {"iphone", "ipad", "macbook", "galaxy", "pixel", "laptop", "phone", "smartphone", "tablet", "monitor", "tv", "television", "ssd", "gpu", "graphics card"},
    "tools": {"drill", "impact driver", "saw", "grinder", "tool", "battery", "charger", "brushless"},
    "plumbing": {"floor drain", "floor sink", "faucet", "sink", "trap primer", "strainer", "no hub", "no-hub", "wejloc", "nickaloy", "nikaloy", "eyewash", "shower"},
    "appliances": {"refrigerator", "washer", "dryer", "dishwasher", "range", "oven", "microwave", "freezer"},
}

FEATURE_TERMS = {
    "adjustable", "aluminum", "barrier-free", "brass", "cast iron", "clamping flange", "copper",
    "double drainage flange", "electronic", "gauge", "ground joint", "hub", "nickaloy", "no hub",
    "primer adapter", "recessed", "satin", "seamless", "stainless steel", "strainer", "trap primer",
    "type 304", "wejloc", "weepholes", "wejloc clamp ring", "unlocked", "titanium", "brushless",
    "cordless", "stainless", "chrome", "refurbished", "renewed", "used", "open box",
}

CONDITION_TERMS = {
    "new": {"new", "brand new"},
    "refurbished": {"refurbished", "renewed", "restored", "certified refurbished"},
    "used": {"used", "pre-owned", "preowned"},
    "open box": {"open box", "open-box"},
}


def _normalize(value: str) -> str:
    text = clean_text(value).upper()
    replacements = {
        "NIKALOY": "NICKALOY", "NO-HUB": "NO HUB", "NOHUB": "NO HUB",
        "GIGABYTES": "GB", "GIGABYTE": "GB", "TERABYTES": "TB", "TERABYTE": "TB",
        "WI FI": "WIFI", "PRE OWNED": "USED", "PREOWNED": "USED", "OPEN-BOX": "OPEN BOX",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def _compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _normalize(value))


def _models(value: str) -> list[str]:
    models = [match.group(0).upper() for match in MODEL_RE.finditer(value or "")]
    normalized = _normalize(value)
    # Consumer-product model phrases that do not contain punctuation.
    patterns = [
        r"\bIPHONE\s+\d+(?:\s+(?:PRO|PRO MAX|PLUS|MINI|AIR|SE))*\b",
        r"\bGALAXY\s+[A-Z]?\d+(?:\s+(?:ULTRA|PLUS|FE))*\b",
        r"\bPIXEL\s+\d+(?:\s+(?:PRO|PRO XL|A))*\b",
        r"\bMACBOOK\s+(?:AIR|PRO)(?:\s+M\d(?:\s+(?:PRO|MAX|ULTRA))?)?\b",
        r"\b[A-Z]{2,6}\d{3,}[A-Z0-9-]*\b",
    ]
    for pattern in patterns:
        models.extend(re.findall(pattern, normalized, re.I))
    # Preserve order while deduplicating.
    return list(dict.fromkeys(m.strip().upper() for m in models if m.strip()))


def _tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in TOKEN_RE.findall(_normalize(value)):
        lowered = token.casefold()
        if lowered not in STOPWORDS and len(token) >= 2:
            tokens.add(token)
    return tokens


def _important_tokens(value: str) -> set[str]:
    tokens = _tokens(value)
    return {t for t in tokens if any(ch.isdigit() for ch in t) or len(t) >= 4 or t.casefold() in BRANDS}


def _features(value: str) -> set[str]:
    normalized = _normalize(value)
    found = {_normalize(term) for term in FEATURE_TERMS if _normalize(term) in normalized}
    found.update(_normalize(d) for d in DIMENSION_RE.findall(value or ""))
    return found


def _brand(value: str) -> str:
    normalized = _normalize(value)
    for brand in sorted(BRANDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(_normalize(brand))}\b", normalized):
            return _normalize(brand)
    # Conservative fallback: only use first word when it is alphabetic and not a product-family term.
    first = normalized.split(" ", 1)[0] if normalized else ""
    generic = {"IPHONE", "GALAXY", "PIXEL", "FLOOR", "SINK", "FAUCET", "DRILL", "LAPTOP"}
    return first if first.isalpha() and first not in generic and len(first) >= 3 else ""


def _category(value: str) -> str:
    normalized = _normalize(value)
    best = (0, "general")
    for category, terms in CATEGORY_TERMS.items():
        count = sum(1 for term in terms if _normalize(term) in normalized)
        if count > best[0]:
            best = (count, category)
    return best[1]


def _attribute_values(pattern: re.Pattern[str], value: str) -> set[str]:
    values = set()
    for match in pattern.finditer(value or ""):
        number, unit = match.groups()
        values.add(f"{float(number):g}{unit.upper().replace('INCH', 'IN').replace('\"', 'IN')}")
    return values


def _condition(value: str) -> str:
    normalized = _normalize(value)
    for label, terms in CONDITION_TERMS.items():
        if any(_normalize(term) in normalized for term in terms):
            return label
    return "unknown"


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _attribute_component(name: str, requested: set[str], offered: set[str], weight: float, parts: list[str], conflicts: list[str]) -> tuple[float, float]:
    """Return earned points and applicable weight. Missing listing values reduce confidence, not to zero."""
    if not requested:
        return 0.0, 0.0
    if not offered:
        parts.append(f"{name}: not stated")
        return weight * 0.45, weight
    matched = requested & offered
    if matched:
        ratio = len(matched) / len(requested)
        parts.append(f"{name}: matched {', '.join(sorted(matched))}")
        if requested != offered and not requested.issubset(offered):
            conflicts.append(f"{name} differs ({', '.join(sorted(offered))})")
        return weight * ratio, weight
    conflicts.append(f"{name} differs: requested {', '.join(sorted(requested))}; listing shows {', '.join(sorted(offered))}")
    return 0.0, weight


def score_product_match(result: ProductResult) -> ProductResult:
    query = result.query or ""
    listing = " ".join([result.title or "", result.snippet or "", result.condition or "", result.seller or ""])
    nq, nl = _normalize(query), _normalize(listing)
    category = _category(query)
    parts: list[str] = []
    conflicts: list[str] = []

    # Strong lexical signal, robust to punctuation/order differences.
    q_tokens, l_tokens = _important_tokens(query), _important_tokens(listing)
    coverage = len(q_tokens & l_tokens) / max(1, len(q_tokens))
    phrase_similarity = _ratio(query, result.title or listing)
    lexical = 25 * coverage + 10 * phrase_similarity
    parts.append(f"keyword coverage {coverage:.0%}; title similarity {phrase_similarity:.0%}")

    score = lexical
    applicable = 35.0

    # Brand comparison.
    q_brand, l_brand = _brand(query), _brand(listing)
    brand_weight = 15.0
    if q_brand:
        applicable += brand_weight
        if q_brand == l_brand or re.search(rf"\b{re.escape(q_brand)}\b", nl):
            score += brand_weight
            parts.append(f"brand matched: {q_brand.title()}")
        elif l_brand:
            conflicts.append(f"brand differs: requested {q_brand.title()}, listing shows {l_brand.title()}")
        else:
            score += brand_weight * 0.35
            parts.append("brand not stated")

    # Model/product-family comparison. Handles iPhone 15 Pro as well as 30000-5A-Z.
    q_models, l_models = _models(query), _models(listing)
    model_weight = 30.0 if q_models else 0.0
    exact_model = False
    same_family = False
    if q_models:
        applicable += model_weight
        for qm in q_models:
            qmc = _compact(qm)
            if any(qmc == _compact(lm) for lm in l_models) or qmc in _compact(listing):
                exact_model = True
                break
        if exact_model:
            score += model_weight
            parts.append(f"model matched: {q_models[0]}")
        else:
            for qm in q_models:
                qbase = re.split(r"[-./ ]", qm)[0]
                if len(qbase) >= 4 and qbase in nl:
                    same_family = True
                    break
            if same_family:
                score += model_weight * 0.55
                conflicts.append("model family is similar, but exact configuration was not confirmed")
            elif l_models:
                conflicts.append(f"model differs: requested {', '.join(q_models)}; listing shows {', '.join(l_models)}")
            else:
                score += model_weight * 0.30
                parts.append("model not stated clearly")

    # Category-specific structured attributes. Only applicable attributes count in denominator.
    attribute_specs: list[tuple[str, set[str], set[str], float]] = []
    if category == "electronics":
        attribute_specs.extend([
            ("storage", _attribute_values(STORAGE_RE, query), _attribute_values(STORAGE_RE, listing), 12.0),
        ])
    elif category == "tools":
        attribute_specs.extend([
            ("voltage", _attribute_values(VOLTAGE_RE, query), _attribute_values(VOLTAGE_RE, listing), 10.0),
        ])
    elif category in {"plumbing", "appliances"}:
        attribute_specs.extend([
            ("dimensions", {_normalize(x) for x in DIMENSION_RE.findall(query)}, {_normalize(x) for x in DIMENSION_RE.findall(listing)}, 10.0),
        ])

    for name, requested, offered, weight in attribute_specs:
        earned, used = _attribute_component(name, requested, offered, weight, parts, conflicts)
        score += earned
        applicable += used

    # Feature matching uses dynamic denominator so irrelevant construction fields do not hurt electronics.
    q_features, l_features = _features(query), _features(listing)
    matched_features = sorted(q_features & l_features)
    missing_features = sorted(q_features - l_features)
    if q_features:
        feature_weight = 15.0
        applicable += feature_weight
        score += feature_weight * (len(matched_features) / len(q_features))
        if matched_features:
            parts.append("features matched: " + ", ".join(matched_features))
        if missing_features:
            parts.append("features not stated: " + ", ".join(missing_features[:8]))

    # Condition is a hard purchasing distinction when the query implies new or omits condition.
    q_condition = _condition(query)
    l_condition = _condition(listing)
    condition_penalty = 0.0
    if l_condition in {"refurbished", "used", "open box"} and q_condition not in {l_condition, "used"}:
        condition_penalty = {"refurbished": 10.0, "open box": 12.0, "used": 18.0}[l_condition]
        conflicts.append(f"condition differs: listing is {l_condition}")

    # Convert dynamically applicable points to a percentage. The baseline lexical block is always applicable.
    normalized_score = 100.0 * score / max(1.0, applicable)
    normalized_score -= condition_penalty

    # Exact normalized title/query containment should never look mediocre.
    if nq and (nq in nl or _compact(query) in _compact(result.title or "")):
        normalized_score = max(normalized_score, 97.0)
    elif exact_model and coverage >= 0.75:
        normalized_score = max(normalized_score, 94.0)
    elif coverage >= 0.90 and not conflicts:
        normalized_score = max(normalized_score, 92.0)

    final_score = round(max(0.0, min(100.0, normalized_score)), 1)

    if final_score >= 95:
        grade, recommendation = "Exact / Excellent", "Top purchase candidate — verify seller, stock, revision, and warranty"
    elif final_score >= 88:
        grade, recommendation = "Strong", "Strong candidate — verify any unstated attributes before ordering"
    elif final_score >= 75:
        grade, recommendation = "Good", "Likely match — review differences and official specification"
    elif final_score >= 55:
        grade, recommendation = "Review", "Do not order until model and specification differences are resolved"
    else:
        grade, recommendation = "Poor", "Reject or use only as a search lead"

    evidence_count = len(q_tokens & l_tokens) + len(matched_features) + int(bool(q_brand and q_brand in nl)) + int(exact_model)
    confidence = "High" if evidence_count >= 5 or exact_model else "Medium" if evidence_count >= 2 else "Low"

    result.match_score = final_score
    result.match_grade = grade
    result.match_confidence = confidence
    result.match_profile = category.title()
    result.exact_model_match = exact_model
    result.matched_features = "; ".join(matched_features) or "No structured features confirmed"
    result.missing_features = "; ".join(missing_features) or "None identified from requested text"
    result.differences = "; ".join(conflicts) or "No material contradictions detected"
    result.score_breakdown = "; ".join(parts)
    result.recommendation = recommendation
    return result


def rank_product_matches(results: list[ProductResult]) -> list[ProductResult]:
    """Score listings, sort each query by match quality, and flag one best match per query."""
    groups: dict[str, list[ProductResult]] = defaultdict(list)
    order: list[str] = []
    for result in results:
        key = (result.query or "").casefold()
        if key not in groups:
            order.append(key)
        groups[key].append(score_product_match(result))

    ranked: list[ProductResult] = []
    for key in order:
        group = groups[key]
        group.sort(key=lambda item: (-(item.match_score or 0), item.extracted_price is None, item.extracted_price or float("inf"), item.rank))
        for idx, item in enumerate(group, start=1):
            item.best_match = idx == 1
            item.rank = idx
            ranked.append(item)
    return ranked
