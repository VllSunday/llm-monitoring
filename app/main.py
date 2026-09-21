"""API-сервис и дашборд мониторинга."""
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import drift, llm, metrics, pipeline, storage
from app.config import ENDPOINTS, MODEL, REPORTS_DIR, WEB_DIR
from app.textutils import estimate_tokens

app = FastAPI(title="LLM Monitoring", version="1.0.0")

REPORT_FILES = {
    "latency": "latency_metrics.json",
    "cost": "cost_analysis.json",
    "drift": "drift_report.json",
    "eval": "eval_results.json",
}


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    endpoint: str = "chat"
    num_predict: int = Field(default=160, ge=16, le=1024)


@app.on_event("startup")
def startup() -> None:
    storage.init_db()


@app.get("/api/health")
def health() -> dict:
    available = llm.is_available()
    return {
        "ollama": available,
        "model": MODEL,
        "models": llm.list_models() if available else [],
        "requests_stored": storage.count(),
    }


@app.post("/api/generate")
def generate(payload: GenerateRequest) -> dict:
    if payload.endpoint not in ENDPOINTS:
        raise HTTPException(400, f"Неизвестный эндпоинт, доступны: {', '.join(ENDPOINTS)}")
    try:
        record = pipeline.run(payload.prompt, endpoint=payload.endpoint,
                              scenario="ui", num_predict=payload.num_predict)
    except llm.LLMUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return record


@app.get("/api/telemetry")
def telemetry(limit: int = 50, scenario: str | None = None) -> dict:
    rows = storage.fetch(limit=limit, scenario=scenario)
    return {"rows": rows, "total": storage.count()}


@app.get("/api/overview")
def overview() -> dict:
    rows = storage.fetch()
    latencies = [row["latency_ms"] for row in rows]
    summary = metrics.summary(latencies)
    eval_report = _read_report("eval")
    drift_report = _read_report("drift")
    return {
        "requests": len(rows),
        "latency": summary,
        "alert": metrics.alert_state(summary) if summary.get("count") else None,
        "total_cost_usd": round(sum(row["cost_usd"] for row in rows), 6),
        "tokens": {
            "input": sum(row["input_tokens"] for row in rows),
            "output": sum(row["output_tokens"] for row in rows),
        },
        "stages": metrics.stage_breakdown(rows),
        "by_endpoint": metrics.group_summary(rows, "endpoint"),
        "languages": drift.distribution_from_rows(rows, "language"),
        "topics": drift.distribution_from_rows(rows, "topic"),
        "hallucination_rate": (eval_report or {}).get("summary", {}).get("hallucination_rate"),
        "drift_status": (drift_report or {}).get("drift", {}).get("status"),
    }


@app.get("/api/drift/live")
def drift_live() -> dict:
    report = _read_report("drift")
    if not report:
        raise HTTPException(404, "Сначала запустите scripts/run_drift.py")
    rows = storage.fetch()
    if len(rows) < 10:
        return {"status": "no_data", "sample_size": len(rows)}
    lengths = [estimate_tokens(row["prompt"]) for row in rows]
    live = {
        "language": drift.distribution_from_rows(rows, "language"),
        "topic": drift.distribution_from_rows(rows, "topic"),
        "query_length_tokens": sum(lengths) / len(lengths),
    }
    result = drift.detect(report["baseline"], live)
    result["sample_size"] = len(rows)
    return result


@app.get("/api/report/{name}")
def report(name: str) -> JSONResponse:
    data = _read_report(name)
    if data is None:
        raise HTTPException(404, f"Отчёт {name} не найден, запустите соответствующий скрипт")
    return JSONResponse(data)


def _read_report(name: str) -> dict | None:
    filename = REPORT_FILES.get(name)
    if not filename:
        return None
    path = REPORTS_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
