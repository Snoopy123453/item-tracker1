# Upgrade to Product Hunter Pro v7

## New Project Intelligence workspace

- Create project records with project number, client, and buyer.
- Upload schedule PDFs with selectable text, images, TXT, and CSV files.
- AI extraction of item tags, manufacturers, exact models, descriptions, quantities, locations, and source pages.
- Editable equipment register with approval and procurement statuses.
- Duplicate consolidation that preserves tags, locations, files, and quantities.
- Project purchasing rules: exact-model requirement, official-source preference, refurbished-product rejection, equivalent-product permission, minimum score, and procurement priority.
- Import vendor quote spreadsheets or CSV files for side-by-side review.
- Download and restore a JSON project backup.
- Export a polished project procurement workbook.
- Build a submittal ZIP containing the project workbook, document manifest, and downloadable public PDFs.
- Send equipment-register search terms into the existing Product Search workspace.

## Deploy

1. Extract the ZIP.
2. Upload all contents to the top level of the existing GitHub repository, replacing older files.
3. Commit the changes.
4. Reboot the Streamlit app.
5. Streamlit will install the new `pypdf` dependency from `requirements.txt`.

Existing Streamlit secrets remain unchanged.

## PDF limitation

Text-based PDFs are supported directly. Scanned PDFs with no selectable text should be exported as PNG/JPG schedule pages and uploaded as images. Very large drawing sets should be divided into schedule pages to control API usage and improve accuracy.
