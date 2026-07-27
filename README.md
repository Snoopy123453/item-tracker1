# Product Hunter Pro v8

A browser-based product sourcing, project procurement, purchasing, and control application built with Streamlit.

## Workspaces

- Product Search
- Project Intelligence
- Procurement Control Center
- Purchase Tracker

## v8 highlights

The Procurement Control Center adds hard requirement gates, specification comparisons, package completeness, duplicate grouping, delivered-cost calculations, review queues, data-health checks, document registers, vendor scorecards, receiving logs, audit history, and draft PO exports.

Product Hunter turns typed descriptions, uploaded photos, and public image URLs into retailer searches. It shows online/shipping listings and nearby retailer leads, then creates a formatted Excel workbook for download.

## Main capabilities

- Search by text, local image upload, or public image URL.
- Recognize uploaded products with OpenAI vision.
- Use Google Lens for public image URLs through SerpApi.
- Find online product listings through Google Shopping results.
- Find nearby retailer leads through Google Maps results.
- Download an Excel workbook containing a summary, recognized inputs, product listings, source links, and nearby stores.
- Run as a password-protected hosted web app from any browser.

## Hosted-app safeguards

- API keys remain server-side and are not displayed in the app.
- Server keys are disabled by default on an unprotected public deployment.
- Uploaded images are resized and re-encoded without EXIF metadata.
- Spreadsheet downloads are generated in memory for multi-user hosting.
- Web text is escaped before Excel export to reduce formula-injection risk.
- Per-run input and search-job limits help control API usage.

## Fastest deployment

Read [`DEPLOYMENT.md`](DEPLOYMENT.md). The recommended route is Streamlit Community Cloud using a private GitHub repository and the included secrets template. Render deployment files are also included.

## Local Windows use

1. Install Python 3.10 or newer.
2. Unzip this folder.
3. Double-click `run_windows.bat`.
4. Edit the generated `.env` with your real keys and password.
5. Run `run_windows.bat` again.

## Manual local setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

python -m pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

## Configuration

| Setting | Purpose |
|---|---|
| `SERPAPI_API_KEY` | Required for live product, Google Lens URL, and nearby-store searches. |
| `OPENAI_API_KEY` | Required only for recognition of locally uploaded images. |
| `APP_PASSWORD` | Recommended access password for hosted use. |
| `OPENAI_MODEL` | Vision-capable model used for uploaded images. |
| `DEFAULT_LOCATION` | Initial city/state/ZIP for nearby searches. |
| `ALLOW_USER_API_KEYS` | Lets users provide alternate keys in the browser when true. |
| `ALLOW_PUBLIC_WITH_SERVER_KEYS` | Explicitly permits an unprotected public app to spend server API keys. Keep false. |
| `MAX_UPLOAD_MB` | Maximum size of each image after upload validation. |
| `MAX_INPUTS` | Maximum combined text, image, and image-URL inputs per run. |
| `MAX_SEARCH_JOBS` | Maximum generated retailer search jobs per run. |

## Excel output

The workbook contains:

- **Summary**: run counts, location, notes, and inventory warning.
- **Inputs**: typed inputs, image recognition, confidence, and generated searches.
- **Product Results**: seller, price, delivery, rating, links, thumbnails, and source.
- **Nearby Stores**: address, phone, hours, website, directions, map links, and source.

## Important limitations

Nearby results identify possible retailers; they do not guarantee live shelf inventory. Prices, shipping, stock, ratings, and seller information can change. Verify each listing before purchasing.

Uploaded images and search requests are sent to configured external API providers. Do not upload confidential work material unless your employer allows it.

## Provider documentation

- OpenAI image and vision input documentation: https://developers.openai.com/api/docs/guides/images-vision
- SerpApi Google Lens API: https://serpapi.com/google-lens-api
- SerpApi Google Shopping API: https://serpapi.com/google-shopping-api
- SerpApi Google Maps local results: https://serpapi.com/maps-local-results

## Version 2 enhancements

- Product thumbnails are downloaded server-side and embedded directly in the Excel `Product Results` sheet when available.
- The workbook includes a redesigned dashboard, alternating row shading, better sizing, clickable links, and a dedicated `Spec Documents` sheet.
- Optional technical-document search finds likely product spec sheets, submittals, installation manuals, and other PDFs through SerpApi Google Search.
- The Streamlit interface includes a polished branded header, improved cards, and clearer search controls.

To update an existing Streamlit deployment, upload all files from this project over the matching files in the GitHub repository, commit the changes, and reboot the app. Existing Streamlit secrets remain in the hosting dashboard and should not be committed to GitHub.

## Version 3 procurement report upgrades

- Excel filenames are based on the recognized/searched product instead of the date.
- Product images are embedded in the workbook when the source thumbnail is available.
- Added a price-comparison worksheet and a procurement review checklist.
- Technical-document search now also looks for warranty, parts diagrams, and CAD/BIM/Revit resources.
- Added an optional UPC/barcode/manufacturer-part-number input.
- Added lightweight recent-search history for the active browser session.

Live shelf inventory, authenticated distributor pricing, discontinued-status confirmation, and approved-equivalent recommendations require retailer/manufacturer-specific APIs or accounts. The app labels nearby results and document matches as leads that must be verified before ordering.


## Project Intelligence (v7)

The third workspace adds schedule extraction, an editable equipment register, duplicate consolidation, project rules, quote review, JSON backup/restore, project Excel exports, and submittal ZIP creation.
## v10: Spec Sheet Compare

The Spec Sheet Compare workspace accepts one original required document and multiple candidate documents. It extracts structured technical attributes, normalizes equivalent terminology, detects hard conflicts, measures evidence coverage, ranks candidates, and exports an evidence-backed Excel comparison report.
