from __future__ import annotations

import hmac
import json
import time
from typing import Iterable
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from product_finder.config import AppConfig, load_config
from product_finder.models import InputRecord, ManufacturerResult, OmniSearchResult, ProductResult, SpecDocument, StoreResult
from product_finder.matching import rank_product_matches
from product_finder.search import (
    google_lens_queries_from_url,
    google_maps_nearby_stores,
    google_manufacturer_search,
    google_shopping_search,
    google_spec_sheet_search,
    google_everywhere_search,
    modular_everywhere_search,
    omni_from_existing,
    rank_omni_results,
)
from product_finder.spreadsheet import create_product_workbook_bytes
from product_finder.purchase_tracker import extract_purchase_candidates, create_purchase_tracker_bytes
from product_finder.rfq_builder import extract_rfq_items, build_rfq_email, create_rfq_workbook
from product_finder.utils import clean_text, unique_keep_order
from product_finder.vision import analyze_uploaded_image
from product_finder.exact_image_match import build_visual_fingerprint, visually_verify_candidates
from product_finder.spec_compare import (
    compare_spec_documents, comparison_rows, create_spec_comparison_workbook, extract_spec_document,
)
from product_finder.project_intelligence import (
    consolidate_items, create_project_backup, create_project_workbook,
    create_submittal_zip, extract_schedule_items, load_project_backup,
)
from product_finder.knowledge_base import ProductKnowledgeBase
from product_finder.research_agent import ResearchAgent
from product_finder.observability import (
    clear_error_log, diagnostics_snapshot, recent_errors, recent_events,
    record_event, record_exception, run_health_checks,
)
from product_finder.procurement_controls import (
    Requirement, append_audit, build_review_queue, classify_document,
    compare_requirements, create_procurement_control_workbook, data_health_checks,
    group_duplicate_offers, landed_cost, normalize_vendor, package_completeness,
    vendor_score, normalize_offer_dataframe, OFFER_BASE_COLUMNS,
)


APP_TITLE = "Product Hunter Pro"
APP_VERSION = "29.0"
EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _secret_getter(name: str, default: str = "") -> object:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def _split_lines(text: str) -> list[str]:
    return unique_keep_order(line.strip() for line in text.splitlines() if line.strip())


def _records_to_df(records: Iterable[object]) -> pd.DataFrame:
    rows = []
    for item in records:
        to_row = getattr(item, "to_row", None)
        rows.append(to_row() if callable(to_row) else item)
    return pd.DataFrame(rows)


def _valid_public_image_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and len(value) <= 2048


def _make_input_records_from_text(text_queries: list[str]) -> list[InputRecord]:
    return [
        InputRecord(
            input_type="text",
            label=query,
            extracted_product_name=query,
            generated_queries=[query],
            notes="User-entered search query.",
        )
        for query in text_queries
    ]


def _build_search_jobs(records: list[InputRecord], max_queries_per_input: int) -> list[tuple[str, str]]:
    jobs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        queries = record.generated_queries[:max_queries_per_input]
        if not queries and record.extracted_product_name:
            queries = [record.extracted_product_name]
        if not queries and record.input_type == "text" and record.label:
            queries = [record.label]
        for query in queries:
            cleaned = clean_text(query)[:300]
            if not cleaned:
                continue
            key = (cleaned.lower(), record.label.lower())
            if key in seen:
                continue
            seen.add(key)
            jobs.append((cleaned, record.label))
    return jobs


def _dedupe_products(results: list[ProductResult]) -> list[ProductResult]:
    output: list[ProductResult] = []
    seen: set[tuple[str, ...]] = set()
    for result in results:
        if result.product_link:
            key = ("link", result.product_link.strip().lower())
        else:
            key = (
                "details",
                result.title.strip().lower(),
                result.seller.strip().lower(),
                result.price.strip().lower(),
            )
        if key in seen:
            continue
        seen.add(key)
        output.append(result)
    return output


