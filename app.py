from __future__ import annotations

import hmac
from typing import Iterable
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from product_finder.config import AppConfig, load_config
from product_finder.models import InputRecord, ProductResult, SpecDocument, StoreResult
from product_finder.search import (
    google_lens_queries_from_url,
    google_maps_nearby_stores,
    google_shopping_search,
    google_spec_sheet_search,
)
from product_finder.spreadsheet import create_product_workbook_bytes
from product_finder.utils import clean_text, unique_keep_order
from product_finder.vision import analyze_uploaded_image


APP_TITLE = "Product Hunter"
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


def _resolve_api_keys(config: AppConfig) -> tuple[str, str]:
    server_keys_allowed = bool(config.app_password) or config.allow_public_with_server_keys
    serpapi_api_key = config.serpapi_api_key if server_keys_allowed else ""
    openai_api_key = config.openai_api_key if server_keys_allowed else ""

    with st.sidebar:
        st.header("Service status")
        if config.serpapi_api_key and not server_keys_allowed:
            st.warning("Hosted retailer-search key is disabled until APP_PASSWORD is set or public key use is explicitly enabled.")
        elif serpapi_api_key:
            st.success("Retailer and nearby search: ready")
        else:
            st.warning("Retailer and nearby search: API key missing")

        if config.openai_api_key and not server_keys_allowed:
            st.warning("Hosted image-recognition key is disabled by the access policy.")
        elif openai_api_key:
            st.success("Uploaded-image recognition: ready")
        else:
            st.info("Uploaded-image recognition: API key missing")

        if config.allow_user_api_keys:
            with st.expander("Use different API keys"):
                user_serpapi_key = st.text_input(
                    "SerpApi API key",
                    type="password",
                    help="Used only for this browser session and not written to the spreadsheet.",
                )
                user_openai_key = st.text_input(
                    "OpenAI API key",
                    type="password",
                    help="Used only for this browser session and not written to the spreadsheet.",
                )
                if user_serpapi_key.strip():
                    serpapi_api_key = user_serpapi_key.strip()
                if user_openai_key.strip():
                    openai_api_key = user_openai_key.strip()

    return serpapi_api_key, openai_api_key


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
    st.subheader("Online and shipping listings")
    if not results:
        st.info("No product listings were returned, or online search was disabled.")
        return
    dataframe = _records_to_df(results)
    columns = [
        "thumbnail",
        "title",
        "seller",
        "price",
        "delivery",
        "rating",
        "reviews",
        "condition",
        "query",
        "product_link",
    ]
    st.dataframe(
        dataframe[[column for column in columns if column in dataframe.columns]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "thumbnail": st.column_config.ImageColumn("Image"),
            "product_link": st.column_config.LinkColumn("Retailer page", display_text="Open listing"),
            "rating": st.column_config.NumberColumn("Rating", format="%.1f"),
            "reviews": st.column_config.NumberColumn("Reviews", format="%d"),
        },
    )


def _show_store_results(results: list[StoreResult]) -> None:
    st.subheader("Nearby retailer leads")
    if not results:
        st.info("No nearby stores were returned, or nearby search was disabled.")
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
    st.subheader("Technical documents")
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

