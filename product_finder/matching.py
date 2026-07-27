from __future__ import annotations

import re
from collections import defaultdict

from .models import ProductResult
from .utils import clean_text

MODEL_RE = re.compile(r"\b(?=[A-Z0-9._/-]{4,}\b)(?=[A-Z0-9._/-]*\d)[A-Z0-9]+(?:[-./][A-Z0-9]+)+\b", re.I)
TOKEN_RE = re.compile(r"\b[A-Z0-9]+(?:[-./][A-Z0-9]+)*\b", re.I)
DIMENSION_RE = re.compile(r"\b\d+(?:-\d+/\d+|/\d+|\.\d+)?\s*(?:\"|IN(?:CH(?:ES)?)?|MM|CM|FT|FOOT|FEET)\b", re.I)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "body", "complete", "for", "from", "in", "is",
    "it", "no", "of", "on", "or", "product", "series", "the", "to", "type", "with", "without",
    "floor", "drain", "sink", "faucet", "fixture", "equipment", "model", "round", "provided",
}
FEATURE_TERMS = {
    "adjustable", "aluminum", "barrier-free", "brass", "cast iron", "clamping flange", "copper",
    "double drainage flange", "electronic", "gauge", "ground joint", "hub", "nickaloy", "nikaloy",
    "no hub", "no-hub", "primer adapter", "recessed", "satin", "seamless", "stainless steel",
    "strainer", "trap primer", "type 304", "wejloc", "weepholes", "wejloc clamp ring",
}


def _normalize(value: str) -> str:
    text = clean_text(value).upper()
    text = text.replace("NIKALOY", "NICKALOY").replace("NO-HUB", "NO HUB")
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def _models(value: str) -> list[str]:
    return [match.group(0).upper() for match in MODEL_RE.finditer(value or "")]


def _tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in TOKEN_RE.findall(_normalize(value)):
        lowered = token.casefold()
        if lowered not in STOPWORDS and len(token) >= 3:
            tokens.add(token)
    return tokens


def _features(value: str) -> set[str]:
    normalized = _normalize(value)
    found = {term for term in FEATURE_TERMS if _normalize(term) in normalized}
    found.update(d.upper() for d in DIMENSION_RE.findall(value or ""))
    return found


def _manufacturer(query: str) -> str:
    for token in TOKEN_RE.findall(query or ""):
        cleaned = token.strip("-./")
        if cleaned and cleaned.casefold() not in STOPWORDS and not any(ch.isdigit() for ch in cleaned):
            return cleaned.upper()
    return ""


def score_product_match(result: ProductResult) -> ProductResult:
    query = result.query or ""
    listing = " ".join([result.title or "", result.snippet or "", result.seller or ""])
    normalized_listing = _normalize(listing)

    query_models = _models(query)
    listing_models = _models(listing)
    exact_models = [model for model in query_models if _normalize(model) in normalized_listing]
    same_family = []
    for qmodel in query_models:
        qbase = re.split(r"[-./]", qmodel)[0]
        if len(qbase) >= 4 and qbase in normalized_listing and qmodel not in exact_models:
            same_family.append(qmodel)

    manufacturer = _manufacturer(query)
    manufacturer_match = bool(manufacturer and manufacturer in normalized_listing)

    query_features = _features(query)
    listing_features = _features(listing)
    matched_features = sorted(query_features & listing_features)
    missing_features = sorted(query_features - listing_features)

    query_tokens = _tokens(query)
    listing_tokens = _tokens(listing)
    token_overlap = len(query_tokens & listing_tokens) / max(1, len(query_tokens))

    score = 0.0
    if query_models:
        if exact_models:
            score += 52
        elif same_family:
            score += 28
        elif listing_models:
            score += 4
    else:
        score += 20 * token_overlap

    if manufacturer_match:
        score += 15
    elif manufacturer:
        score -= 8

    score += 18 * token_overlap
    if query_features:
        score += 15 * (len(matched_features) / len(query_features))
        score -= min(10, 2 * len(missing_features))

    if result.condition and "used" in result.condition.casefold():
        score -= 5
    score = round(max(0.0, min(100.0, score)), 1)

    if score >= 95:
        grade, recommendation = "Exact / Excellent", "Purchase candidate — verify stock, revision, and seller terms"
    elif score >= 85:
        grade, recommendation = "Strong", "Strong candidate — verify noted differences before ordering"
    elif score >= 70:
        grade, recommendation = "Good", "Review carefully — likely similar but not confirmed exact"
    elif score >= 50:
        grade, recommendation = "Review", "Do not order until specifications and model differences are resolved"
    else:
        grade, recommendation = "Poor", "Reject or use only as a search lead"

    differences: list[str] = []
    if query_models and not exact_models:
        differences.append("Exact requested model not shown")
    if manufacturer and not manufacturer_match:
        differences.append(f"Requested manufacturer {manufacturer} not confirmed")
    if same_family:
        differences.append("Same model family, but suffix/configuration differs")
    if missing_features:
        differences.append("Listing does not confirm: " + ", ".join(missing_features[:8]))

    result.match_score = score
    result.match_grade = grade
    result.exact_model_match = bool(exact_models)
    result.matched_features = "; ".join(matched_features) or "No specification features confirmed"
    result.missing_features = "; ".join(missing_features) or "None identified from listing text"
    result.differences = "; ".join(differences) or "No material text differences detected"
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
