# Product Hunter Pro v31.2

## RFQ navigation hotfix

The v31 ribbon looked interactive but was rendered as decorative HTML spans. v31.2 replaces it with real Streamlit navigation and connects every command to a working view.

### Working destinations

- RFQ Home
- Create RFQ
- Import Quotes
- Compare
- Award Review
- Bid Tab
- Export
- Audit

### Additional fixes

- Imported quotes remain available while moving between RFQ Center pages.
- Comparison, award review, bid-tab generation, and exports reuse the same normalized quote data.
- RFQ and quote actions are recorded in a session audit table.
- Empty states explain what data is required instead of showing inactive controls.
- Added regression tests to prevent decorative ribbon controls from returning.

No Streamlit secret changes are required.
