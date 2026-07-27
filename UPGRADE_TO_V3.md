# Upgrade the existing Streamlit app to Version 3

1. Extract `product_hunter_webapp_v3.zip`.
2. Open the extracted `product_hunter_webapp` folder.
3. In GitHub, open `Snoopy123453/item-tracker1`.
4. Upload all files and folders from inside `product_hunter_webapp` and allow GitHub to replace matching files.
5. Commit the changes.
6. In Streamlit Community Cloud, open **Manage app** and select **Reboot app**.

Your Streamlit Secrets remain on Streamlit and should not be uploaded to GitHub.

## New behavior

- A search for `JOSAM 30000-5A-Z` downloads as `JOSAM_30000-5A-Z.xlsx`.
- One recognized product uses that product name for the workbook.
- Two products use both names.
- Larger mixed searches use a descriptive procurement-report name.
- The workbook now includes Summary, Inputs, Product Results, Nearby Stores, Spec Documents, Price Comparison, and Review Notes.
