# Product Hunter Pro v28 — Search Reliability and Provider Resilience

This release prevents SearXNG engine outages from appearing as legitimate zero-result product searches.

## Critical fixes

- Reads and reports SearXNG `unresponsive_engines` details.
- Distinguishes rate limits, access denials, timeouts, invalid JSON, and true no-match searches.
- Runs one minimal circuit-breaker request before launching expanded procurement searches.
- Stops the expanded search fan-out when upstream engines are unavailable.
- Never caches empty provider-outage responses.
- Uses expired cached evidence when live providers fail and verified prior research exists.
- Records research runs as `Provider outage`, `Stale cache fallback`, `No matching results`, or `Completed`.
- Shows raw-result, normalized-result, request-count, and engine-health diagnostics.
- Improves the SearXNG health check so a reachable server with blocked engines is reported as degraded.
- Updates user-facing messaging so an outage is not presented as proof that a product does not exist.

## Deployment

1. Extract the ZIP.
2. Upload all files inside `product_hunter_webapp_v28` to the root of `item-tracker1`.
3. Replace the prior files and commit the changes.
4. Reboot the Streamlit app.

Existing OpenAI and SearXNG secrets remain unchanged.
