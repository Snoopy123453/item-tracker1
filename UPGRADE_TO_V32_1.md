# Product Hunter Pro v32.1 - Product Relevance Hotfix

## Fixed

- Prevents dictionary and word-definition pages from appearing as product evidence.
- Preserves hyphenated manufacturer model numbers such as `USXN1824A-J` during matching.
- Searches the exact normalized model before broad web variations.
- Requires stronger query coverage before general-web pages are accepted.
- Stops ambiguous manufacturer words such as `JUST` from automatically making unrelated domains look official.
- Invalidates older cached ranking results so previously cached dictionary pages do not reappear.

## Deploy

Upload all files in this folder to the root of `item-tracker1`, replace the existing files, commit, and reboot Streamlit.

No secret changes are required.
