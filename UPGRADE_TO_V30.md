# Product Hunter Pro v30 — Search Failover Hotfix

## What changed

- Adds bounded engine-level SearXNG failover.
- Skips engines already reported as CAPTCHA-blocked, rate-limited, or access-denied.
- Retries healthy engine pools such as Google/Bing, Qwant/Mojeek, and Yahoo.
- Limits fallback attempts to protect the Render service and avoid request storms.
- Preserves detailed diagnostics when all upstream engines remain unavailable.
- Empty outage responses are still never cached.

## Deploy

Upload all files in this folder to the root of `item-tracker1`, replace existing files, commit, and reboot Streamlit. No secret changes are required.
