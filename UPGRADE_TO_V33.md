# Upgrade to v33 — Phase 2 React Foundation

v33 begins Phase 2 by adding a real React customer interface and FastAPI backend while retaining the Streamlit app.

## Included

- Next.js App Router frontend with TypeScript
- Professional left navigation and sticky command header
- Dashboard API and React dashboard
- Background research job API and live polling UI
- Product intelligence API and grid
- CORS configuration
- Docker files for independent frontend/backend deployment
- Existing product logic reused through `product_finder`

## Why both interfaces remain

The React client is now the migration target. Streamlit remains the stable admin/fallback console until feature parity is reached.

## Next update — v34

- Full Projects workflow in React
- RFQ & Quote Center migration
- Product details inspector
- Authentication foundation
- PostgreSQL adapter interface
