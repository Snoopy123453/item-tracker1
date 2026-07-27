# Upgrade to Product Hunter Pro v6

Version 6 replaces the fixed construction-oriented match formula with an adaptive hybrid scoring engine.

## Improvements

- Detects product category before scoring: electronics, plumbing, tools, appliances, or general.
- Dynamically scores only relevant attributes instead of treating missing irrelevant fields as failures.
- Recognizes consumer product families such as iPhone 15 Pro, Galaxy S24 Ultra, Pixel, and MacBook models.
- Normalizes punctuation, storage units, no-hub terminology, Nickaloy spelling, and common condition wording.
- Detects wrong storage, voltage, dimensions, brand, model, and condition.
- Penalizes refurbished, used, or open-box listings when they were not requested.
- Adds Match Confidence, Match Profile, and a transparent Score Breakdown to the app and Excel workbook.
- Keeps exact manufacturer/model construction matching and specification-feature comparison.

## Deploy

Upload all files from this folder to the existing GitHub repository, replace the old files, commit, and reboot the Streamlit app.