def main() -> None:
    st.set_page_config(page_title="Product Hunter", page_icon="🔎", layout="wide")
    st.markdown("""<style>
    .stApp {background: linear-gradient(180deg,#f4f8fc 0%,#ffffff 45%);}
    .block-container {max-width: 1380px; padding-top: 2rem;}
    h1,h2,h3 {color:#17324d;}
    [data-testid="stSidebar"] {background:#edf4fb; border-right:1px solid #d7e4f0;}
    .hero {padding:1.4rem 1.6rem;border-radius:18px;background:linear-gradient(120deg,#17324d,#2e75b6);color:white;margin-bottom:1.25rem;box-shadow:0 10px 28px rgba(23,50,77,.16)}
    .hero h1{color:white;margin:0;font-size:2.25rem}.hero p{margin:.5rem 0 0;color:#eaf3fb;font-size:1.05rem}
    div[data-testid="stMetric"] {background:white;border:1px solid #dbe7f2;padding:1rem;border-radius:14px;box-shadow:0 5px 16px rgba(23,50,77,.06)}
    div.stButton > button, div.stDownloadButton > button {border-radius:10px;font-weight:700;}
    </style>""", unsafe_allow_html=True)
    config = load_config(_secret_getter)

    if not _password_gate(config):
        return

    st.markdown("""<div class="hero"><h1>Product Hunter</h1><p>Recognize products from images or text, compare retailers, find nearby suppliers and technical documents, then export a polished Excel workbook with product images.</p></div>""", unsafe_allow_html=True)

    serpapi_api_key, openai_api_key = _resolve_api_keys(config)

    with st.sidebar:
        st.divider()
        st.header("Search settings")
        location = st.text_input("City, state, or ZIP", value=config.default_location)
        include_online = st.checkbox("Online and shipping listings", value=True)
        include_nearby = st.checkbox("Nearby retailer leads", value=True)
        include_specs = st.checkbox("Spec sheets and technical documents", value=True)
        max_product_results = st.slider("Listings per search term", min_value=3, max_value=20, value=8)
        max_store_results = st.slider("Nearby stores per search term", min_value=1, max_value=10, value=4)
        max_spec_results = st.slider("Technical documents per search term", min_value=1, max_value=8, value=3)
        max_queries_per_input = st.slider("Search terms per image/input", min_value=1, max_value=4, value=2)
        with st.expander("Advanced"):
            country_code = st.text_input("Country code", value=config.country_code).lower().strip() or "us"
            language = st.text_input("Language", value=config.language).lower().strip() or "en"
            openai_model = st.text_input("OpenAI vision model", value=config.openai_model).strip() or config.openai_model

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
        left, right = st.columns(2)
        with left:
            text_searches = st.text_area(
                "Text searches, one per line",
                placeholder="black Nike hoodie\nCrucial 2TB NVMe SSD",
                height=170,
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
        submitted = st.form_submit_button("Find products and build spreadsheet", type="primary", use_container_width=True)

    if not submitted:
        st.info("Add a text search, image upload, or public image URL, then start the search.")
        return

    if not include_online and not include_nearby and not include_specs:
        st.error("Enable online listings, nearby retailer leads, technical documents, or a combination.")
        return

    text_queries = _split_lines(text_searches)
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
    run_notes: list[str] = []

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

    if not serpapi_api_key:
        note = "No live listings were fetched because the retailer-search API is not configured."
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

    steps_per_job = int(include_online) + int(include_nearby) + int(include_specs)
    total_steps = len(search_jobs) * steps_per_job
    completed = 0
    progress = st.progress(0, text="Searching retailers...")

    for query, input_source in search_jobs:
        if include_online:
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

        if include_nearby:
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

        if include_specs:
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

    product_results = _dedupe_products(product_results)
    store_results = _dedupe_stores(store_results)
    progress.progress(1.0, text="Search complete.")

    filename, workbook_bytes = create_product_workbook_bytes(
        input_records=input_records,
        product_results=product_results,
        store_results=store_results,
        spec_documents=spec_documents,
        location=location,
        run_notes=" | ".join(unique_keep_order(run_notes)),
    )

    st.success("Search complete. Review the results below and download the Excel workbook.")
    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Inputs", len(input_records))
    metric_two.metric("Product listings", len(product_results))
    metric_three.metric("Nearby retailers", len(store_results))
    metric_four.metric("Technical documents", len(spec_documents))

    _show_product_results(product_results)
    _show_store_results(store_results)
    _show_spec_documents(spec_documents)

    st.download_button(
        "Download Excel spreadsheet",
        data=workbook_bytes,
        file_name=filename,
        mime=EXCEL_MIME,
        type="primary",
        use_container_width=True,
        on_click="ignore",
    )


if __name__ == "__main__":
    main()
