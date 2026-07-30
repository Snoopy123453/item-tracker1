# Product Hunter v33 — Phase 2 React Migration

This release starts the customer-facing migration without deleting the existing Streamlit app.

## New architecture

- `web/`: Next.js App Router + React + TypeScript client
- `api/`: FastAPI service exposing Product Hunter data and research jobs
- `app.py`: existing Streamlit admin and fallback interface
- `product_finder/`: shared business logic used by both interfaces

## Working React areas

- Enterprise application shell and navigation
- Executive dashboard backed by FastAPI
- Background research job creation and polling
- Evidence results table
- Product intelligence list
- Placeholder routes for Projects, RFQ, and System migration

## Local or server deployment

Use `docker-compose.phase2.yml` on a server. Nothing needs to be installed on the work computer; users only need a browser.

```bash
docker compose -f docker-compose.phase2.yml up --build
```

Open React at `http://server:3000` and FastAPI docs at `http://server:8000/docs`.

## Render deployment

Deploy two services from the same GitHub repository:

1. API web service using `api.Dockerfile`
2. React web service with root directory `web` and its `Dockerfile`

Set the React environment variable `NEXT_PUBLIC_API_URL` to the public API URL. Set API `CORS_ORIGINS` to the public React URL.

## Migration safety

Do not remove Streamlit yet. It remains the complete operational interface while React screens are migrated and validated one workflow at a time.
