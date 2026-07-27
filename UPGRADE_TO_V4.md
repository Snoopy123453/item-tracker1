# Upgrade to Product Hunter Pro v4

Version 4 adds a **Purchase Tracker** workspace.

## New workflow

1. Run a normal product search and download the initial Excel report.
2. Open **Purchase Tracker** from the app sidebar.
3. Upload the original Product Hunter Excel file.
4. Select the retailer links you plan to purchase from.
5. Adjust quantities and unit prices, then add the project, buyer, and notes.
6. Download a separate purchasing workbook.

The tracker includes Dashboard, Purchase List, and Instructions sheets. It tracks planned and purchased totals, quantities, shipping, tax, order numbers, expected and received dates, payment method, cost code, purchaser, status, and received quantity.

## Deploy

Upload all v4 files to the root of the existing GitHub repository, replace the older files, commit the changes, and reboot the Streamlit app. Existing Streamlit Secrets remain unchanged.
