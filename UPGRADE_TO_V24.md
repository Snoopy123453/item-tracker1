# Product Hunter Pro v24 — Resource Optimization Patch

## What changed

- Added Efficient, Balanced, and Thorough resource profiles.
- Added bounded SearXNG concurrency and per-product query budgets.
- Added configurable research-cache lifetime.
- Added shorter, configurable provider timeouts.
- Added expired-cache fallback when live search providers are unavailable.
- Deep research is now positioned as an escalation path instead of the default.
- Added a visible resource-plan summary in the sidebar.
- Updated all interface version labels to v24.

## Recommended Streamlit secrets

```toml
RESOURCE_PROFILE = "Balanced"
RESEARCH_CACHE_HOURS = 72
SEARCH_MAX_WORKERS = 3
SEARCH_QUERY_BUDGET = 10
SEARCH_REQUEST_TIMEOUT = 45
```

Your existing OpenAI and SearXNG secrets do not change. Upload all files in this folder to the root of the GitHub repository, replace the older version, commit, and reboot Streamlit.
