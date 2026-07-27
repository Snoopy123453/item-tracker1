# Upgrade to Product Hunter Pro v10

Version 10 adds a dedicated **Spec Sheet Compare** workspace.

## New workflow

1. Upload the original or required specification sheet.
2. Upload one or more candidate specification sheets.
3. Optionally enter mandatory comparison instructions.
4. Run the comparison.
5. Review candidate rankings, hard conflicts, unconfirmed requirements, page references, and evidence coverage.
6. Download the Excel comparison report.

## Verification behavior

- Missing values are marked **Not Confirmed**, never assumed to match.
- Explicit conflicts in dimensions, connections, voltage, capacity, material, finish, certifications, mounting, or required accessories reduce or disqualify a candidate.
- Results are classified as:
  - Exact Specification Match
  - Technical Equivalent
  - Needs Verification
  - Not Compatible
- The Excel report includes Comparison Summary, Spec Comparison, and Original Evidence sheets.

## Deploy

Upload all files in this package to the root of the existing GitHub repository, replace older files, commit, and reboot the Streamlit app. Existing Streamlit secrets remain unchanged.

Text-searchable PDFs work best. For scanned PDFs without selectable text, export the relevant pages as PNG or JPG and upload those images.
