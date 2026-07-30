# Product Hunter Pro v33 — Research Orchestrator 2.0

## What changed

- Research is now knowledge-first instead of SearXNG-first.
- Previously reviewed product evidence is returned even when live search providers are blocked.
- Exact model numbers are preserved and searched before broad keywords.
- Known manufacturer domains can be refreshed through public sitemap files without a search API.
- Search providers are isolated and receive health states, latency, result counts, and error messages.
- Expanded manufacturer, document, offer, and lifecycle searches only run after an exact query succeeds.
- A degraded provider no longer receives a burst of follow-up requests.
- Provider health and the generated research plan are returned in research metadata for diagnostics.
- SearXNG remains supported, but it is now one optional discovery provider rather than the entire research system.

## Deployment

Replace the existing repository files with this release and reboot Streamlit. Existing secrets remain valid.

Recommended provider order:

```toml
SEARCH_PROVIDER_ORDER = "searxng,serpapi"
```

SerpApi can remain blank. Product Hunter will still reuse verified evidence and known manufacturer sources when live providers are unavailable.
