from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class InputRecord:
    input_type: str
    label: str
    extracted_product_name: str = ""
    brand: str = ""
    category: str = ""
    confidence: float | None = None
    generated_queries: list[str] = field(default_factory=list)
    notes: str = ""
    source_url: str = ""
    retrieved_at: str = field(default_factory=now_iso)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["generated_queries"] = "; ".join(self.generated_queries)
        return row


@dataclass
class ProductResult:
    query: str
    input_source: str
    rank: int
    title: str
    seller: str = ""
    price: str = ""
    extracted_price: float | None = None
    delivery: str = ""
    rating: float | None = None
    reviews: int | None = None
    condition: str = ""
    snippet: str = ""
    product_link: str = ""
    seller_link: str = ""
    thumbnail: str = ""
    search_location: str = ""
    retrieved_at: str = field(default_factory=now_iso)
    raw_source: str = "Google Shopping / SerpApi"
    match_score: float | None = None
    match_grade: str = ""
    match_confidence: str = ""
    match_profile: str = ""
    score_breakdown: str = ""
    best_match: bool = False
    exact_model_match: bool = False
    matched_features: str = ""
    missing_features: str = ""
    differences: str = ""
    recommendation: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StoreResult:
    query: str
    rank: int
    title: str
    store_type: str = ""
    address: str = ""
    phone: str = ""
    rating: float | None = None
    reviews: int | None = None
    hours: str = ""
    website: str = ""
    directions: str = ""
    maps_link: str = ""
    search_location: str = ""
    retrieved_at: str = field(default_factory=now_iso)
    raw_source: str = "Google Maps / SerpApi"

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpecDocument:
    query: str
    rank: int
    title: str
    document_type: str = "Spec sheet"
    source_domain: str = ""
    link: str = ""
    displayed_link: str = ""
    snippet: str = ""
    official_source: bool = False
    pdf_link: bool = False
    match_confidence: str = "Possible"
    retrieved_at: str = field(default_factory=now_iso)
    raw_source: str = "Google Search / SerpApi"

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManufacturerResult:
    query: str
    rank: int
    title: str
    manufacturer: str = ""
    source_domain: str = ""
    page_type: str = "Product page"
    link: str = ""
    snippet: str = ""
    official_source: bool = False
    exact_model_mentioned: bool = False
    source_confidence: str = "Possible"
    retrieved_at: str = field(default_factory=now_iso)
    raw_source: str = "Google Search / SerpApi"

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OmniSearchResult:
    query: str
    rank: int
    title: str
    source_name: str = ""
    source_domain: str = ""
    source_type: str = "General web"
    result_kind: str = "Product page"
    link: str = ""
    snippet: str = ""
    price: str = ""
    extracted_price: float | None = None
    delivery: str = ""
    location: str = ""
    official_source: bool = False
    authorized_distributor: bool = False
    exact_model_mentioned: bool = False
    document_pdf: bool = False
    legacy_or_discontinued: bool = False
    source_reliability: float = 0.0
    match_score: float = 0.0
    overall_score: float = 0.0
    verification_status: str = "Needs review"
    evidence: str = ""
    raw_source: str = "OmniSearch"
    retrieved_at: str = field(default_factory=now_iso)

    def to_row(self) -> dict[str, Any]:
        return asdict(self)
