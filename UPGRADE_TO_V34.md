# Product Hunter Pro v34 — Direct Research Independence

## Purpose

v34 removes SearXNG as a critical single point of failure. SearXNG remains an optional discovery provider, but research can now continue through direct manufacturer evidence, the Product Intelligence Database, and an isolated keyless discovery fallback.

## Added

- Direct manufacturer-domain inference for recognized brands.
- Official sitemap research that can locate exact model pages and PDFs without a metasearch engine.
- Knowledge-base and verified-domain results remain first in the research plan.
- Independent Bing RSS fallback, isolated from SearXNG.
- Provider-level health reporting for direct manufacturer research and RSS discovery.
- Honest official-site search leads when an exact model page cannot be verified.
- Bounded requests and one-level sitemap expansion to protect Render resources.
- Exact model preservation for manufacturer and document discovery.

## Behavior during SearXNG outages

When SearXNG engines are blocked or CAPTCHA-protected, Product Hunter now attempts:

1. Product Intelligence Database evidence.
2. Previously verified manufacturer domains.
3. Direct official sitemap discovery.
4. Other configured providers.
5. A bounded Bing RSS discovery fallback when no exact result exists.

A SearXNG outage is no longer enough by itself to force a zero-result research session.

## Deployment

Upload all files in this release to the root of `item-tracker1`, replace older files, commit, and reboot Streamlit. Existing secrets remain valid. SearXNG may remain configured as an optional provider.
