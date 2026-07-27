from __future__ import annotations

import hmac
from typing import Iterable
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from product_finder.config import AppConfig, load_config
from product_finder.models import InputRecord, ProductResult, SpecDocument, StoreResult
from product_finder.matching import rank_product_matches
from product_finder.search import (
    google_lens_queries_from_url,
    google_maps_nearby_stores,
    google_shopping_search,
    google_spec_sheet_search,
)
from product_finder.spreadsheet import create_product_workbook_bytes
from product_finder.purchase_tracker import extract_purchase_candidates, create_purchase_tracker_bytes
from product_finder.utils import clean_text, unique_keep_order
from product_finder.vision import analyze_uploaded_image
from product_finder.project_intelligence import (
    consolidate_items, create_project_backup, create_project_workbook,
    create_submittal_zip, extract_schedule_items, load_project_backup,
)


APP_TITLE = "Product Hunter Pro"
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

def main() -> None:
    st.set_page_config(page_title="Product Hunter Pro", page_icon="🔎", layout="wide")
    st.markdown("""<style>
    .stApp {background: linear-gradient(180deg,#f4f8fc 0%,#ffffff 45%);}
    .block-container {max-width: 1380px; padding-top: 2rem;}
    h1,h2,h3 {color:#17324d;}
    .section-card{background:white;border:1px solid #dbe7f2;border-radius:16px;padding:1rem 1.1rem;margin:.75rem 0;box-shadow:0 6px 18px rgba(23,50,77,.05)}
    [data-testid="stSidebar"] {background:#edf4fb; border-right:1px solid #d7e4f0;}
    .hero {padding:1.4rem 1.6rem;border-radius:18px;background:linear-gradient(120deg,#17324d,#2e75b6);color:white;margin-bottom:1.25rem;box-shadow:0 10px 28px rgba(23,50,77,.16)}
    .hero h1{color:white;margin:0;font-size:2.25rem}.hero p{margin:.5rem 0 0;color:#eaf3fb;font-size:1.05rem}
    div[data-testid="stMetric"] {background:white;border:1px solid #dbe7f2;padding:1rem;border-radius:14px;box-shadow:0 5px 16px rgba(23,50,77,.06)}
    div.stButton > button, div.stDownloadButton > button {border-radius:10px;font-weight:700;}
    </style>""", unsafe_allow_html=True)
    config = load_config(_secret_getter)

    if not _password_gate(config):
        return

    with st.sidebar:
        app_mode = st.radio("Workspace", ["Product Search", "Project Intelligence", "Purchase Tracker"], horizontal=False)

    if app_mode == "Purchase Tracker":
        _render_purchase_tracker()
        return
    if app_mode == "Project Intelligence":
        serpapi_api_key, openai_api_key = _resolve_api_keys(config)
        _render_project_intelligence(openai_api_key, config.openai_model)
        return

    st.markdown("""<div class="hero"><h1>Product Hunter Pro</h1><p>AI-assisted product recognition, retailer comparison, nearby supplier leads, technical documents, embedded images, and procurement-ready Excel reports.</p></div>""", unsafe_allow_html=True)

    serpapi_api_key, openai_api_key = _resolve_api_keys(config)

    with st.sidebar:
        st.divider()
        st.header("Search settings")
        location = st.text_input("City, state, or ZIP", value=config.default_location)
        include_online = st.checkbox("Online and shipping listings", value=True)
        include_nearby = st.checkbox("Nearby retailer leads", value=True)
        include_specs = st.checkbox("Spec sheets, manuals, warranty, parts, and CAD/BIM links", value=True)
        max_product_results = st.slider("Listings per search term", min_value=3, max_value=20, value=8)
        max_store_results = st.slider("Nearby stores per search term", min_value=1, max_value=10, value=4)
        max_spec_results = st.slider("Technical documents per search term", min_value=1, max_value=8, value=3)
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
            barcode_searches = st.text_input("Optional UPC / barcode / manufacturer part number", placeholder="012345678905 or JOSAM 30000-5A-Z")
            text_searches = st.text_area(
                "Text searches, one per line",
                value=st.session_state.get("project_search_queries", ""),
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

    product_results = rank_product_matches(_dedupe_products(product_results))
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

    st.success(f"Search complete. Your workbook will download as **{filename}**.")
    best_count = sum(1 for item in product_results if item.best_match)
    if best_count:
        st.info(
            f"Best Match ranked {best_count} search group(s). Scores compare the requested model, manufacturer, "
            "dimensions, materials, connections, finish, and accessories against each listing. Always verify the official spec sheet before ordering."
        )
    history_item = {"file": filename, "inputs": len(input_records), "listings": len(product_results), "stores": len(store_results), "documents": len(spec_documents)}
    st.session_state.setdefault("search_history", []).insert(0, history_item)
    st.session_state["search_history"] = st.session_state["search_history"][:10]
    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Inputs", len(input_records))
    metric_two.metric("Product listings", len(product_results))
    metric_three.metric("Nearby retailers", len(store_results))
    metric_four.metric("Technical documents", len(spec_documents))

    _show_product_results(product_results)
    _show_store_results(store_results)
    _show_spec_documents(spec_documents)

    st.download_button(
        f"Download {filename}",
        data=workbook_bytes,
        file_name=filename,
        mime=EXCEL_MIME,
        type="primary",
        use_container_width=True,
        on_click="ignore",
    )


if __name__ == "__main__":
    main()
