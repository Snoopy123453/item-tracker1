# Product Hunter Pro v34.1 - Streamlit Search Recovery Hotfix

This hotfix stabilizes the current Streamlit application before further migration work.

## Fixes

- Adds a SearXNG cold-start wake and retry path for sleeping hosted instances.
- Uses the exact model token as the first live query instead of repeating ambiguous brand words.
- Applies one final relevance gate to every source, including Bing RSS, direct sources, live providers, and cached evidence.
- Blocks dictionary/reference domains globally from product evidence.
- Rejects model-mismatched general web pages when an exact model number is present.
- Revalidates old cached results before returning them, so previously cached dictionary pages are ignored automatically.
- Keeps honest official-manufacturer search leads when an exact official page has not yet been verified.

No Streamlit secret changes are required.
