from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
import os
import time

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import ApprovalUpdate, ResearchJob, ResearchRequest
from api.store import create_job, get_job, kb, run_research_job


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Product Hunter API",
    version="33.0.0",
    description="Phase 2 API for the Product Hunter React client.",
    lifespan=lifespan,
)

origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "product-hunter-api",
        "version": "33.0.0",
        "database": str(Path(kb.path)),
        "timestamp": time.time(),
    }


@app.get("/api/dashboard")
def dashboard() -> dict:
    products = kb.list_verified_products(limit=500)
    runs = kb.list_research_runs(limit=250)
    cached = kb.list_cached_research(limit=250)
    return {
        "metrics": {
            "verifiedProducts": len(products),
            "researchRuns": len(runs),
            "cachedQueries": len(cached),
            "needsReview": sum(1 for p in products if p.get("status") == "Needs review"),
        },
        "recentRuns": runs[:10],
        "recentProducts": products[:8],
    }


@app.get("/api/products")
def products(limit: int = 250) -> list[dict]:
    return kb.list_verified_products(limit=max(1, min(limit, 1000)))


@app.get("/api/products/{product_key}")
def product(product_key: str) -> dict:
    item = kb.get_verified_product(product_key)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    item["events"] = kb.list_product_events(product_key)
    item["notesHistory"] = kb.list_product_notes(product_key)
    return item


@app.patch("/api/products/{product_key}/approval")
def update_approval(product_key: str, body: ApprovalUpdate) -> dict:
    item = kb.get_verified_product(product_key)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    kb.upsert_verified_product(
        product_key=product_key,
        manufacturer=item.get("manufacturer", ""),
        model=item.get("model", ""),
        title=item.get("title", ""),
        status=body.status,
        notes=body.notes,
        evidence=item.get("evidence", []),
    )
    kb.add_product_event(product_key, body.status, body.notes, body.actor)
    return kb.get_verified_product(product_key) or {}


@app.post("/api/research", response_model=ResearchJob, status_code=202)
def research(body: ResearchRequest, background_tasks: BackgroundTasks) -> dict:
    job = create_job(body.query)
    background_tasks.add_task(run_research_job, job["id"], body.model_dump())
    return job


@app.get("/api/research/{job_id}", response_model=ResearchJob)
def research_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")
    return job
