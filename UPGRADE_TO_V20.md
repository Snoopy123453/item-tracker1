# Product Hunter Pro v20 — Real Foundation Release

This release adds working architecture rather than only interface concepts.

## Implemented

- **AI Research Agent foundation** that wraps the modular search providers.
- **Persistent SQLite Product Intelligence Database** for cached research and reviewed products.
- **Research caching** with a 72-hour default TTL to reduce repeated SearXNG/API calls.
- **Refresh live sources** control to bypass cache when current pricing or availability matters.
- **Evidence Viewer** with source score, reliability, product match, exact-model status, official-source status, evidence explanation, and direct source link.
- **Human review workflow** to save Exact, Equivalent, Needs Review, or Rejected decisions.
- **Knowledge Base statistics** in the sidebar.
- Professional v20 command bar and workspace terminology.

## Deployment

Upload every file in this folder to the root of the existing GitHub repository and replace older files. Commit and reboot Streamlit.

No new secret is required. Existing SearXNG and OpenAI settings remain valid.

## Storage note

The SQLite database lives on the Streamlit runtime filesystem. It persists during the running deployment but Community Cloud may replace local storage during rebuilds. For permanent multi-user storage, the next backend step is PostgreSQL/Supabase.