def _dedupe_stores(results: list[StoreResult]) -> list[StoreResult]:
    output: list[StoreResult] = []
    seen: set[tuple[str, ...]] = set()
    for result in results:
        key = (
            result.title.strip().lower(),
            result.address.strip().lower(),
            result.phone.strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(result)
    return output




def _route_omni_results(results: list[OmniSearchResult]) -> tuple[list[ProductResult], list[StoreResult], list[SpecDocument], list[ManufacturerResult]]:
    """Route normalized SearXNG/OmniSearch records into the dedicated app views.

    OmniSearch remains the source of truth. These derived records let users work with
    retailer, supplier, document, and manufacturer-focused tables without requiring
    SerpApi-specific result objects.
    """
    products: list[ProductResult] = []
    stores: list[StoreResult] = []
    documents: list[SpecDocument] = []
    manufacturers: list[ManufacturerResult] = []
    for item in results:
        source_type = (item.source_type or "").casefold()
        result_kind = (item.result_kind or "").casefold()
        is_document = item.document_pdf or "document" in source_type or "pdf" in result_kind or any(
            token in result_kind for token in ("manual", "spec", "submittal", "warranty", "cad", "bim", "revit")
        )
        is_manufacturer = item.official_source or "official manufacturer" in source_type
        is_retail = any(token in source_type for token in ("retailer", "marketplace", "distributor"))
        is_local = "local supplier" in source_type or "nearby" in result_kind

        if is_retail:
            products.append(ProductResult(
                query=item.query, input_source="OmniSearch", rank=item.rank, title=item.title,
                seller=item.source_name or item.source_domain, price=item.price,
                extracted_price=item.extracted_price, delivery=item.delivery, snippet=item.snippet,
                product_link=item.link, raw_source=item.raw_source, match_score=item.overall_score,
                match_grade=item.verification_status, match_confidence="Evidence-backed web result",
                match_profile="OmniSearch", score_breakdown=item.evidence,
                best_match=False, exact_model_match=item.exact_model_mentioned,
                recommendation="Verify price, stock, shipping, and exact configuration on the source page.",
            ))
        if is_local:
            stores.append(StoreResult(
                query=item.query, rank=item.rank, title=item.source_name or item.title,
                store_type="Local supplier lead", address=item.location, website=item.link,
                maps_link=item.link, raw_source=item.raw_source,
            ))
        if is_document:
            doc_type = "Technical document"
            text = f"{item.title} {item.result_kind}".casefold()
            for label, tokens in (("Spec sheet", ("spec", "datasheet")), ("Submittal", ("submittal",)),
                                  ("Installation manual", ("installation", "install manual")),
                                  ("Warranty", ("warranty",)), ("CAD / BIM", ("cad", "bim", "revit", "dwg")),
                                  ("Parts / service", ("parts", "service manual"))):
                if any(token in text for token in tokens):
                    doc_type = label
                    break
            documents.append(SpecDocument(
                query=item.query, rank=item.rank, title=item.title, document_type=doc_type,
                source_domain=item.source_domain, link=item.link, displayed_link=item.link,
                snippet=item.snippet, official_source=item.official_source,
                pdf_link=item.document_pdf,
                match_confidence="Exact" if item.exact_model_mentioned else "Likely" if item.overall_score >= 70 else "Possible",
                raw_source=item.raw_source,
            ))
        if is_manufacturer:
            manufacturers.append(ManufacturerResult(
                query=item.query, rank=item.rank, title=item.title,
                manufacturer=item.source_name, source_domain=item.source_domain,
                page_type=item.result_kind, link=item.link, snippet=item.snippet,
                official_source=True, exact_model_mentioned=item.exact_model_mentioned,
                source_confidence="Verified exact source" if item.exact_model_mentioned else "Likely official source",
                raw_source=item.raw_source,
            ))
    return products, stores, documents, manufacturers


def _password_gate(config: AppConfig) -> bool:
    if not config.app_password:
        return True
    if st.session_state.get("product_hunter_authenticated") is True:
        with st.sidebar:
            st.caption("Protected session")
            if st.button("Sign out", use_container_width=True):
                st.session_state.pop("product_hunter_authenticated", None)
                st.rerun()
        return True

    st.title("Product Hunter")
    st.write("Enter the app password to continue.")
    with st.form("access_form", clear_on_submit=True):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Open app", type="primary", use_container_width=True)
    if submitted:
        if hmac.compare_digest(password, config.app_password):
            st.session_state["product_hunter_authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.caption("The password protects access to the hosted API keys and is not written to the spreadsheet.")
    return False


def _resolve_api_keys(config: AppConfig) -> tuple[str, str, str, str]:
    server_keys_allowed = bool(config.app_password) or config.allow_public_with_server_keys
    serpapi_api_key = config.serpapi_api_key if server_keys_allowed else ""
    brave_api_key = config.brave_search_api_key if server_keys_allowed else ""
    searxng_url = config.searxng_url
    openai_api_key = config.openai_api_key if server_keys_allowed else ""

    with st.sidebar:
        st.header("Service status")
        if searxng_url:
            st.success("Dynamic discovery search: SearXNG configured")
            if st.button("Test SearXNG connection", use_container_width=True):
                from product_finder.search import searxng_health_check
                ok, message = searxng_health_check(base_url=searxng_url, language=config.language)
                (st.success if ok else st.error)(message)
        elif serpapi_api_key:
            st.success("Web search: SerpApi compatibility mode")
        else:
            st.warning("Web search provider missing. Configure SEARXNG_URL.")

        if serpapi_api_key:
            st.info("Google Shopping, Maps, and Lens compatibility: ready")
        else:
            st.caption("Google Shopping, Maps, and Lens are disabled without SerpApi. Dynamic manufacturer discovery and web/document search still work through SearXNG.")

        if config.openai_api_key and not server_keys_allowed:
            st.warning("Hosted image-recognition key is disabled by the access policy.")
        elif openai_api_key:
            st.success("Uploaded-image recognition: ready")
        else:
            st.info("Uploaded-image recognition: API key missing")

        if config.allow_user_api_keys:
            with st.expander("Use different API settings"):
                user_searxng_url = st.text_input("SearXNG URL", value="", help="Example: https://search.example.com")
                user_brave_key = ""  # Brave is optional and no longer shown in the normal setup.
                user_serpapi_key = st.text_input("SerpApi key (optional compatibility)", type="password")
                user_openai_key = st.text_input("OpenAI API key", type="password")
                if user_searxng_url.strip(): searxng_url = user_searxng_url.strip().rstrip("/")
                if user_brave_key.strip(): brave_api_key = user_brave_key.strip()
                if user_serpapi_key.strip(): serpapi_api_key = user_serpapi_key.strip()
                if user_openai_key.strip(): openai_api_key = user_openai_key.strip()

    return serpapi_api_key, openai_api_key, brave_api_key, searxng_url


def _show_input_records(records: list[InputRecord]) -> None:
    st.subheader("Recognized inputs and search terms")
    dataframe = _records_to_df(records)
    visible = [
        "input_type",
        "label",
        "extracted_product_name",
        "brand",
        "category",
        "confidence",
        "generated_queries",
        "notes",
    ]
    st.dataframe(dataframe[[column for column in visible if column in dataframe.columns]], use_container_width=True, hide_index=True)


def _show_product_results(results: list[ProductResult]) -> None:
    st.subheader("Retailer and distributor offers")
    if not results:
        st.info("No retailer or distributor pages were returned.")
        return
    dataframe = _records_to_df(results)
    columns = [
        "thumbnail",
        "best_match",
        "match_score",
        "match_grade",
        "match_confidence",
        "match_profile",
        "exact_model_match",
        "title",
        "seller",
        "price",
        "delivery",
        "differences",
        "score_breakdown",
        "recommendation",
        "query",
        "product_link",
    ]
    st.dataframe(
        dataframe[[column for column in columns if column in dataframe.columns]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "thumbnail": st.column_config.ImageColumn("Image"),
            "best_match": st.column_config.CheckboxColumn("Best match"),
            "match_score": st.column_config.ProgressColumn("Match", min_value=0, max_value=100, format="%.1f%%"),
            "exact_model_match": st.column_config.CheckboxColumn("Exact model"),
            "product_link": st.column_config.LinkColumn("Retailer page", display_text="Open listing"),
            "rating": st.column_config.NumberColumn("Rating", format="%.1f"),
            "reviews": st.column_config.NumberColumn("Reviews", format="%d"),
        },
    )


def _show_store_results(results: list[StoreResult]) -> None:
    st.subheader("Local supplier leads")
    if not results:
        st.info("No local supplier leads were returned. General web search cannot guarantee nearby inventory.")
        return
    dataframe = _records_to_df(results)
    columns = [
        "title",
        "store_type",
        "address",
        "phone",
        "rating",
        "reviews",
        "hours",
        "website",
        "directions",
        "maps_link",
        "query",
    ]
    st.dataframe(
        dataframe[[column for column in columns if column in dataframe.columns]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "website": st.column_config.LinkColumn("Website", display_text="Open"),
            "directions": st.column_config.LinkColumn("Directions", display_text="Directions"),
            "maps_link": st.column_config.LinkColumn("Map", display_text="Open map"),
            "rating": st.column_config.NumberColumn("Rating", format="%.1f"),
            "reviews": st.column_config.NumberColumn("Reviews", format="%d"),
        },
    )



def _show_spec_documents(results: list[SpecDocument]) -> None:
    st.subheader("Technical documentation")
    if not results:
        st.info("No spec sheets or technical documents were returned, or document search was disabled.")
        return
    dataframe = _records_to_df(results)
    columns = ["title", "document_type", "source_domain", "match_confidence", "official_source", "pdf_link", "link", "query"]
    st.dataframe(
        dataframe[[column for column in columns if column in dataframe.columns]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "link": st.column_config.LinkColumn("Document", display_text="Open document"),
            "official_source": st.column_config.CheckboxColumn("Likely official"),
            "pdf_link": st.column_config.CheckboxColumn("PDF"),
        },
    )



def _show_manufacturer_results(results: list[ManufacturerResult]) -> None:
    st.subheader("Official manufacturer evidence")
    if not results:
        st.info("No likely manufacturer pages were returned, or manufacturer search was disabled.")
        return
    dataframe = _records_to_df(results)
    columns = ["title", "manufacturer", "source_domain", "page_type", "official_source", "exact_model_mentioned", "source_confidence", "link", "query"]
    st.dataframe(
        dataframe[[column for column in columns if column in dataframe.columns]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "link": st.column_config.LinkColumn("Manufacturer page", display_text="Open source"),
            "official_source": st.column_config.CheckboxColumn("Likely official"),
            "exact_model_mentioned": st.column_config.CheckboxColumn("Exact model found"),
        },
    )

def _show_omni_results(results: list[OmniSearchResult]) -> None:
    st.subheader("Research results")
    if not results:
        st.markdown("""<div class="empty-state"><div style="font-size:1.6rem">⌕</div><h3>No research results yet</h3><div>Run a product research query or broaden the source filters.</div></div>""", unsafe_allow_html=True)
        return
    df = _records_to_df(results)
    exact_count = int(df.get("exact_model_mentioned", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not df.empty else 0
    official_count = int(df.get("official_source", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not df.empty else 0
    doc_count = int(df.get("document_pdf", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not df.empty else 0
    high_conf = int((pd.to_numeric(df.get("overall_score", pd.Series(dtype=float)), errors="coerce").fillna(0) >= 85).sum()) if not df.empty else 0
    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Sources", len(df))
    sm2.metric("Exact-model evidence", exact_count)
    sm3.metric("Official sources", official_count)
    sm4.metric("High-confidence", high_conf)
    if not df.empty and "overall_score" in df.columns:
        top_idx = pd.to_numeric(df["overall_score"], errors="coerce").fillna(-1).idxmax()
        top = df.loc[top_idx]
        st.markdown(f"""<div class="result-highlight"><strong>Top evidence:</strong> {clean_text(str(top.get('title', '')))}<br><span>{clean_text(str(top.get('source_type', 'Source')))} · score {float(top.get('overall_score') or 0):.0f}% · {clean_text(str(top.get('verification_status', 'Review')))}</span></div>""", unsafe_allow_html=True)
    source_options = sorted(x for x in df.get("source_type", pd.Series(dtype=str)).dropna().unique().tolist() if x)
    kb = ProductKnowledgeBase()
    saved_views = kb.list_views()
    preset_names = ["Current filters"] + [v["view_name"] for v in saved_views]
    preset = st.selectbox("Saved view", preset_names, key="omni_saved_view")
    preset_filters = next((v.get("filters", {}) for v in saved_views if v["view_name"] == preset), {})

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    selected = c1.multiselect(
        "Source types", source_options,
        default=[x for x in preset_filters.get("source_types", source_options) if x in source_options] or source_options,
        key=f"omni_source_filter_{preset}",
    )
    exact_only = c2.checkbox("Exact model", value=bool(preset_filters.get("exact_only", False)), key=f"omni_exact_only_{preset}")
    official_only = c3.checkbox("Official", value=bool(preset_filters.get("official_only", False)), key=f"omni_official_only_{preset}")
    min_score = c4.number_input("Min score", min_value=0, max_value=100, value=int(preset_filters.get("min_score", 0)), step=5, key=f"omni_min_score_{preset}")
    view = df.copy()
    if selected:
        view = view[view["source_type"].isin(selected)]
    if exact_only and "exact_model_mentioned" in view.columns:
        view = view[view["exact_model_mentioned"] == True]  # noqa: E712
    if official_only and "official_source" in view.columns:
        view = view[view["official_source"] == True]  # noqa: E712
    if "overall_score" in view.columns:
        view = view[pd.to_numeric(view["overall_score"], errors="coerce").fillna(0) >= min_score]

    save_col, export_col, count_col = st.columns([1, 1, 2])
    with save_col:
        with st.popover("Save view"):
            view_name = st.text_input("View name", key="omni_new_view_name")
            if st.button("Save filters", key="omni_save_view_button", use_container_width=True):
                kb.save_view(view_name, {"source_types": selected, "exact_only": exact_only, "official_only": official_only, "min_score": min_score})
                st.success("Saved view.")
                st.rerun()
    with export_col:
        st.download_button(
            "Export filtered CSV",
            data=view.to_csv(index=False).encode("utf-8-sig"),
            file_name="Product_Hunter_Filtered_Research.csv",
            mime="text/csv",
            use_container_width=True,
        )
    count_col.caption(f"Showing {len(view)} of {len(df)} normalized sources")

    cols = ["rank", "overall_score", "verification_status", "title", "source_name", "source_type", "result_kind", "price", "delivery", "official_source", "authorized_distributor", "exact_model_mentioned", "legacy_or_discontinued", "source_reliability", "evidence", "link", "query"]
    st.dataframe(view[[c for c in cols if c in view.columns]], use_container_width=True, hide_index=True, column_config={
        "overall_score": st.column_config.ProgressColumn("Overall", min_value=0, max_value=100, format="%.1f%%"),
        "source_reliability": st.column_config.ProgressColumn("Source trust", min_value=0, max_value=100, format="%.0f%%"),
        "official_source": st.column_config.CheckboxColumn("Official"),
        "authorized_distributor": st.column_config.CheckboxColumn("Distributor"),
        "exact_model_mentioned": st.column_config.CheckboxColumn("Exact model"),
        "legacy_or_discontinued": st.column_config.CheckboxColumn("Legacy"),
        "link": st.column_config.LinkColumn("Open source", display_text="Open"),
    }, height=520)


def _render_purchase_tracker() -> None:
    st.markdown("""<div class="hero"><h1>Purchase Tracker Builder</h1><p>Import a Product Hunter Excel report, select retailer links, and generate a separate purchasing workbook that tracks approvals, orders, costs, delivery, and received quantities.</p></div>""", unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "Upload the original Product Hunter Excel file",
        type=["xlsx"],
        help="The app reads retailer links from Product Results, Products, Retailers, or other sheets containing URLs.",
        key="purchase_tracker_source",
    )
    direct_links = st.text_area(
        "Optional retailer links to add manually, one per line",
        placeholder="https://retailer.com/product-page",
        key="purchase_tracker_links",
    )

    candidates: list[dict] = []
    if uploaded is not None:
        try:
            candidates = extract_purchase_candidates(uploaded.getvalue())
            st.success(f"Found {len(candidates)} unique purchasable link(s) in the workbook.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"The workbook could not be read: {exc}")
            return

    existing = {str(row.get("product_link", "")).casefold() for row in candidates}
    for link in _split_lines(direct_links):
        if _valid_public_image_url(link) and link.casefold() not in existing:
            existing.add(link.casefold())
            candidates.append({
                "select": True,
                "product": "",
                "model_or_search": "",
                "retailer": "",
                "unit_price": 0.0,
                "quantity": 1,
                "product_link": link,
                "image_url": "",
                "source_sheet": "Manual link",
                "source_row": "",
            })

    if not candidates:
        st.info("Upload an Excel report or paste at least one retailer product link.")
        return

    st.subheader("Choose products to track")
    table = pd.DataFrame(candidates)
    edited = st.data_editor(
        table,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "select": st.column_config.CheckboxColumn("Add", default=False),
            "product_link": st.column_config.LinkColumn("Retailer link", display_text="Open"),
            "image_url": st.column_config.LinkColumn("Image", display_text="Open image"),
            "unit_price": st.column_config.NumberColumn("Unit price", format="$%.2f", min_value=0.0),
            "quantity": st.column_config.NumberColumn("Quantity", min_value=1, step=1),
            "source_row": st.column_config.NumberColumn("Source row", disabled=True),
        },
        disabled=["source_sheet", "source_row"],
        key="purchase_tracker_editor",
    )

    selected = edited[edited["select"] == True].to_dict("records")  # noqa: E712
    st.caption(f"{len(selected)} item(s) selected.")

    with st.form("purchase_tracker_details"):
        left, right = st.columns(2)
        with left:
            tracker_name = st.text_input("Tracker name", placeholder="Plumbing Fixtures Purchase Tracker")
            project_name = st.text_input("Project / job name")
        with right:
            buyer = st.text_input("Buyer / purchaser")
            notes = st.text_area("Tracker notes", height=90)
        build_tracker = st.form_submit_button("Build purchase tracker Excel", type="primary", use_container_width=True)

    if not build_tracker:
        return
    if not selected:
        st.error("Select at least one product link in the Add column.")
        return

    filename, tracker_bytes = create_purchase_tracker_bytes(
        selected,
        tracker_name=tracker_name,
        project_name=project_name,
        buyer=buyer,
        notes=notes,
    )
    st.success(f"Purchase tracker ready: **{filename}**")
    st.download_button(
        f"Download {filename}",
        data=tracker_bytes,
        file_name=filename,
        mime=EXCEL_MIME,
        type="primary",
        use_container_width=True,
        on_click="ignore",
    )


def _default_project() -> dict:
    return {
        "project_name": "", "project_number": "", "client": "", "buyer": "",
        "equipment": [], "documents": [], "quotes": [],
        "preferences": {
            "require_exact_model": True, "prefer_official_manufacturer": True,
            "reject_refurbished": True, "allow_equivalents": False,
            "minimum_match_score": 85, "priority": "Best specification match",
        },
    }


def _render_project_intelligence(openai_api_key: str, model: str) -> None:
    st.markdown("""<div class="hero"><h1>Project Intelligence</h1><p>Extract schedules, consolidate equipment, review project rules, compare quotes, and export a project workbook or submittal package.</p></div>""", unsafe_allow_html=True)
    if "project_v7" not in st.session_state:
        st.session_state.project_v7 = _default_project()
    project = st.session_state.project_v7

    restore = st.file_uploader("Restore a Product Hunter project backup", type=["json"], key="project_restore")
    if restore is not None and st.button("Restore project", use_container_width=True):
        try:
            st.session_state.project_v7 = load_project_backup(restore.getvalue())
            st.success("Project restored."); st.rerun()
        except Exception as exc:
            st.error(f"Could not restore project: {exc}")

    a,b,c,d = st.columns(4)
    project["project_name"] = a.text_input("Project name", value=project.get("project_name", ""))
    project["project_number"] = b.text_input("Project number", value=project.get("project_number", ""))
    project["client"] = c.text_input("Client / owner", value=project.get("client", ""))
    project["buyer"] = d.text_input("Buyer", value=project.get("buyer", ""))

    st.markdown("### 1. Import schedules")
    uploads = st.file_uploader("Upload schedule PDFs, images, text, or CSV files", type=["pdf","png","jpg","jpeg","webp","txt","csv"], accept_multiple_files=True, key="project_docs")
    if st.button("Extract equipment from uploaded schedules", type="primary", use_container_width=True):
        if not uploads: st.error("Upload at least one schedule file.")
        elif not openai_api_key: st.error("OpenAI API key is required for schedule extraction.")
        else:
            extracted=[]
            progress=st.progress(0)
            for i,f in enumerate(uploads,1):
                try:
                    extracted.extend(extract_schedule_items(file_bytes=f.getvalue(), filename=f.name, mime_type=f.type or "", openai_api_key=openai_api_key, model=model))
                except Exception as exc:
                    st.warning(f"{f.name}: {exc}")
                progress.progress(i/len(uploads))
            project["equipment"] = consolidate_items(project.get("equipment", []) + [x.to_row() for x in extracted])
            project["documents"] = list(dict.fromkeys(project.get("documents", []) + [f.name for f in uploads]))
            st.success(f"Added {len(extracted)} extracted row(s); consolidated register has {len(project['equipment'])} product(s).")

    st.markdown("### 2. Review equipment register")
    equipment_df = pd.DataFrame(project.get("equipment", []))
    required_cols = ["item_tag","division","manufacturer","model","description","quantity","location","source_file","source_page","status","approved_listing","notes"]
    for col in required_cols:
        if col not in equipment_df: equipment_df[col] = [] if equipment_df.empty else ""
    edited = st.data_editor(equipment_df[required_cols], num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "quantity": st.column_config.NumberColumn("Quantity", min_value=1, step=1),
            "approved_listing": st.column_config.LinkColumn("Approved listing"),
            "status": st.column_config.SelectboxColumn("Status", options=["Needs search","Needs review","Approved","Rejected","Alternate","Submitted","Ordered","Received","Installed"]),
        }, key="project_equipment_editor")
    project["equipment"] = edited.fillna("").to_dict("records")
    x,y = st.columns(2)
    if x.button("Consolidate duplicates", use_container_width=True):
        project["equipment"] = consolidate_items(project["equipment"]); st.rerun()
    if y.button("Send equipment to Product Search", use_container_width=True):
        queries=[]
        for r in project["equipment"]:
            q=" ".join(str(r.get(k,"")) for k in ("manufacturer","model","description") if r.get(k)).strip()
            if q: queries.append(q)
        st.session_state["project_search_queries"]="\n".join(dict.fromkeys(queries)); st.success("Search terms prepared. Switch to Product Search and paste/use the prepared list.")

    st.markdown("### 3. Procurement rules")
    pref=project.get("preferences", {})
    p1,p2,p3,p4=st.columns(4)
    pref["require_exact_model"]=p1.checkbox("Require exact model", value=bool(pref.get("require_exact_model",True)))
    pref["prefer_official_manufacturer"]=p2.checkbox("Prefer official source", value=bool(pref.get("prefer_official_manufacturer",True)))
    pref["reject_refurbished"]=p3.checkbox("Reject refurbished", value=bool(pref.get("reject_refurbished",True)))
    pref["allow_equivalents"]=p4.checkbox("Allow equivalents", value=bool(pref.get("allow_equivalents",False)))
    pref["minimum_match_score"]=st.slider("Minimum acceptable match score", 0, 100, int(pref.get("minimum_match_score",85)))
    pref["priority"]=st.selectbox("Purchasing priority", ["Best specification match","Lowest total price","Fastest delivery","Local pickup","Preferred vendor"], index=0)
    project["preferences"]=pref

    st.markdown("### 4. Quote comparison")
    quote_files=st.file_uploader("Upload vendor quote Excel or CSV files", type=["xlsx","csv"], accept_multiple_files=True, key="quote_uploads")
    quote_rows=[]
    for f in quote_files or []:
        try:
            frame = pd.read_csv(f) if f.name.lower().endswith('.csv') else pd.read_excel(f)
            frame["source_quote"] = f.name
            quote_rows.extend(frame.astype(object).where(pd.notna(frame), "").to_dict("records"))
        except Exception as exc: st.warning(f"{f.name}: {exc}")
    if quote_rows:
        qdf=pd.DataFrame(quote_rows)
        st.dataframe(qdf, use_container_width=True, hide_index=True)
        project["quotes"]=quote_rows
        numeric=qdf.select_dtypes(include="number")
        if not numeric.empty:
            st.caption("Numeric quote summary")
            st.dataframe(numeric.describe().T, use_container_width=True)

    st.markdown("### 5. Export and backup")
    e1,e2,e3=st.columns(3)
    backup_name, backup_bytes=create_project_backup(project)
    e1.download_button("Download project backup", backup_bytes, file_name=backup_name, mime="application/json", use_container_width=True)
    workbook_name, workbook_bytes=create_project_workbook(project)
    e2.download_button("Download project Excel", workbook_bytes, file_name=workbook_name, mime=EXCEL_MIME, use_container_width=True)
    doc_text=st.text_area("Optional spec/document links for submittal ZIP, one per line", key="submittal_links")
    docs=[{"title":f"Document {i}","link":u} for i,u in enumerate(_split_lines(doc_text),1) if u.startswith(("http://","https://"))]
    zip_name, zip_bytes=create_submittal_zip(project, docs)
    e3.download_button("Download submittal ZIP", zip_bytes, file_name=zip_name, mime="application/zip", use_container_width=True)

    st.session_state.project_v7=project


def _render_procurement_control_center() -> None:
    st.markdown("""<div class="hero"><h1>Procurement Control Center</h1><p>Define hard requirements, compare offers, calculate delivered cost, group duplicates, validate documentation, create PO drafts, and focus attention on unresolved risks.</p></div>""", unsafe_allow_html=True)
    if "control_v8" not in st.session_state:
        st.session_state.control_v8 = {"project_name":"", "products":[], "requirements":[], "documents":[], "audit":[], "receiving":[]}
    data=st.session_state.control_v8
    data["project_name"]=st.text_input("Project / report name", value=data.get("project_name", ""), placeholder="Hospital Plumbing Procurement")

    tabs=st.tabs(["Products & costs","Requirements","Review dashboard","Documents","Vendors & receiving","Export"])
    with tabs[0]:
        st.markdown("### Import or enter product offers")
        upload=st.file_uploader("Upload Product Hunter Excel/CSV or a vendor offer table", type=["xlsx","csv"], key="control_products")
        if upload is not None and st.button("Import offer table", use_container_width=True):
            try:
                frame=pd.read_csv(upload) if upload.name.lower().endswith('.csv') else pd.read_excel(upload, sheet_name=None)
                if isinstance(frame,dict):
                    preferred=next((v for k,v in frame.items() if k in {"Product Results","Products","Purchase List","Equipment Register"}), next(iter(frame.values())))
                    frame=preferred
                data["products"]=frame.astype(object).where(pd.notna(frame),"").to_dict("records")
                append_audit(data["audit"],"Imported offers",details=f"{len(data['products'])} rows from {upload.name}")
                st.success(f"Imported {len(data['products'])} offer rows.")
            except Exception as exc: st.error(f"Could not import: {exc}")
        products=normalize_offer_dataframe(pd.DataFrame(data.get("products",[])))
        edited=st.data_editor(products,num_rows="dynamic",hide_index=True,use_container_width=True,
            column_config={
                "product_link":st.column_config.LinkColumn("Product link"),
                "quantity":st.column_config.NumberColumn("Qty",min_value=0,step=1),
                "unit_price":st.column_config.NumberColumn("Unit price",format="$%.2f"),
                "shipping":st.column_config.NumberColumn("Shipping",format="$%.2f"),
                "tax_rate":st.column_config.NumberColumn("Tax rate",format="%.3f"),
                "discount":st.column_config.NumberColumn("Discount",format="$%.2f"),
                "accessory_cost":st.column_config.NumberColumn("Accessory cost",format="$%.2f"),
                "match_score":st.column_config.NumberColumn("Match %",min_value=0,max_value=100),
                "status":st.column_config.SelectboxColumn("Status",options=["Needs review","Approved","Rejected","Alternate","Selected","Ordered","Received","Installed"]),
                "approved":st.column_config.CheckboxColumn("Approved"),
                "exact_model_match":st.column_config.CheckboxColumn("Exact model"),
                "authorized_distributor":st.column_config.CheckboxColumn("Authorized distributor"),
            },key="control_product_editor")
        data["products"]=normalize_offer_dataframe(edited).to_dict("records")
        enriched=[]
        for row in data["products"]:
            calc=landed_cost(float(row.get("unit_price") or 0),float(row.get("quantity") or 1),float(row.get("shipping") or 0),float(row.get("tax_rate") or 0),float(row.get("discount") or 0),float(row.get("accessory_cost") or 0))
            out=dict(row); out.update(calc); out["normalized_vendor"]=normalize_vendor(str(row.get("seller") or ""),str(row.get("product_link") or "")); out["vendor_score"]=vendor_score(out); enriched.append(out)
        if enriched:
            st.markdown("#### Delivered-cost comparison")
            st.dataframe(pd.DataFrame(enriched)[[c for c in ["title","normalized_vendor","quantity","unit_price","shipping","tax","delivered_total","match_score","vendor_score","status"] if c in pd.DataFrame(enriched)]].sort_values(["delivered_total","match_score"],ascending=[True,False]),use_container_width=True,hide_index=True)
            groups=group_duplicate_offers(enriched)
            st.caption(f"Grouped into {len(groups)} unique product group(s) from {len(enriched)} offer(s).")

    with tabs[1]:
        st.markdown("### Hard requirements and preferences")
        req_df=pd.DataFrame(data.get("requirements",[]))
        for c in ["attribute","required_value","importance","weight"]:
            if c not in req_df: req_df[c]=[] if req_df.empty else ""
        req_edit=st.data_editor(req_df[["attribute","required_value","importance","weight"]],num_rows="dynamic",hide_index=True,use_container_width=True,
            column_config={"importance":st.column_config.SelectboxColumn("Importance",options=["Required","Preferred","Optional","Ignore"]),"weight":st.column_config.NumberColumn("Weight",min_value=0.1,max_value=10.0,step=0.5)},key="requirements_editor")
        data["requirements"]=req_edit.fillna("").to_dict("records")
        components=st.text_area("Required package components, one per line",placeholder="sink\nfaucet\nbubbler\nangle stops\nstrainer\np-trap",key="package_components")
        if data["products"] and data["requirements"]:
            evaluated=[]
            for row in data["products"]:
                comps,reject,score=compare_requirements(data["requirements"],row)
                package=package_completeness(_split_lines(components)," ".join(str(v) for v in row.values()))
                evaluated.append({"title":row.get("title"),"seller":row.get("seller"),"requirements_score":score,"hard_reject":reject,"package_complete":package["percent"],"missing_components":"; ".join(package["missing"]),"comparison":" | ".join(f"{c.attribute}: {c.status}" for c in comps)})
            st.markdown("#### Side-by-side compliance results")
            st.dataframe(pd.DataFrame(evaluated).sort_values(["hard_reject","requirements_score"],ascending=[True,False]),use_container_width=True,hide_index=True)

    with tabs[2]:
        st.markdown("### Missing-information and risk queue")
        minimum=st.slider("Minimum acceptable match score",0,100,85,key="control_minimum")
        review=build_review_queue(data["products"],minimum)
        health=data_health_checks(data["products"],data.get("documents",[]))
        a,b,c=st.columns(3); a.metric("Offers",len(data["products"])); b.metric("Needs review",len(review)); c.metric("Data-health issues",len(health))
        if review: st.dataframe(pd.DataFrame(review),use_container_width=True,hide_index=True)
        else: st.success("No offers currently meet the review-queue rules.")
        if health:
            st.markdown("#### Data-health checks")
            st.dataframe(pd.DataFrame(health),use_container_width=True,hide_index=True)

    with tabs[3]:
        st.markdown("### Document classification and validation register")
        doc_df=pd.DataFrame(data.get("documents",[]))
        for c in ["title","link","requested_model","document_type","opens","is_pdf","model_confirmed","notes"]:
            if c not in doc_df: doc_df[c]=[] if doc_df.empty else ""
        doc_edit=st.data_editor(doc_df,num_rows="dynamic",hide_index=True,use_container_width=True,column_config={"link":st.column_config.LinkColumn("Link")},key="document_editor")
        data["documents"]=doc_edit.fillna("").to_dict("records")
        if st.button("Classify documents",use_container_width=True):
            for row in data["documents"]: row["document_type"]=classify_document(str(row.get("title") or ""),str(row.get("link") or ""))
            append_audit(data["audit"],"Classified documents",details=f"{len(data['documents'])} documents")
            st.rerun()
        st.caption("Full online link validation can be slow and some manufacturer sites block automated checks. The export preserves links and review notes.")

    with tabs[4]:
        st.markdown("### Vendor scorecard")
        if data["products"]:
            vendor_rows=[]
            for row in data["products"]:
                vendor_rows.append({"vendor":normalize_vendor(str(row.get("seller") or ""),str(row.get("product_link") or "")),"offer":row.get("title"),"score":vendor_score(row),"match_score":row.get("match_score"),"authorized":row.get("authorized_distributor"),"vendor_rating":row.get("vendor_rating")})
            st.dataframe(pd.DataFrame(vendor_rows).sort_values("score",ascending=False),use_container_width=True,hide_index=True)
        st.markdown("### Receiving log")
        rec=pd.DataFrame(data.get("receiving",[]))
        for c in ["product","vendor","po_number","ordered_qty","received_qty","damaged_qty","backordered_qty","expected_date","received_date","tracking_number","packing_slip","status","notes"]:
            if c not in rec: rec[c]=[] if rec.empty else ""
        rec_edit=st.data_editor(rec,num_rows="dynamic",hide_index=True,use_container_width=True,key="receiving_editor")
        data["receiving"]=rec_edit.fillna("").to_dict("records")

    with tabs[5]:
        st.markdown("### Export, audit, and templates")
        user=st.text_input("Prepared by",key="control_user")
        note=st.text_input("Audit note",placeholder="Approved vendor change after quote review",key="audit_note")
        if st.button("Add audit entry",use_container_width=True):
            append_audit(data["audit"],"Manual note",details=note,user=user); st.success("Audit entry added.")
        if data["audit"]: st.dataframe(pd.DataFrame(data["audit"]),use_container_width=True,hide_index=True)
        filename,content=create_procurement_control_workbook(data.get("project_name", ""),data["products"],data["requirements"],data["documents"],data["audit"])
        st.download_button("Download procurement control workbook",content,file_name=filename,mime=EXCEL_MIME,type="primary",use_container_width=True)
        backup=json.dumps(data,indent=2,default=str).encode("utf-8")
        st.download_button("Download control-center backup",backup,file_name="procurement_control_backup.json",mime="application/json",use_container_width=True)
        st.info("The workbook includes a dashboard, products, requirements, review queue, data-health findings, document register, audit log, and a draft PO sheet. Draft purchasing outputs still require human verification.")
    st.session_state.control_v8=data



def _render_spec_sheet_compare(config: AppConfig, openai_api_key: str) -> None:
    st.markdown("""<div class="hero"><h1>Spec Sheet Compare</h1><p>Upload the original required specification and one or more candidate product documents. The app extracts technical attributes, compares every required value, flags hard conflicts, and creates an evidence-backed Excel report.</p></div>""", unsafe_allow_html=True)
    with st.expander("How verification works", expanded=False):
        st.markdown("Missing information is marked **Not Confirmed**, never treated as a match. Explicit conflicts in dimensions, connections, voltage, capacity, material, finish, certifications, mounting, or required accessories can disqualify a candidate. Final purchasing approval should still be completed by a qualified reviewer.")
    original_file = st.file_uploader("Original / required spec sheet", type=["pdf","png","jpg","jpeg","webp"], key="spec_original")
    candidate_files = st.file_uploader("Candidate spec sheets", type=["pdf","png","jpg","jpeg","webp"], accept_multiple_files=True, key="spec_candidates")
    notes = st.text_area("Optional comparison instructions", placeholder="Exact manufacturer and model required; no substitutions. Treat 5-inch top, no-hub outlet, trap-primer tap, and clamping flange as mandatory.")
    run = st.button("Compare specification sheets", type="primary", use_container_width=True)
    if not run:
        return
    if not openai_api_key:
        st.error("OpenAI API key is required for document extraction and comparison.")
        return
    if original_file is None:
        st.error("Upload the original required spec sheet.")
        return
    if not candidate_files:
        st.error("Upload at least one candidate spec sheet.")
        return
    try:
        with st.status("Extracting the original specification...", expanded=True) as status:
            original = extract_spec_document(data=original_file.getvalue(), filename=original_file.name, openai_api_key=openai_api_key, model=config.openai_model)
            if notes.strip():
                original["comparison_instructions"] = notes.strip()
            st.write(f"Extracted {len(original.get('attributes', []))} original attributes.")
            results=[]
            candidate_docs=[]
            for uploaded in candidate_files[:10]:
                st.write(f"Reading candidate: {uploaded.name}")
                try:
                    candidate=extract_spec_document(data=uploaded.getvalue(), filename=uploaded.name, openai_api_key=openai_api_key, model=config.openai_model)
                    candidate_docs.append(candidate)
                    results.append(compare_spec_documents(original=original, candidate=candidate, openai_api_key=openai_api_key, model=config.openai_model))
                except Exception as exc:
                    st.warning(f"Could not compare {uploaded.name}: {exc}")
            status.update(label="Specification comparison complete.", state="complete")
    except Exception as exc:
        st.error(f"Could not read the original spec sheet: {exc}")
        return
    if not results:
        st.error("No candidate documents could be compared.")
        return
    ranked=sorted(results,key=lambda r:(r.hard_conflicts,-r.compatibility_score,-r.evidence_coverage))
    best=ranked[0]
    a,b,c,d=st.columns(4)
    a.metric("Candidates",len(ranked)); b.metric("Best compatibility",f"{best.compatibility_score:.1f}%"); c.metric("Evidence coverage",f"{best.evidence_coverage:.1f}%"); d.metric("Hard conflicts",best.hard_conflicts)
    if best.status in {"Exact Specification Match","Technical Equivalent"}:
        st.success(f"Top result: {best.candidate_name} — {best.status}")
    elif best.status == "Not Compatible":
        st.error(f"Top result still has technical conflicts: {best.candidate_name}")
    else:
        st.warning(f"Top result needs verification: {best.candidate_name}")
    summary_rows=[{"candidate":r.candidate_name,"manufacturer":r.manufacturer,"model":r.model,"status":r.status,"compatibility":r.compatibility_score,"evidence_coverage":r.evidence_coverage,"hard_conflicts":r.hard_conflicts,"unconfirmed_required":r.unconfirmed_required,"summary":r.summary} for r in ranked]
    st.subheader("Candidate ranking")
    st.dataframe(pd.DataFrame(summary_rows),use_container_width=True,hide_index=True,column_config={"compatibility":st.column_config.ProgressColumn("Compatibility",min_value=0,max_value=100,format="%.1f%%"),"evidence_coverage":st.column_config.ProgressColumn("Evidence coverage",min_value=0,max_value=100,format="%.1f%%")})
    selected=st.selectbox("Detailed comparison",options=list(range(len(ranked))),format_func=lambda i:f"{ranked[i].candidate_name} — {ranked[i].status} ({ranked[i].compatibility_score:.1f}%)")
    detail=pd.DataFrame(comparison_rows(ranked[selected]))
    st.dataframe(detail,use_container_width=True,hide_index=True,column_config={"confidence":st.column_config.ProgressColumn("Confidence",min_value=0,max_value=1,format="%.0f%%")})
    conflicts=detail[detail["status"].isin(["Conflict","Not Confirmed"])] if not detail.empty else detail
    if not conflicts.empty:
        st.subheader("Exceptions requiring attention")
        st.dataframe(conflicts,use_container_width=True,hide_index=True)
    filename,workbook=create_spec_comparison_workbook(original,ranked)
    st.download_button("Download spec comparison workbook",workbook,file_name=filename,mime=EXCEL_MIME,type="primary",use_container_width=True)


def _render_exact_image_match(config: AppConfig, serpapi_api_key: str, openai_api_key: str) -> None:
    st.markdown("""<div class="hero"><h1>Exact Product From Image</h1><p>Upload clear photos of a product, label, model plate, or packaging. The app builds a visual fingerprint, searches exact identifiers, and visually verifies the strongest retailer candidates.</p></div>""", unsafe_allow_html=True)
    photos=st.file_uploader("Upload one or more photos of the same product",type=["png","jpg","jpeg","webp"],accept_multiple_files=True,key="exact_photos")
    hints=st.text_area("Optional hints",placeholder="Where it is used, approximate size, retailer, brand, or text that is hard to read")
    location=st.text_input("Search location",value=config.default_location,key="exact_location")
    run=st.button("Identify and find exact product",type="primary",use_container_width=True)
    if not run: return
    if not photos: st.error("Upload at least one product photo."); return
    if not openai_api_key: st.error("OpenAI API key is required."); return
    if not serpapi_api_key: st.error("SerpApi is required for live retailer results."); return
    fingerprints=[]
    with st.status("Reading labels and building a visual fingerprint...",expanded=True):
        for photo in photos[:4]:
            try: fingerprints.append(build_visual_fingerprint(image_bytes=photo.getvalue(),openai_api_key=openai_api_key,model=config.openai_model,hints=hints,max_upload_mb=config.max_upload_mb))
            except Exception as exc: st.warning(f"Could not analyze {photo.name}: {exc}")
    if not fingerprints: return
    st.subheader("Identification evidence")
    st.dataframe(pd.DataFrame(fingerprints),use_container_width=True,hide_index=True)
    queries=[]
    for f in fingerprints:
        for q in f.get("search_queries",[]) or []:
            if clean_text(q): queries.append(clean_text(q))
        exact=" ".join(clean_text(f.get(k)) for k in ["brand","model_number","mpn","product_name","variant"] if clean_text(f.get(k)))
        if exact: queries.insert(0,exact)
    queries=unique_keep_order(queries,max_items=4)
    results=[]
    for q in queries:
        try: results.extend(google_shopping_search(query=q,input_source="Exact image match",api_key=serpapi_api_key,location=location,country_code=config.country_code,language=config.language,max_results=10))
        except Exception as exc: st.warning(f"Search failed for {q}: {exc}")
    results=_dedupe_products(results)
    rows=[r.to_row() for r in results]
    verified=visually_verify_candidates(reference_bytes=photos[0].getvalue(),candidates=rows,openai_api_key=openai_api_key,model=config.openai_model,max_upload_mb=config.max_upload_mb) if rows else []
    st.subheader("Visually verified candidates")
    if verified:
        df=pd.DataFrame(verified)
        st.dataframe(df,use_container_width=True,hide_index=True,column_config={"thumbnail":st.column_config.ImageColumn("Image"),"product_link":st.column_config.LinkColumn("Retailer page",display_text="Open"),"visual_score":st.column_config.ProgressColumn("Visual match",min_value=0,max_value=100,format="%.0f%%")})
        best=verified[0]
        if best.get("visual_status")=="Exact" and best.get("visual_score",0)>=92:
            st.success(f"Exact product candidate: {best.get('title')} — {best.get('visual_score'):.0f}% visual confidence")
        else: st.warning("No candidate was confirmed as exact. Review the strongest matches or upload a clearer label/model-number photo.")
    else:
        st.info("No candidate images were available for visual verification.")



def _render_request_quotes() -> None:
    st.markdown("""<div class="hero"><h1>Request Quotes</h1><p>Import a Product Hunter workbook, select the exact products, and generate an email-ready RFQ plus a vendor quote workbook with lead-time and delivery fields.</p></div>""", unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload a Product Hunter or project Excel workbook", type=["xlsx"], key="rfq_upload")
    items = []
    if uploaded:
        try:
            items = extract_rfq_items(uploaded.getvalue())
            st.success(f"Found {len(items)} unique product(s).")
        except Exception as exc:
            st.error(f"Could not read that workbook: {exc}")
    manual = st.text_area("Or paste products manually, one per line", placeholder="JOSAM 30002-5A-Z-50 | Floor drain | Qty 2")
    if not items and manual.strip():
        from product_finder.rfq_builder import RFQItem
        for line in _split_lines(manual):
            parts=[p.strip() for p in line.split("|")]
            items.append(RFQItem(description=parts[0], notes=" | ".join(parts[1:])))
    if not items:
        st.info("Upload a workbook or paste products to begin.")
        return
    df=pd.DataFrame([x.to_row() for x in items])
    edited=st.data_editor(df, use_container_width=True, hide_index=True, num_rows="dynamic", column_config={
        "include":st.column_config.CheckboxColumn("Include", default=True),
        "quantity":st.column_config.NumberColumn("Qty", min_value=1, step=1),
        "product_link":st.column_config.LinkColumn("Product link"),
        "spec_link":st.column_config.LinkColumn("Spec link"),
    })
    selected=edited[edited["include"]==True].to_dict("records") if "include" in edited else edited.to_dict("records")
    st.markdown("### Quote details")
    a,b,c=st.columns(3)
    with a:
        project_name=st.text_input("Project name", value="Bldg D 310 & 311")
        project_number=st.text_input("Project number")
        ship_to=st.text_input("Ship-to city/state/ZIP", placeholder="Long Beach, CA 90802")
    with b:
        needed_by=st.date_input("Required delivery date", value=None)
        substitutions=st.selectbox("Substitutions", ["No substitutions without written approval", "Approved equals allowed", "Equivalent products may be quoted separately"])
        tax_exempt=st.checkbox("Tax-exempt purchase")
    with c:
        contact_name=st.text_input("Contact name")
        contact_email=st.text_input("Contact email")
        contact_phone=st.text_input("Contact phone")
    notes=st.text_area("RFQ notes", placeholder="Include current stock, manufacturer lead time, freight, quote expiration, and earliest delivery date.")
    if not selected:
        st.warning("Select at least one product.")
        return
    needed_text=needed_by.isoformat() if needed_by else ""
    email=build_rfq_email(project_name,ship_to,needed_text,contact_name,contact_email,selected,substitutions,tax_exempt,notes)
    st.markdown("### Email-ready RFQ")
    st.code(email, language=None)
    project={"project_name":project_name,"project_number":project_number,"ship_to":ship_to,"needed_by":needed_text,"contact_name":contact_name,"contact_email":contact_email,"contact_phone":contact_phone,"substitutions":substitutions,"tax_exempt":tax_exempt,"email_draft":email}
    data=create_rfq_workbook(project,selected)
    filename=(clean_text(project_name).replace(" ","_") or "Product")+"_RFQ.xlsx"
    st.download_button("Download RFQ workbook",data=data,file_name=filename,mime=EXCEL_MIME,use_container_width=True)


def _format_epoch(value: object) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(value)))
    except (TypeError, ValueError, OSError):
        return ""


def _render_dashboard_workspace() -> None:
    st.markdown("""<div class="hero"><div class="eyebrow">Product Hunter Pro · v30</div><h1>Procurement Dashboard</h1><p>Monitor research performance, reviewed products, cache health, and recent activity from one professional control center.</p></div>""", unsafe_allow_html=True)
    kb = ProductKnowledgeBase()
    stats = kb.stats()
    run_stats = kb.research_run_stats()
    verified = kb.list_verified_products(limit=1000)
    runs = kb.list_research_runs(limit=100)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Reviewed products", stats.get("verified_products", 0))
    k2.metric("Research runs", run_stats.get("runs", 0))
    k3.metric("Sources collected", run_stats.get("results", 0))
    k4.metric("Cache hit rate", f"{(100 * run_stats.get('cache_hits', 0) / max(1, run_stats.get('runs', 0))):.0f}%")
    k5.metric("Avg. research time", f"{run_stats.get('avg_duration', 0):.1f}s")

    left, right = st.columns([1.45, 1])
    with left:
        st.markdown("### Recent research activity")
        if runs:
            run_df = pd.DataFrame([{
                "Query": r.get("query", ""), "Depth": r.get("depth", ""),
                "Results": r.get("result_count", 0), "Warnings": r.get("warning_count", 0),
                "Duration (s)": round(float(r.get("duration_seconds", 0)), 2),
                "Cache": bool(r.get("cache_hit", 0)), "Status": r.get("status", ""),
                "Time": _format_epoch(r.get("created_at")),
            } for r in runs])
            st.dataframe(run_df, use_container_width=True, hide_index=True, height=390, column_config={
                "Cache": st.column_config.CheckboxColumn("Cache"),
                "Results": st.column_config.NumberColumn("Results"),
                "Warnings": st.column_config.NumberColumn("Warnings"),
            })
            chosen = st.selectbox("Prepare a recent query", run_df["Query"].drop_duplicates().tolist(), key="dashboard_recent_query")
            if st.button("Open in Product Search", type="primary", use_container_width=True):
                st.session_state["project_search_queries"] = chosen
                st.session_state["workspace_mode"] = "Product Search"
                st.rerun()
        else:
            st.info("Research activity will appear here after the first product search.")
    with right:
        st.markdown("### Review status")
        if verified:
            status_df = pd.DataFrame(verified)
            counts = status_df.groupby("status").size().rename("Products")
            st.bar_chart(counts)
            st.dataframe(status_df[["manufacturer", "model", "title", "status"]].head(12), use_container_width=True, hide_index=True, height=270)
        else:
            st.info("No reviewed products yet. Save decisions from the Evidence workspace.")
        st.markdown("### System health")
        warning_rate = run_stats.get("warnings", 0) / max(1, run_stats.get("runs", 0))
        if warning_rate == 0:
            st.success("No provider warnings recorded.")
        elif warning_rate < 1:
            st.warning("Some research runs recorded provider warnings. Review Diagnostics when results look incomplete.")
        else:
            st.error("Frequent provider warnings detected. Check SearXNG availability and Render logs.")
        st.caption(f"Saved views: {stats.get('saved_views', 0)} · Cached searches: {stats.get('cached_research', 0)}")


def _render_knowledge_base_workspace() -> None:
    st.markdown("""<div class="hero"><div class="eyebrow">Product Intelligence · v26</div><h1>Knowledge Base</h1><p>Review verified products, inspect cached research, export intelligence, and manage stored evidence.</p></div>""", unsafe_allow_html=True)
    kb = ProductKnowledgeBase()
    stats = kb.stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Verified products", stats["verified_products"])
    c2.metric("Cached searches", stats["cached_research"])
    expired_removed = 0
    with c3:
        if st.button("Clean expired cache", use_container_width=True):
            expired_removed = kb.clear_expired_cache()
            st.success(f"Removed {expired_removed} expired cache record(s).")
    snapshot = json.dumps(kb.export_snapshot(), indent=2).encode("utf-8")
    c4.download_button("Export knowledge snapshot", data=snapshot, file_name="Product_Hunter_Knowledge_Base.json", mime="application/json", use_container_width=True)

    verified_tab, cache_tab, settings_tab = st.tabs(["Verified products", "Research cache", "Workspace settings"])
    with verified_tab:
        rows = kb.list_verified_products()
        if not rows:
            st.info("No reviewed products yet. Save a decision from the Evidence viewer after running research.")
        else:
            df = pd.DataFrame([{
                "Manufacturer": r.get("manufacturer", ""), "Model": r.get("model", ""),
                "Product": r.get("title", ""), "Status": r.get("status", ""),
                "Notes": r.get("notes", ""), "Updated": _format_epoch(r.get("updated_at")),
                "Key": r.get("product_key", ""),
            } for r in rows])
            st.dataframe(df.drop(columns=["Key"]), use_container_width=True, hide_index=True, height=420)
            selected_key = st.selectbox("Select a reviewed product", df["Key"].tolist(), format_func=lambda k: df.loc[df["Key"] == k, "Product"].iloc[0])
            selected = next((r for r in rows if r.get("product_key") == selected_key), None)
            if selected:
                left, right = st.columns([2, 1])
                with left:
                    st.markdown(f"### {selected.get('title') or 'Reviewed product'}")
                    st.write(f"**Manufacturer:** {selected.get('manufacturer') or 'Not recorded'}")
                    st.write(f"**Model:** {selected.get('model') or 'Not recorded'}")
                    st.write(f"**Status:** {selected.get('status') or 'Needs review'}")
                    st.write(selected.get("notes") or "No reviewer notes.")
                with right:
                    evidence = selected.get("evidence") or []
                    st.metric("Evidence records", len(evidence))
                    if st.button("Delete reviewed product", type="secondary", use_container_width=True):
                        kb.delete_verified_product(selected_key)
                        st.success("Reviewed product deleted.")
                        st.rerun()
                if evidence:
                    st.dataframe(pd.DataFrame(evidence), use_container_width=True, hide_index=True)
    with cache_tab:
        cache_rows = kb.list_cached_research()
        if cache_rows:
            cache_df = pd.DataFrame([{
                "Query": r.get("query", ""), "Location": r.get("location", ""),
                "Saved": _format_epoch(r.get("created_at")), "Expires": _format_epoch(r.get("expires_at")),
            } for r in cache_rows])
            st.dataframe(cache_df, use_container_width=True, hide_index=True, height=420)
            st.caption("Cached research speeds up repeat searches. Refresh live sources when price, availability, or newly published documents matter.")
            if st.button("Clear all research cache", use_container_width=True):
                count = kb.clear_research_cache()
                st.success(f"Cleared {count} cached research record(s).")
                st.rerun()
        else:
            st.info("No cached research is stored yet.")
    with settings_tab:
        st.markdown("### Interface preferences")
        st.write("Theme and table-density preferences are available in the sidebar and apply immediately to this browser session.")
        st.info("The SQLite knowledge base is suitable for one Streamlit deployment. A shared PostgreSQL or Supabase database is recommended before multi-user production use.")


def _render_product_workspace() -> None:
    st.markdown("## Product Workspace")
    st.caption("Manage a reviewed product's evidence, lifecycle, notes, and approval status in one place.")
    kb = ProductKnowledgeBase()
    products = kb.list_verified_products(limit=1000)
    if not products:
        st.info("No reviewed products are available yet. Run research, open Evidence, and save a review decision first.")
        if st.button("Open Product Search", type="primary", key="product_workspace_open_search"):
            st.session_state["workspace_mode"] = "Product Search"
            st.rerun()
        return

    keys = [item["product_key"] for item in products]
    requested_key = st.session_state.get("selected_product_key", "")
    default_index = keys.index(requested_key) if requested_key in keys else 0
    selected_key = st.selectbox(
        "Product record", keys, index=default_index,
        format_func=lambda key: next(f"{item.get('manufacturer') or 'Unknown manufacturer'} · {item.get('model') or item.get('title') or key[:8]}" for item in products if item["product_key"] == key),
        key="product_workspace_selector",
    )
    st.session_state["selected_product_key"] = selected_key
    product = kb.get_verified_product(selected_key)
    if not product:
        st.error("The selected product record could not be loaded.")
        return

    left, right = st.columns([3, 1])
    with left:
        st.markdown(f"### {product.get('title') or 'Untitled product'}")
        st.caption(f"{product.get('manufacturer') or 'Unknown manufacturer'} · {product.get('model') or 'Model not recorded'}")
    with right:
        st.metric("Status", product.get("status") or "Needs review")

    overview_tab, evidence_tab, timeline_tab, notes_tab, actions_tab = st.tabs(["Overview", "Evidence", "Timeline", "Notes", "Actions"])
    with overview_tab:
        a, b, c, d = st.columns(4)
        a.metric("Evidence", len(product.get("evidence") or []))
        b.metric("Timeline", len(kb.list_product_events(selected_key)))
        c.metric("Notes", len(kb.list_product_notes(selected_key)))
        d.metric("Updated", time.strftime("%Y-%m-%d", time.localtime(float(product.get("updated_at") or 0))))
        st.dataframe(pd.DataFrame([{
            "Manufacturer": product.get("manufacturer", ""), "Model / MPN": product.get("model", ""),
            "Product": product.get("title", ""), "Status": product.get("status", ""),
            "Reviewer summary": product.get("notes", ""),
        }]), use_container_width=True, hide_index=True)
    with evidence_tab:
        evidence = product.get("evidence") or []
        if not evidence:
            st.info("No evidence is attached to this product.")
        else:
            rows = [{
                "Title": item.get("title", ""), "Overall": item.get("overall_score", 0),
                "Trust": item.get("source_reliability", 0), "Match": item.get("match_score", 0),
                "Source type": item.get("source_type", ""), "Official": bool(item.get("official_source", False)),
                "Exact model": bool(item.get("exact_model_mentioned", False)), "Link": item.get("link", ""),
                "Evidence": item.get("evidence", ""),
            } for item in evidence]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, column_config={
                "Overall": st.column_config.ProgressColumn("Overall", min_value=0, max_value=100),
                "Trust": st.column_config.ProgressColumn("Trust", min_value=0, max_value=100),
                "Match": st.column_config.ProgressColumn("Match", min_value=0, max_value=100),
                "Official": st.column_config.CheckboxColumn("Official"),
                "Exact model": st.column_config.CheckboxColumn("Exact model"),
                "Link": st.column_config.LinkColumn("Source", display_text="Open"),
            })
    with timeline_tab:
        stages = ["Specified", "Researched", "Reviewed", "Approved", "Quoted", "Ordered", "Received", "Installed", "Warranty"]
        events = kb.list_product_events(selected_key)
        completed = {str(event.get("stage", "")) for event in events}
        stage_cols = st.columns(len(stages))
        for idx, stage_name in enumerate(stages):
            stage_cols[idx].markdown(f"**{'✓ ' if stage_name in completed else ''}{stage_name}**")
        if events:
            event_df = pd.DataFrame(events)
            event_df["created_at"] = event_df["created_at"].map(lambda value: time.strftime("%Y-%m-%d %H:%M", time.localtime(float(value))))
            st.dataframe(event_df[["created_at", "stage", "detail", "actor"]], use_container_width=True, hide_index=True)
        else:
            st.info("No lifecycle events have been recorded.")
        with st.form("product_timeline_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            stage_name = c1.selectbox("Stage", stages)
            actor = c2.text_input("Actor / reviewer")
            detail = st.text_input("Event detail")
            if st.form_submit_button("Add timeline event", type="primary"):
                kb.add_product_event(selected_key, stage_name, detail, actor)
                st.success("Timeline event added.")
                st.rerun()
    with notes_tab:
        notes = kb.list_product_notes(selected_key)
        if notes:
            for item in notes:
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(item.get("created_at") or 0)))
                st.markdown(f"**{item.get('author') or 'Team member'}** · {when}")
                st.write(item.get("note", ""))
                st.divider()
        else:
            st.info("No product notes have been added.")
        with st.form("product_note_form", clear_on_submit=True):
            author = st.text_input("Author")
            note = st.text_area("Add note")
            if st.form_submit_button("Save note", type="primary"):
                try:
                    kb.add_product_note(selected_key, note, author)
                    st.success("Note saved.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    with actions_tab:
        statuses = ["Verified exact", "Approved equivalent", "Needs review", "Rejected", "Quoted", "Ordered", "Received", "Installed"]
        current = product.get("status") or "Needs review"
        new_status = st.selectbox("Review / procurement status", statuses, index=statuses.index(current) if current in statuses else 2)
        new_notes = st.text_area("Reviewer summary", value=product.get("notes", ""))
        c1, c2 = st.columns(2)
        if c1.button("Update product record", type="primary", use_container_width=True):
            kb.update_verified_product_status(selected_key, new_status, new_notes)
            kb.add_product_event(selected_key, new_status, "Status updated from Product Workspace")
            st.success("Product record updated.")
            st.rerun()
        export_record = {"product": product, "events": kb.list_product_events(selected_key, 10000), "notes": kb.list_product_notes(selected_key, 10000)}
        c2.download_button("Export product record", json.dumps(export_record, indent=2).encode("utf-8"),
                           file_name=f"Product_Hunter_{(product.get('model') or 'product').replace('/', '-')}.json",
                           mime="application/json", use_container_width=True)


def _render_system_center(config: AppConfig) -> None:
    st.markdown("""<div class="hero"><div class="eyebrow">Enterprise Operations · v30</div><h1>System Center</h1><p>Validate service health, inspect incidents, export diagnostics, and resolve configuration problems without exposing secrets.</p></div>""", unsafe_allow_html=True)
    serpapi_api_key, openai_api_key, brave_api_key, searxng_url = _resolve_api_keys(config)
    db_path = ProductKnowledgeBase().path

    action_cols = st.columns([1, 1, 1, 4])
    run_now = action_cols[0].button("Run health checks", type="primary", use_container_width=True)
    if action_cols[1].button("Clear incidents", use_container_width=True):
        clear_error_log()
        st.toast("Incident log cleared.")
        st.rerun()
    snapshot = diagnostics_snapshot(
        app_version=APP_VERSION,
        config_summary={
            "provider_order": config.search_provider_order,
            "searxng_configured": bool(searxng_url),
            "openai_configured": bool(openai_api_key),
            "serpapi_configured": bool(serpapi_api_key),
            "resource_profile": config.resource_profile,
            "knowledge_database": str(db_path),
        },
    )
    action_cols[2].download_button(
        "Export diagnostics",
        data=json.dumps(snapshot, indent=2).encode("utf-8"),
        file_name="Product_Hunter_Diagnostics.json",
        mime="application/json",
        use_container_width=True,
    )

    if run_now or "v30_health_checks" not in st.session_state:
        with st.spinner("Checking configured services..."):
            st.session_state["v30_health_checks"] = [
                item.to_row() for item in run_health_checks(
                    searxng_url=searxng_url, openai_api_key=openai_api_key, db_path=db_path
                )
            ]
        record_event("health_check", "System health checks completed", checks=len(st.session_state["v30_health_checks"]))

    checks = pd.DataFrame(st.session_state.get("v30_health_checks", []))
    if not checks.empty:
        healthy = int(checks["status"].isin(["Healthy", "Configured"]).sum())
        degraded = int(checks["status"].isin(["Degraded", "Review", "Not configured"]).sum())
        down = int((checks["status"] == "Down").sum())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Healthy services", healthy)
        c2.metric("Needs attention", degraded)
        c3.metric("Unavailable", down)
        c4.metric("Recorded incidents", len(recent_errors(500)))
        st.dataframe(
            checks, use_container_width=True, hide_index=True,
            column_config={
                "name": st.column_config.TextColumn("Service"),
                "status": st.column_config.TextColumn("Status"),
                "detail": st.column_config.TextColumn("Details", width="large"),
                "latency_ms": st.column_config.NumberColumn("Latency (ms)", format="%d"),
                "action": st.column_config.TextColumn("Recommended action", width="large"),
            },
        )

    incident_tab, event_tab, readiness_tab = st.tabs(["Incident center", "Activity log", "Commercial readiness"])
    with incident_tab:
        errors = recent_errors(100)
        if not errors:
            st.success("No application incidents have been recorded in this deployment.")
        else:
            incident_df = pd.DataFrame([{
                "Incident": e.get("incident_id", ""),
                "Workspace": e.get("workspace", ""),
                "Type": e.get("error_type", ""),
                "Message": e.get("message", ""),
                "Timestamp": pd.to_datetime(e.get("timestamp", 0), unit="s", errors="coerce"),
            } for e in errors])
            st.dataframe(incident_df, use_container_width=True, hide_index=True)
            selected_id = st.selectbox("Inspect incident", incident_df["Incident"].tolist())
            selected = next(e for e in errors if e.get("incident_id") == selected_id)
            st.code(selected.get("traceback", "No traceback recorded."), language="text")
    with event_tab:
        events = recent_events(100)
        if events:
            st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
        else:
            st.info("Operational events will appear after health checks and research runs.")
    with readiness_tab:
        st.markdown("#### Enterprise readiness priorities")
        readiness = pd.DataFrame([
            {"Capability": "Persistent managed database", "Status": "Next", "Why it matters": "Survives redeploys and enables teams."},
            {"Capability": "Role-based access", "Status": "Planned", "Why it matters": "Separates reviewers, buyers, admins, and clients."},
            {"Capability": "Approval audit trail", "Status": "Foundation present", "Why it matters": "Makes purchasing decisions defensible."},
            {"Capability": "Background job queue", "Status": "Planned", "Why it matters": "Large research runs should continue outside the browser request."},
            {"Capability": "Automated regression suite", "Status": "Active", "Why it matters": "Prevents old workflows from breaking during upgrades."},
        ])
        st.dataframe(readiness, use_container_width=True, hide_index=True)


def _workspace_css(theme: str, density: str, text_size: str = "Standard") -> str:
    # Return a high-contrast, accessible application theme for both display modes.
    dark = theme == "Dark"
    if dark:
        colors = {
            "bg": "#0b0f16", "surface": "#121923", "surface2": "#192332",
            "surface3": "#202c3d", "border": "#344256", "border_strong": "#506079",
            "text": "#f7f9fc", "text_strong": "#ffffff", "muted": "#bdc8d8",
            "subtle": "#98a7bb", "nav": "#080c12", "nav2": "#101826",
            "input": "#0f1722", "hover": "#1c293a", "selected": "#183b60",
            "link": "#74b9f2", "focus": "#6cb8f5", "success": "#54d79b",
            "warning": "#ffd166", "danger": "#ff8a9a", "info_bg": "#122943",
            "success_bg": "#103326", "warning_bg": "#3a2d0e", "danger_bg": "#3a1820",
            "shadow": "0 1px 2px rgba(0,0,0,.42),0 10px 30px rgba(0,0,0,.22)",
        }
    else:
        colors = {
            "bg": "#f3f5f8", "surface": "#ffffff", "surface2": "#f7f9fc",
            "surface3": "#eef2f7", "border": "#cdd5df", "border_strong": "#9aa8b8",
            "text": "#182230", "text_strong": "#0c1420", "muted": "#4f5f70",
            "subtle": "#66778a", "nav": "#101827", "nav2": "#172033",
            "input": "#ffffff", "hover": "#edf4fb", "selected": "#e5f1fc",
            "link": "#005ea6", "focus": "#0f6cbd", "success": "#0b6f3c",
            "warning": "#7a5400", "danger": "#a4262c", "info_bg": "#eaf4fd",
            "success_bg": "#e8f5ee", "warning_bg": "#fff4ce", "danger_bg": "#fdebec",
            "shadow": "0 1px 2px rgba(15,23,42,.08),0 10px 28px rgba(15,23,42,.06)",
        }
    pad = ".48rem" if density == "Compact" else ".78rem"
    control = "2.2rem" if density == "Compact" else "2.65rem"
    row_height = "32px" if density == "Compact" else "41px"
    base_font = "15px" if text_size == "Standard" else "17px"
    small_font = "12.5px" if text_size == "Standard" else "14px"
    c = colors
    return f'''<style>
    :root{{--ph-bg:{c["bg"]};--ph-surface:{c["surface"]};--ph-surface2:{c["surface2"]};--ph-surface3:{c["surface3"]};--ph-border:{c["border"]};--ph-border-strong:{c["border_strong"]};--ph-text:{c["text"]};--ph-text-strong:{c["text_strong"]};--ph-muted:{c["muted"]};--ph-subtle:{c["subtle"]};--ph-accent:#0f6cbd;--ph-accent-hover:#115ea3;--ph-link:{c["link"]};--ph-focus:{c["focus"]};--ph-nav:{c["nav"]};--ph-nav2:{c["nav2"]};--ph-input:{c["input"]};--ph-hover:{c["hover"]};--ph-selected:{c["selected"]};--ph-success:{c["success"]};--ph-warning:{c["warning"]};--ph-danger:{c["danger"]};--ph-info-bg:{c["info_bg"]};--ph-success-bg:{c["success_bg"]};--ph-warning-bg:{c["warning_bg"]};--ph-danger-bg:{c["danger_bg"]};--ph-shadow:{c["shadow"]};--ph-font:{base_font};--ph-small:{small_font};}}
    html,body,[class*="css"]{{font-family:"Segoe UI Variable","Segoe UI",Inter,Arial,sans-serif;font-size:var(--ph-font);}}
    body,.stApp,.stApp>header{{background:var(--ph-bg);color:var(--ph-text);}}
    .block-container{{max-width:1680px;padding:1rem 1.35rem 4rem;}}
    .main *{{box-sizing:border-box;}}

    /* Global readable foregrounds */
    .stApp p,.stApp li,.stApp label,.stApp span,.stApp strong,.stApp em,.stApp div[data-testid="stMarkdownContainer"],.stApp div[data-testid="stCaptionContainer"]{{color:var(--ph-text);}}
    .stApp small,.stCaption,[data-testid="stCaptionContainer"],.muted{{color:var(--ph-muted)!important;font-size:var(--ph-small);}}
    h1,h2,h3,h4,h5,h6{{color:var(--ph-text-strong)!important;font-family:"Segoe UI Variable","Segoe UI",Inter,Arial,sans-serif;letter-spacing:-.018em;line-height:1.24;}}
    a,a:visited{{color:var(--ph-link)!important;text-decoration-thickness:1px;text-underline-offset:2px;}}
    a:hover{{text-decoration:underline;}}
    code,kbd,pre{{color:var(--ph-text-strong)!important;background:var(--ph-surface2)!important;border-color:var(--ph-border)!important;}}
    hr{{border-color:var(--ph-border)!important;}}

    /* Keyboard focus and accessibility */
    button:focus-visible,input:focus-visible,textarea:focus-visible,[role="combobox"]:focus-visible,[role="tab"]:focus-visible,a:focus-visible{{outline:3px solid var(--ph-focus)!important;outline-offset:2px!important;box-shadow:none!important;}}
    ::selection{{background:var(--ph-selected);color:var(--ph-text-strong);}}

    /* Sidebar */
    [data-testid="stSidebar"]{{background:linear-gradient(180deg,var(--ph-nav),var(--ph-nav2));border-right:1px solid #35435a;}}
    [data-testid="stSidebar"] p,[data-testid="stSidebar"] span,[data-testid="stSidebar"] label,[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,[data-testid="stSidebar"] strong{{color:#f4f7fb!important;}}
    [data-testid="stSidebar"] small,[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{{color:#c2cddd!important;}}
    [data-testid="stSidebar"] hr{{border-color:#3b4960!important;}}
    [data-testid="stSidebar"] [role="radiogroup"] label{{padding:.38rem .48rem;border-radius:5px;}}
    [data-testid="stSidebar"] [role="radiogroup"] label:hover{{background:rgba(255,255,255,.09);}}
    [data-testid="stSidebar"] input,[data-testid="stSidebar"] textarea,[data-testid="stSidebar"] [data-baseweb="select"]>div{{color:#111827!important;background:#fff!important;border-color:#aeb9c7!important;}}
    [data-testid="stSidebar"] [data-baseweb="select"] span{{color:#111827!important;}}

    /* Inputs and menus */
    input,textarea,[data-baseweb="select"]>div,[data-baseweb="base-input"]{{background:var(--ph-input)!important;color:var(--ph-text-strong)!important;border-color:var(--ph-border-strong)!important;}}
    input::placeholder,textarea::placeholder{{color:var(--ph-subtle)!important;opacity:1;}}
    [data-baseweb="select"] span,[data-baseweb="popover"] *{{color:var(--ph-text)!important;}}
    [data-baseweb="popover"],[role="listbox"],[data-baseweb="menu"]{{background:var(--ph-surface)!important;color:var(--ph-text)!important;border-color:var(--ph-border)!important;}}
    [role="option"]{{color:var(--ph-text)!important;background:var(--ph-surface)!important;}}
    [role="option"]:hover,[aria-selected="true"][role="option"]{{background:var(--ph-selected)!important;color:var(--ph-text-strong)!important;}}
    [data-testid="stFileUploader"]{{color:var(--ph-text)!important;}}
    [data-testid="stFileUploaderDropzone"]{{background:var(--ph-surface2)!important;border-color:var(--ph-border-strong)!important;}}
    [data-testid="stFileUploaderDropzone"] *{{color:var(--ph-text)!important;}}

    /* Shell and hero */
    .app-shell{{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.6rem .78rem;margin:0 0 .75rem;background:var(--ph-surface);border:1px solid var(--ph-border);border-radius:7px;box-shadow:0 1px 2px rgba(15,23,42,.05);}}
    .app-shell .brand{{display:flex;align-items:center;gap:.58rem;font-weight:720;color:var(--ph-text-strong);}}
    .app-shell .brandmark{{width:29px;height:29px;border-radius:6px;display:grid;place-items:center;background:linear-gradient(135deg,#0f6cbd,#4f46e5);color:#fff!important;font-size:.78rem;}}
    .app-shell .meta{{font-size:.77rem;color:var(--ph-muted)!important;display:flex;align-items:center;gap:.65rem;}}
    .app-shell .meta *{{color:var(--ph-muted)!important;}}
    .status-dot{{width:7px;height:7px;border-radius:999px;background:#2bb673;display:inline-block;box-shadow:0 0 0 3px rgba(43,182,115,.14);}}
    .hero{{padding:1.35rem 1.55rem;border-radius:8px;background:linear-gradient(112deg,#101827 0%,#15385f 55%,#0f6cbd 100%);color:#fff!important;margin:.15rem 0 .85rem;box-shadow:0 6px 24px rgba(15,23,42,.18);border:1px solid rgba(255,255,255,.1);}}
    .hero *{{color:#fff!important;}}.hero h1{{margin:0;font-size:1.95rem;font-weight:700}}.hero p{{margin:.4rem 0 0;color:#e6f2ff!important;max-width:1120px;line-height:1.55}}.hero .eyebrow{{text-transform:uppercase;letter-spacing:.12em;font-size:.69rem;color:#b9e0ff!important;font-weight:750;margin-bottom:.3rem;}}
    .commandbar{{display:flex;align-items:center;flex-wrap:wrap;gap:.44rem;background:var(--ph-surface);border:1px solid var(--ph-border);border-radius:6px;padding:.48rem .68rem;margin-bottom:.8rem;box-shadow:0 1px 2px rgba(15,23,42,.05);font-size:.84rem;color:var(--ph-muted)!important;}}
    .commandbar span{{color:var(--ph-muted)!important;}}.commandbar .pill{{background:var(--ph-selected);color:var(--ph-link)!important;border:1px solid rgba(15,108,189,.35);border-radius:4px;padding:.24rem .52rem;font-weight:700;}}

    /* Cards, metrics, buttons */
    .section-card,div[data-testid="stMetric"]{{background:var(--ph-surface);border:1px solid var(--ph-border);border-radius:6px;box-shadow:var(--ph-shadow);}}
    div[data-testid="stMetric"]{{padding:{pad} 1rem;}}
    div[data-testid="stMetricLabel"]{{font-size:.73rem;color:var(--ph-muted)!important;text-transform:uppercase;letter-spacing:.05em;font-weight:650;}}
    div[data-testid="stMetricValue"]{{font-size:1.55rem;font-weight:720;color:var(--ph-text-strong)!important;}}
    div[data-testid="stMetricDelta"]{{color:var(--ph-muted)!important;}}
    div.stButton>button,div.stDownloadButton>button{{border-radius:4px;font-weight:650;min-height:{control};border:1px solid var(--ph-border-strong)!important;background:var(--ph-surface)!important;color:var(--ph-text-strong)!important;}}
    div.stButton>button:hover,div.stDownloadButton>button:hover{{border-color:var(--ph-accent)!important;color:var(--ph-link)!important;background:var(--ph-hover)!important;}}
    div.stButton>button[kind="primary"],div.stDownloadButton>button[kind="primary"]{{background:var(--ph-accent)!important;color:#fff!important;border-color:var(--ph-accent)!important;}}
    div.stButton>button[kind="primary"] *,div.stDownloadButton>button[kind="primary"] *{{color:#fff!important;}}
    div.stButton>button[kind="primary"]:hover,div.stDownloadButton>button[kind="primary"]:hover{{background:var(--ph-accent-hover)!important;color:#fff!important;}}
    button:disabled{{opacity:.62!important;color:var(--ph-muted)!important;background:var(--ph-surface2)!important;}}

    /* Data grids */
    [data-testid="stDataFrame"],[data-testid="stDataEditor"]{{background:var(--ph-surface);border:1px solid var(--ph-border);border-radius:5px;overflow:hidden;box-shadow:0 1px 2px rgba(15,23,42,.04);}}
    [data-testid="stDataFrame"] *,[data-testid="stDataEditor"] *{{color:var(--ph-text)!important;}}
    [data-testid="stDataFrame"] canvas,[data-testid="stDataEditor"] canvas{{background:var(--ph-surface)!important;}}
    [data-testid="stDataFrame"] [role="columnheader"],[data-testid="stDataEditor"] [role="columnheader"]{{background:var(--ph-surface3)!important;color:var(--ph-text-strong)!important;font-weight:700;}}
    [data-testid="stDataFrame"] [role="gridcell"],[data-testid="stDataEditor"] [role="gridcell"]{{min-height:{row_height};color:var(--ph-text)!important;background:var(--ph-surface)!important;}}
    [data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"],[data-testid="stDataEditor"] [role="row"]:hover [role="gridcell"]{{background:var(--ph-hover)!important;}}

    /* Tabs, expanders, alerts, tooltips */
    [data-baseweb="tab-list"]{{gap:.05rem;border-bottom:1px solid var(--ph-border);background:var(--ph-surface);padding:0 .35rem;}}
    [data-baseweb="tab"]{{border-radius:3px 3px 0 0;padding:.55rem .84rem;font-weight:650;color:var(--ph-muted)!important;}}
    [data-baseweb="tab"] *{{color:inherit!important;}}
    [data-baseweb="tab"][aria-selected="true"]{{color:var(--ph-link)!important;background:var(--ph-selected);border-bottom:2px solid var(--ph-accent);}}
    [data-testid="stExpander"]{{border:1px solid var(--ph-border);border-radius:6px;background:var(--ph-surface);}}
    [data-testid="stExpander"] summary,[data-testid="stExpander"] summary *{{color:var(--ph-text-strong)!important;}}
    .stAlert{{border-radius:5px;color:var(--ph-text)!important;border:1px solid var(--ph-border)!important;}}
    .stAlert *{{color:var(--ph-text)!important;}}
    [data-testid="stNotificationContentInfo"]{{background:var(--ph-info-bg)!important;}}
    [data-testid="stNotificationContentSuccess"]{{background:var(--ph-success-bg)!important;}}
    [data-testid="stNotificationContentWarning"]{{background:var(--ph-warning-bg)!important;}}
    [data-testid="stNotificationContentError"]{{background:var(--ph-danger-bg)!important;}}
    [data-testid="stToast"]{{background:var(--ph-surface)!important;color:var(--ph-text)!important;border:1px solid var(--ph-border)!important;}}
    [data-baseweb="tooltip"]{{background:var(--ph-text-strong)!important;color:var(--ph-bg)!important;}}

    .result-highlight{{background:var(--ph-surface);border:1px solid var(--ph-border);border-left:4px solid var(--ph-accent);border-radius:6px;padding:.78rem .95rem;margin:.25rem 0 .65rem;}}
    .result-highlight strong{{color:var(--ph-text-strong)!important;}}.result-highlight span{{color:var(--ph-muted)!important;}}
    .empty-state{{text-align:center;padding:2rem 1rem;border:1px dashed var(--ph-border-strong);border-radius:8px;background:var(--ph-surface);color:var(--ph-muted)!important;}}
    .empty-state *{{color:var(--ph-muted)!important;}}.empty-state h3{{margin:.25rem 0;color:var(--ph-text-strong)!important;}}
    .kbd{{font-size:.7rem;border:1px solid var(--ph-border);border-bottom-width:2px;border-radius:4px;padding:.08rem .32rem;background:var(--ph-surface2);color:var(--ph-text-strong)!important;}}
    .resource-card{{background:var(--ph-surface2);border:1px solid var(--ph-border);padding:.7rem .8rem;margin:.45rem 0 .7rem;color:var(--ph-text)!important;font-size:.84rem;line-height:1.5;border-radius:5px;}}
    .resource-card *{{color:var(--ph-text)!important;}}.resource-card strong{{color:var(--ph-text-strong)!important;}}
    .contrast-note{{display:inline-flex;align-items:center;gap:.35rem;padding:.22rem .5rem;border-radius:999px;background:var(--ph-success-bg);color:var(--ph-success)!important;border:1px solid color-mix(in srgb,var(--ph-success) 35%,transparent);font-size:.74rem;font-weight:700;}}

    @media(max-width:900px){{.block-container{{padding:.65rem .7rem 3rem}}.hero{{padding:1rem}}.hero h1{{font-size:1.55rem}}.app-shell .meta{{display:none}}.commandbar{{font-size:.78rem}}}}
    @media(prefers-reduced-motion:reduce){{*,*::before,*::after{{animation-duration:.01ms!important;transition-duration:.01ms!important;scroll-behavior:auto!important;}}}}
    </style>'''

def _main_impl() -> None:
    st.set_page_config(page_title="Product Hunter Pro", page_icon="🔎", layout="wide")
    st.session_state.setdefault("ui_theme", "Light")
    st.session_state.setdefault("ui_density", "Compact")
    st.session_state.setdefault("ui_text_size", "Standard")
    st.markdown(_workspace_css(st.session_state["ui_theme"], st.session_state["ui_density"], st.session_state["ui_text_size"]), unsafe_allow_html=True)
    config = load_config(_secret_getter)

    if not _password_gate(config):
        return

    st.markdown(
        f"""<div class="app-shell"><div class="brand"><div class="brandmark">PH</div><span>Product Hunter Pro</span></div><div class="meta"><span><span class="status-dot"></span>&nbsp; Workspace online</span><span>v{APP_VERSION}</span><span class="kbd">Ctrl K</span> Quick navigation</div></div>""",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown("### PRODUCT HUNTER")
        st.caption("Procurement Intelligence Platform · v30")
        app_mode = st.radio("Workspace", ["Dashboard", "Product Search", "Product Workspace", "Knowledge Base", "System Center", "Project Intelligence", "Spec Sheet Compare", "Exact Product From Image", "Request Quotes", "Procurement Control Center", "Purchase Tracker"], horizontal=False, key="workspace_mode")
        with st.expander("Appearance"):
            theme = st.selectbox("Theme", ["Light", "Dark"], index=0 if st.session_state["ui_theme"] == "Light" else 1)
            density = st.selectbox("Table density", ["Compact", "Comfortable"], index=0 if st.session_state["ui_density"] == "Compact" else 1)
            text_size = st.selectbox("Text size", ["Standard", "Large"], index=0 if st.session_state["ui_text_size"] == "Standard" else 1)
            st.markdown('<span class="contrast-note">✓ High-contrast text enabled</span>', unsafe_allow_html=True)
            if theme != st.session_state["ui_theme"] or density != st.session_state["ui_density"] or text_size != st.session_state["ui_text_size"]:
                st.session_state["ui_theme"] = theme
                st.session_state["ui_density"] = density
                st.session_state["ui_text_size"] = text_size
                st.rerun()
        with st.expander("Quick navigation"):
            quick_target = st.selectbox("Go to", ["Dashboard", "Product Search", "Product Workspace", "Knowledge Base", "System Center", "Project Intelligence", "Spec Sheet Compare", "Request Quotes", "Purchase Tracker"], key="quick_nav_target")
            if st.button("Open workspace", use_container_width=True, key="quick_nav_open"):
                st.session_state["workspace_mode"] = quick_target
                st.rerun()

    if app_mode == "Dashboard":
        _render_dashboard_workspace()
        return
    if app_mode == "Product Workspace":
        _render_product_workspace()
        return
    if app_mode == "Knowledge Base":
        _render_knowledge_base_workspace()
        return
    if app_mode == "System Center":
        _render_system_center(config)
        return
    if app_mode == "Request Quotes":
        _render_request_quotes()
        return
    if app_mode == "Spec Sheet Compare":
        _, openai_api_key, _, _ = _resolve_api_keys(config)
        _render_spec_sheet_compare(config, openai_api_key)
        return
    if app_mode == "Exact Product From Image":
        serpapi_api_key, openai_api_key, brave_api_key, searxng_url = _resolve_api_keys(config)
        _render_exact_image_match(config, serpapi_api_key, openai_api_key)
        return
    if app_mode == "Purchase Tracker":
        _render_purchase_tracker()
        return
    if app_mode == "Procurement Control Center":
        _render_procurement_control_center()
        return
    if app_mode == "Project Intelligence":
        serpapi_api_key, openai_api_key, brave_api_key, searxng_url = _resolve_api_keys(config)
        _render_project_intelligence(openai_api_key, config.openai_model)
        return

    st.markdown("""<div class="hero"><div class="eyebrow">Procurement Intelligence Workspace · v30</div><h1>Product Hunter Pro</h1><p>Research, verify, compare, and retain product intelligence across manufacturers, distributors, technical documents, legacy sources, and purchasing channels.</p></div><div class="commandbar"><span class="pill">Research</span><span>Evidence</span><span>Products</span><span>Documents</span><span>Suppliers</span><span>RFQ</span><span>Export</span></div>""", unsafe_allow_html=True)

    command_cols = st.columns([1, 1, 1, 1, 5])
    if command_cols[0].button("New research", use_container_width=True):
        st.session_state["product_barcode_search"] = ""
        st.session_state["product_text_searches"] = ""
        st.rerun()
    if command_cols[1].button("Knowledge Base", use_container_width=True):
        st.session_state["workspace_mode"] = "Knowledge Base"
        st.rerun()
    command_cols[2].button("Refresh", use_container_width=True, help="Enable Refresh live sources in Search settings before running research.")
    command_cols[3].button("Help", use_container_width=True, help="Use Product Search for research, Evidence viewer for approval, and Request Quotes for vendor RFQs.")

    serpapi_api_key, openai_api_key, brave_api_key, searxng_url = _resolve_api_keys(config)

    with st.sidebar:
        st.divider()
        st.header("Search settings")
        location = st.text_input("City, state, or ZIP", value=config.default_location)
        search_everywhere = st.checkbox("Research Everywhere", value=True, help="Runs multiple focused searches for official manufacturer pages, documents, pricing, lead times, distributors, local suppliers, and legacy products.")
        resource_profile = st.selectbox(
            "Resource profile",
            ["Efficient", "Balanced", "Thorough"],
            index={"Efficient": 0, "Balanced": 1, "Thorough": 2}.get(config.resource_profile, 1),
            help="Efficient minimizes queries and concurrency. Balanced is recommended. Thorough uses more searches for difficult or high-value products.",
        )
        profile_settings = {
            "Efficient": {"workers": 1, "budget": 6, "results": 12, "cache": 168, "timeout": 35},
            "Balanced": {"workers": config.search_max_workers, "budget": config.search_query_budget, "results": 20, "cache": config.research_cache_hours, "timeout": config.search_request_timeout},
            "Thorough": {"workers": min(5, max(3, config.search_max_workers + 1)), "budget": min(18, max(12, config.search_query_budget + 4)), "results": 35, "cache": 24, "timeout": min(90, max(60, config.search_request_timeout + 20))},
        }[resource_profile]
        research_depth = st.selectbox("Research depth", ["Standard", "Deep"], index=0, help="Deep research adds lifecycle, CAD/BIM, warranty, and manufacturer-domain searches. Use it only when the standard run is insufficient.")
        st.session_state["force_research_refresh"] = st.checkbox("Refresh live sources", value=False, help="Ignore saved research and run a fresh provider search. Leave this off to reduce server and API usage.")
        st.markdown(
            f"<div class='resource-card'><strong>{resource_profile} plan</strong><br>"
            f"Up to {profile_settings['budget']} focused queries · {profile_settings['workers']} concurrent worker(s) · "
            f"{profile_settings['cache']}h research cache</div>",
            unsafe_allow_html=True,
        )
        try:
            kb_stats = ProductKnowledgeBase().stats()
            st.caption(f"Knowledge Base: {kb_stats['cached_research']} cached searches · {kb_stats['verified_products']} verified products")
        except Exception:
            st.caption("Knowledge Base initializes on first research run.")
        with st.expander("Source controls"):
            include_online = st.checkbox("Shopping and shipping listings", value=True)
            include_nearby = st.checkbox("Nearby supplier leads", value=True)
            include_specs = st.checkbox("Technical documents", value=True)
            include_manufacturer = st.checkbox("Official manufacturer sources", value=True)
            include_broad_web = st.checkbox("Broad web, distributors, and legacy pages", value=True)
        max_product_results = st.slider("Listings per search term", min_value=3, max_value=20, value=8)
        max_store_results = st.slider("Nearby stores per search term", min_value=1, max_value=10, value=4)
        max_spec_results = st.slider("Technical documents per search term", min_value=1, max_value=8, value=3)
        max_manufacturer_results = st.slider("Manufacturer sources per search term", min_value=1, max_value=8, value=4)
        max_omni_results = st.slider("Broad web results per search term", min_value=5, max_value=50, value=profile_settings["results"])
        max_queries_per_input = st.slider("Search terms per image/input", min_value=1, max_value=4, value=2)
        with st.expander("Advanced"):
            country_code = st.text_input("Country code", value=config.country_code).lower().strip() or "us"
            language = st.text_input("Language", value=config.language).lower().strip() or "en"
            openai_model = st.text_input("OpenAI vision model", value=config.openai_model).strip() or config.openai_model
        history = st.session_state.get("search_history", [])
        if history:
            with st.expander("Recent searches"):
                for item in history[:5]:
                    st.caption(f"{item['file']} — {item['listings']} listings, {item['documents']} documents")

    with st.expander("Data handling and search limitations"):
        st.markdown(
            "Uploaded images are validated, resized, stripped of image metadata, and sent to the configured OpenAI API "
            "for product recognition. Search text and public image URLs are sent to SerpApi. The app creates the Excel "
            "file in memory and does not intentionally retain uploads or search results. Hosting and API providers may "
            "still maintain operational logs. Do not upload confidential work material unless your employer permits it.\n\n"
            "Nearby results identify possible retailers, not guaranteed live shelf inventory. Always confirm stock, price, "
            "delivery, and seller details on the retailer page."
        )

    with st.form("product_search_form"):
        st.markdown("### Product inputs")
        left, right = st.columns(2)
        with left:
            barcode_searches = st.text_input("Optional UPC / barcode / manufacturer part number", placeholder="012345678905 or JOSAM 30000-5A-Z", key="product_barcode_search")
            text_searches = st.text_area(
                "Text searches, one per line",
                value=st.session_state.get("project_search_queries", ""),
                placeholder="black Nike hoodie\nCrucial 2TB NVMe SSD",
                height=170,
                key="product_text_searches",
            )
            uploaded_images = st.file_uploader(
                "Upload product images",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                help=f"Up to {config.max_inputs} total inputs; each image may be up to {config.max_upload_mb} MB.",
            )
        with right:
            image_urls_text = st.text_area(
                "Public image URLs, one per line",
                placeholder="https://example.com/product-photo.jpg",
                height=170,
                help="Public image URLs use Google Lens through SerpApi.",
            )
            hints = st.text_area(
                "Optional product hints",
                placeholder="brand, color, size, material, model number, budget, or preferred variant",
                height=110,
                max_chars=1000,
            )
        submitted = st.form_submit_button("Research products and build procurement workbook", type="primary", use_container_width=True)

    if not submitted:
        st.info("Add a text search, image upload, or public image URL, then start the search.")
        return

    if not search_everywhere and not include_online and not include_nearby and not include_specs and not include_manufacturer and not include_broad_web:
        st.error("Enable online listings, nearby retailer leads, technical documents, or a combination.")
        return

    text_queries = _split_lines(text_searches)
    if barcode_searches.strip():
        text_queries = unique_keep_order([barcode_searches.strip(), *text_queries])
    raw_image_urls = _split_lines(image_urls_text)
    invalid_urls = [url for url in raw_image_urls if not _valid_public_image_url(url)]
    image_urls = [url for url in raw_image_urls if _valid_public_image_url(url)]
    uploaded_images = list(uploaded_images or [])

    if invalid_urls:
        st.warning(f"Skipped {len(invalid_urls)} invalid public image URL(s). Use complete http:// or https:// URLs.")

    total_inputs = len(text_queries) + len(image_urls) + len(uploaded_images)
    if total_inputs == 0:
        st.error("Add at least one text search, uploaded image, or valid public image URL.")
        return
    if total_inputs > config.max_inputs:
        st.error(f"This deployment allows up to {config.max_inputs} inputs per run. You supplied {total_inputs}.")
        return

    input_records: list[InputRecord] = []
    product_results: list[ProductResult] = []
    store_results: list[StoreResult] = []
    spec_documents: list[SpecDocument] = []
    manufacturer_results: list[ManufacturerResult] = []
    omni_results: list[OmniSearchResult] = []
    run_notes: list[str] = []
    search_provider_outage = False
    stale_cache_used = False

    with st.status("Recognizing products and building search terms...", expanded=True) as status:
        if text_queries:
            st.write(f"Added {len(text_queries)} typed search input(s).")
            input_records.extend(_make_input_records_from_text(text_queries))

        for url in image_urls:
            if not serpapi_api_key:
                input_records.append(
                    InputRecord(
                        input_type="image_url",
                        label=url,
                        source_url=url,
                        notes="Skipped Google Lens because the retailer-search API is not configured.",
                    )
                )
                run_notes.append("Some public image URLs were skipped because SerpApi was not configured.")
                continue
            st.write(f"Reading public image URL: {url[:90]}")
            input_records.append(
                google_lens_queries_from_url(
                    image_url=url,
                    api_key=serpapi_api_key,
                    country_code=country_code,
                    language=language,
                    extra_query_hint=hints,
                    max_queries=max_queries_per_input,
                )
            )

        for uploaded in uploaded_images:
            st.write(f"Recognizing uploaded image: {uploaded.name}")
            input_records.append(
                analyze_uploaded_image(
                    image_bytes=uploaded.getvalue(),
                    mime_type=uploaded.type or "image/jpeg",
                    label=uploaded.name,
                    openai_api_key=openai_api_key,
                    model=openai_model,
                    user_hints=hints,
                    max_upload_mb=config.max_upload_mb,
                )
            )

        search_jobs = _build_search_jobs(input_records, max_queries_per_input=max_queries_per_input)
        status.update(label=f"Built {len(search_jobs)} unique search job(s).", state="complete")

    _show_input_records(input_records)

    if len(search_jobs) > config.max_search_jobs:
        st.error(
            f"This run generated {len(search_jobs)} search jobs, above the deployment limit of "
            f"{config.max_search_jobs}. Reduce the inputs or search terms per input."
        )
        return

    web_search_ready = bool(searxng_url or brave_api_key or serpapi_api_key)
    if not web_search_ready:
        note = "No live results were fetched because no web-search provider is configured."
        run_notes.append(note)
        st.error(note)
        filename, workbook_bytes = create_product_workbook_bytes(
            input_records=input_records,
            product_results=[],
            store_results=[],
            spec_documents=[],
            location=location,
            run_notes=" | ".join(unique_keep_order(run_notes)),
        )
        st.download_button(
            "Download spreadsheet with recognized inputs",
            data=workbook_bytes,
            file_name=filename,
            mime=EXCEL_MIME,
            use_container_width=True,
            on_click="ignore",
        )
        return

    if not search_jobs:
        st.warning("No usable search terms were generated. Add clearer text or more specific image hints.")
        return

    if search_everywhere:
        include_online = include_nearby = include_specs = include_manufacturer = include_broad_web = True
    steps_per_job = (int(include_online and bool(serpapi_api_key)) + int(include_nearby and bool(serpapi_api_key)) + int(include_specs and bool(serpapi_api_key)) + int(include_manufacturer and bool(serpapi_api_key)) + int(include_broad_web))
    total_steps = len(search_jobs) * steps_per_job
    completed = 0
    progress = st.progress(0, text="Researching products across all enabled sources...")

    for query, input_source in search_jobs:
        if include_online and serpapi_api_key:
            try:
                product_results.extend(
                    google_shopping_search(
                        query=query,
                        input_source=input_source,
                        api_key=serpapi_api_key,
                        location=location,
                        country_code=country_code,
                        language=language,
                        max_results=max_product_results,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - safe provider errors are displayed per query.
                message = f"Online search failed for '{query}': {exc}"
                st.warning(message)
                run_notes.append(message)
            completed += 1
            progress.progress(completed / total_steps, text=f"Searched online listings for: {query}")

        if include_nearby and serpapi_api_key:
            try:
                store_results.extend(
                    google_maps_nearby_stores(
                        query=query,
                        api_key=serpapi_api_key,
                        location=location,
                        country_code=country_code,
                        language=language,
                        max_results=max_store_results,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - safe provider errors are displayed per query.
                message = f"Nearby search failed for '{query}': {exc}"
                st.warning(message)
                run_notes.append(message)
            completed += 1
            progress.progress(completed / total_steps, text=f"Searched nearby retailers for: {query}")

        if include_specs and serpapi_api_key:
            try:
                spec_documents.extend(
                    google_spec_sheet_search(
                        query=query,
                        api_key=serpapi_api_key,
                        country_code=country_code,
                        language=language,
                        max_results=max_spec_results,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                message = f"Technical-document search failed for '{query}': {exc}"
                st.warning(message)
                run_notes.append(message)
            completed += 1
            progress.progress(completed / total_steps, text=f"Searched technical documents for: {query}")

        if include_manufacturer and serpapi_api_key:
            try:
                manufacturer_results.extend(
                    google_manufacturer_search(
                        query=query,
                        api_key=serpapi_api_key,
                        country_code=country_code,
                        language=language,
                        max_results=max_manufacturer_results,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                message = f"Manufacturer-site search failed for '{query}': {exc}"
                st.warning(message)
                run_notes.append(message)
            completed += 1
            progress.progress(completed / total_steps, text=f"Searched manufacturer sources for: {query}")

        if include_broad_web:
            try:
                kb = ProductKnowledgeBase()
                agent = ResearchAgent(kb)
                provider_results, provider_notes, research_meta = agent.research(
                    query=query, location=location, depth=research_depth,
                    searxng_url=searxng_url, brave_api_key=brave_api_key,
                    serpapi_api_key=serpapi_api_key, provider_order=config.search_provider_order,
                    country_code=country_code, language=language, max_results=max_omni_results,
                    force_refresh=st.session_state.get("force_research_refresh", False),
                    cache_ttl_hours=profile_settings["cache"],
                    max_workers=profile_settings["workers"],
                    query_budget=profile_settings["budget"],
                    request_timeout=profile_settings["timeout"],
                )
                omni_results.extend(provider_results)
                if research_meta.get("cache_hit"):
                    run_notes.append(f"Knowledge Base cache used for '{query}'.")
                if research_meta.get("provider_outage"):
                    search_provider_outage = True
                if research_meta.get("used_stale_cache"):
                    stale_cache_used = True
                run_notes.extend(f"OmniSearch provider warning for '{query}': {note}" for note in provider_notes)
            except Exception as exc:  # noqa: BLE001
                search_provider_outage = True
                message = f"Broad OmniSearch failed for '{query}': {exc}"
                st.warning(message)
                run_notes.append(message)
            completed += 1
            progress.progress(completed / total_steps, text=f"Completed procurement research for: {query}")

    product_results = rank_product_matches(_dedupe_products(product_results))
    store_results = _dedupe_stores(store_results)
    omni_results = rank_omni_results(omni_results + omni_from_existing(products=product_results, specs=spec_documents, manufacturers=manufacturer_results, stores=store_results))
    routed_products, routed_stores, routed_specs, routed_manufacturers = _route_omni_results(omni_results)
    product_results = rank_product_matches(_dedupe_products(product_results + routed_products))
    store_results = _dedupe_stores(store_results + routed_stores)
    spec_documents = list({(d.link or d.title): d for d in (spec_documents + routed_specs)}.values())
    manufacturer_results = list({(m.link or m.title): m for m in (manufacturer_results + routed_manufacturers)}.values())
    progress.progress(1.0, text="Research complete.")

    filename, workbook_bytes = create_product_workbook_bytes(
        input_records=input_records,
        product_results=product_results,
        store_results=store_results,
        spec_documents=spec_documents,
        manufacturer_results=manufacturer_results,
        omni_results=omni_results,
        location=location,
        run_notes=" | ".join(unique_keep_order(run_notes)),
    )

    if search_provider_outage and not omni_results:
        st.error(
            "Search infrastructure is temporarily unavailable. The workbook was still created from recognized inputs, "
            "but live sources were not returned. Open Diagnostics or retry after the SearXNG engines recover."
        )
    elif stale_cache_used:
        st.warning(
            f"Live search was unavailable, so Product Hunter used older cached evidence. Your workbook will download as **{filename}**."
        )
    else:
        st.success(f"Research complete. Your procurement workbook will download as **{filename}**.")
    best_count = sum(1 for item in product_results if item.best_match)
    if best_count:
        st.info(
            f"Best Match ranked {best_count} search group(s). Scores compare the requested model, manufacturer, "
            "dimensions, materials, connections, finish, and accessories against each listing. Always verify the official spec sheet before ordering."
        )
    history_item = {"file": filename, "inputs": len(input_records), "listings": len(product_results), "stores": len(store_results), "documents": len(spec_documents), "manufacturer_sources": len(manufacturer_results), "omni_results": len(omni_results)}
    st.session_state.setdefault("search_history", []).insert(0, history_item)
    st.session_state["search_history"] = st.session_state["search_history"][:10]
    metric_one, metric_two, metric_three, metric_four, metric_five, metric_six = st.columns(6)
    metric_one.metric("Inputs", len(input_records))
    metric_two.metric("Product listings", len(product_results))
    metric_three.metric("Nearby retailers", len(store_results))
    metric_four.metric("Technical documents", len(spec_documents))
    metric_five.metric("Manufacturer sources", len(manufacturer_results))
    metric_six.metric("All sources", len(omni_results))

    if run_notes:
        with st.expander("Research diagnostics", expanded=not bool(omni_results)):
            for note in unique_keep_order(run_notes):
                st.write(f"- {note}")
    if include_broad_web and not omni_results:
        if search_provider_outage:
            st.error(
                "Live search did not return data because SearXNG's upstream engines were unavailable, blocked, or rate limited. "
                "This is a provider outage—not proof that the product does not exist. Empty outage responses are not cached."
            )
        else:
            st.info(
                "The search provider responded normally, but no matching public results were found. "
                "Try a manufacturer name, exact model number, or broader product description."
            )

    overview_tab, evidence_tab, offers_tab, documents_tab, suppliers_tab, diagnostics_tab = st.tabs([
        "Overview", "Evidence", "Offers", "Documents", "Suppliers", "Diagnostics"
    ])
    with overview_tab:
        _show_omni_results(omni_results)
    with evidence_tab:
        st.markdown("#### Evidence viewer")
        st.caption("Inspect why a source ranked highly, then save a reviewed product to the local knowledge base.")
        if omni_results:
            selected_index = st.selectbox(
                "Select research source",
                options=list(range(len(omni_results))),
                format_func=lambda i: f"{omni_results[i].overall_score:.0f}% · {omni_results[i].title[:90]}",
                key="v20_evidence_source",
            )
            selected = omni_results[selected_index]
            left_e, right_e = st.columns([2, 1])
            with left_e:
                st.markdown(f"### {selected.title}")
                st.write(selected.snippet or "No source excerpt was returned.")
                st.markdown(f"**Source:** {selected.source_domain or selected.source_name or 'Unknown'}")
                st.markdown(f"**Type:** {selected.source_type} · **Result kind:** {selected.result_kind}")
                if selected.link:
                    st.link_button("Open source", selected.link)
            with right_e:
                st.metric("Evidence score", f"{selected.overall_score:.0f}%")
                st.metric("Source reliability", f"{selected.source_reliability:.0f}%")
                st.metric("Product match", f"{selected.match_score:.0f}%")
                st.write(f"**Verification:** {selected.verification_status or 'Needs review'}")
                st.write(f"**Exact model mentioned:** {'Yes' if selected.exact_model_mentioned else 'No'}")
                st.write(f"**Official source:** {'Yes' if selected.official_source else 'No'}")
            st.info(selected.evidence or "No detailed evidence explanation was generated for this source.")
            with st.expander("Compare multiple sources", expanded=False):
                compare_ids = st.multiselect(
                    "Choose up to three sources",
                    options=list(range(len(omni_results))),
                    default=[selected_index],
                    max_selections=3,
                    format_func=lambda i: f"{omni_results[i].overall_score:.0f}% · {omni_results[i].title[:70]}",
                    key="v22_compare_sources",
                )
                if compare_ids:
                    comparison = pd.DataFrame([{
                        "Title": omni_results[i].title,
                        "Overall": omni_results[i].overall_score,
                        "Trust": omni_results[i].source_reliability,
                        "Match": omni_results[i].match_score,
                        "Source type": omni_results[i].source_type,
                        "Official": omni_results[i].official_source,
                        "Exact model": omni_results[i].exact_model_mentioned,
                        "Verification": omni_results[i].verification_status,
                        "Link": omni_results[i].link,
                    } for i in compare_ids])
                    st.dataframe(comparison, use_container_width=True, hide_index=True, column_config={
                        "Overall": st.column_config.ProgressColumn("Overall", min_value=0, max_value=100),
                        "Trust": st.column_config.ProgressColumn("Trust", min_value=0, max_value=100),
                        "Match": st.column_config.ProgressColumn("Match", min_value=0, max_value=100),
                        "Official": st.column_config.CheckboxColumn("Official"),
                        "Exact model": st.column_config.CheckboxColumn("Exact model"),
                        "Link": st.column_config.LinkColumn("Source", display_text="Open"),
                    })
                    st.download_button(
                        "Export comparison JSON",
                        data=json.dumps(comparison.to_dict("records"), indent=2).encode("utf-8"),
                        file_name="Product_Hunter_Evidence_Comparison.json",
                        mime="application/json",
                        use_container_width=True,
                    )
            with st.expander("Save review decision", expanded=False):
                c1, c2 = st.columns(2)
                manufacturer = c1.text_input("Manufacturer", value=selected.source_name if selected.official_source else "", key="v20_verified_manufacturer")
                model = c2.text_input("Model / MPN", value=selected.query, key="v20_verified_model")
                status_choice = st.selectbox("Review status", ["Verified exact", "Approved equivalent", "Needs review", "Rejected"], key="v20_verified_status")
                reviewer_notes = st.text_area("Reviewer notes", key="v20_verified_notes")
                if st.button("Save to Product Intelligence Database", type="primary", key="v20_save_verified"):
                    saved_key = ProductKnowledgeBase().upsert_verified_product(
                        manufacturer=manufacturer,
                        model=model,
                        title=selected.title,
                        status=status_choice,
                        notes=reviewer_notes,
                        evidence=[selected.to_row()],
                    )
                    ProductKnowledgeBase().add_product_event(saved_key, "Reviewed", f"Evidence decision saved: {status_choice}")
                    st.session_state["selected_product_key"] = saved_key
                    st.success("Review decision saved. Open Product Workspace to manage its lifecycle.")
        else:
            st.info("Run product research to inspect source evidence.")
    with offers_tab:
        _show_product_results(product_results)
    with documents_tab:
        doc_col, mfg_col = st.columns(2)
        with doc_col:
            _show_spec_documents(spec_documents)
        with mfg_col:
            _show_manufacturer_results(manufacturer_results)
    with suppliers_tab:
        _show_store_results(store_results)
    with diagnostics_tab:
        st.markdown("#### Research health")
        st.write(f"Normalized sources: **{len(omni_results)}**")
        st.write(f"Routed offers: **{len(product_results)}** · documents: **{len(spec_documents)}** · manufacturer sources: **{len(manufacturer_results)}**")
        if run_notes:
            for note in unique_keep_order(run_notes):
                st.write(f"- {note}")
        else:
            st.success("No provider warnings were recorded for this run.")

    st.download_button(
        f"Download {filename}",
        data=workbook_bytes,
        file_name=filename,
        mime=EXCEL_MIME,
        type="primary",
        use_container_width=True,
        on_click="ignore",
    )


def main() -> None:
    try:
        _main_impl()
    except Exception as exc:
        workspace = str(st.session_state.get("workspace_mode", "unknown"))
        incident_id = record_exception(exc, workspace=workspace, context={"app_version": APP_VERSION})
        st.error("Product Hunter encountered an unexpected problem, but your incident was recorded safely.")
        st.markdown(f"**Incident ID:** `{incident_id}`")
        st.caption("Open System Center to inspect the technical details and export a diagnostics package.")
        c1, c2 = st.columns(2)
        if c1.button("Open System Center", type="primary", use_container_width=True, key="fatal_open_system_center"):
            st.session_state["workspace_mode"] = "System Center"
            st.rerun()
        if c2.button("Retry workspace", use_container_width=True, key="fatal_retry"):
            st.rerun()


if __name__ == "__main__":
    main()
