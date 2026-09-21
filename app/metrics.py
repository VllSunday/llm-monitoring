"""Агрегация телеметрии: перцентили, гистограммы, разбивка по этапам."""
from statistics import mean, pstdev

from app.config import ALERT_P95_MS, ALERT_P99_MS


def percentile(values: list[float], q: float) -> float:
    """Перцентиль методом nearest-rank, чтобы совпадало с расчётом в дашбордах."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-q * len(ordered) // 1))))
    return ordered[rank - 1]


def summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "avg": round(mean(values), 2),
        "p50": round(percentile(values, 0.50), 2),
        "p95": round(percentile(values, 0.95), 2),
        "p99": round(percentile(values, 0.99), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "std": round(pstdev(values), 2) if len(values) > 1 else 0.0,
    }


def histogram(values: list[float], bins: int = 20) -> dict:
    if not values:
        return {"edges": [], "counts": []}
    low, high = min(values), max(values)
    if high == low:
        high = low + 1
    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        index = min(bins - 1, int((value - low) / width))
        counts[index] += 1
    edges = [round(low + i * width, 2) for i in range(bins + 1)]
    return {"edges": edges, "counts": counts}


def stage_breakdown(rows: list[dict]) -> list[dict]:
    totals: dict[str, list[float]] = {}
    for row in rows:
        for stage, value in (row.get("stages") or {}).items():
            totals.setdefault(stage, []).append(value)
    overall = sum(mean(v) for v in totals.values()) or 1.0
    result = [
        {
            "stage": stage,
            "avg_ms": round(mean(values), 3),
            "p95_ms": round(percentile(values, 0.95), 3),
            "share": round(mean(values) / overall, 4),
        }
        for stage, values in totals.items()
    ]
    result.sort(key=lambda item: item["avg_ms"], reverse=True)
    return result


def group_summary(rows: list[dict], key: str, value_field: str = "latency_ms") -> dict:
    groups: dict[str, list[float]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key)), []).append(float(row[value_field]))
    return {name: summary(values) for name, values in groups.items()}


def alert_state(metrics: dict, p95_threshold: float = ALERT_P95_MS,
                p99_threshold: float = ALERT_P99_MS) -> dict:
    breached = []
    if metrics.get("p95", 0) > p95_threshold:
        breached.append(f"p95={metrics['p95']} ms > {p95_threshold} ms")
    if metrics.get("p99", 0) > p99_threshold:
        breached.append(f"p99={metrics['p99']} ms > {p99_threshold} ms")
    return {
        "firing": bool(breached),
        "reasons": breached,
        "p95_threshold": p95_threshold,
        "p99_threshold": p99_threshold,
    }


def compare(before: dict, after: dict) -> dict:
    keys = ("avg", "p50", "p95", "p99", "max")
    return {
        key: {
            "before": before.get(key),
            "after": after.get(key),
            "delta": round(after.get(key, 0) - before.get(key, 0), 2),
            "delta_pct": round(
                (after.get(key, 0) - before.get(key, 0)) / before[key] * 100, 1
            ) if before.get(key) else None,
        }
        for key in keys
    }
