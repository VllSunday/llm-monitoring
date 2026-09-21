"""Детектор дрейфа по категориальным и числовым признакам."""
import math

from app.config import DRIFT_LENGTH_WARN, DRIFT_PSI_ALERT, DRIFT_PSI_WARN

EPS = 1e-6


def normalize_dist(dist: dict[str, float]) -> dict[str, float]:
    total = sum(dist.values()) or 1.0
    return {key: value / total for key, value in dist.items()}


def psi(baseline: dict[str, float], production: dict[str, float]) -> float:
    """Population Stability Index по категориям."""
    base = normalize_dist(baseline)
    prod = normalize_dist(production)
    value = 0.0
    for key in set(base) | set(prod):
        b = max(base.get(key, 0.0), EPS)
        p = max(prod.get(key, 0.0), EPS)
        value += (p - b) * math.log(p / b)
    return round(value, 4)


def jensen_shannon(baseline: dict[str, float], production: dict[str, float]) -> float:
    base = normalize_dist(baseline)
    prod = normalize_dist(production)
    keys = set(base) | set(prod)
    divergence = 0.0
    for key in keys:
        b = max(base.get(key, 0.0), EPS)
        p = max(prod.get(key, 0.0), EPS)
        m = (b + p) / 2
        divergence += 0.5 * b * math.log(b / m) + 0.5 * p * math.log(p / m)
    return round(math.sqrt(max(divergence, 0.0)), 4)


def total_variation(baseline: dict[str, float], production: dict[str, float]) -> float:
    base = normalize_dist(baseline)
    prod = normalize_dist(production)
    keys = set(base) | set(prod)
    return round(0.5 * sum(abs(prod.get(k, 0.0) - base.get(k, 0.0)) for k in keys), 4)


def categorical_report(name: str, baseline: dict[str, float],
                       production: dict[str, float]) -> dict:
    base = normalize_dist(baseline)
    prod = normalize_dist(production)
    score = psi(base, prod)
    shifts = {
        key: round((prod.get(key, 0.0) - base.get(key, 0.0)) * 100, 2)
        for key in sorted(set(base) | set(prod))
    }
    top = max(shifts, key=lambda k: abs(shifts[k])) if shifts else None
    return {
        "feature": name,
        "type": "categorical",
        "psi": score,
        "js_distance": jensen_shannon(base, prod),
        "total_variation": total_variation(base, prod),
        "baseline": {k: round(v, 4) for k, v in base.items()},
        "production": {k: round(v, 4) for k, v in prod.items()},
        "shift_pp": shifts,
        "top_shift": top,
        "status": status_from_psi(score),
    }


def numeric_report(name: str, baseline_mean: float, production_mean: float,
                   baseline_std: float | None = None) -> dict:
    delta = production_mean - baseline_mean
    rel = delta / baseline_mean if baseline_mean else 0.0
    effect = abs(delta) / baseline_std if baseline_std else None
    if abs(rel) >= DRIFT_LENGTH_WARN * 2:
        status = "alert"
    elif abs(rel) >= DRIFT_LENGTH_WARN:
        status = "warn"
    else:
        status = "ok"
    return {
        "feature": name,
        "type": "numeric",
        "baseline_mean": baseline_mean,
        "production_mean": production_mean,
        "delta": round(delta, 2),
        "delta_pct": round(rel * 100, 1),
        "effect_size": round(effect, 2) if effect else None,
        "status": status,
    }


def status_from_psi(value: float) -> str:
    if value >= DRIFT_PSI_ALERT:
        return "alert"
    if value >= DRIFT_PSI_WARN:
        return "warn"
    return "ok"


def detect(baseline: dict, production: dict) -> dict:
    """Общий отчёт по набору признаков.

    Ожидает структуру вида
    {"language": {...}, "topic": {...}, "query_length_tokens": 42}
    """
    features = []
    for key, base_value in baseline.items():
        prod_value = production.get(key)
        if prod_value is None:
            continue
        if isinstance(base_value, dict):
            features.append(categorical_report(key, base_value, prod_value))
        else:
            features.append(numeric_report(key, float(base_value), float(prod_value)))

    worst = "ok"
    for feature in features:
        if feature["status"] == "alert":
            worst = "alert"
            break
        if feature["status"] == "warn":
            worst = "warn"
    features.sort(key=lambda f: f.get("psi") or abs(f.get("delta_pct", 0)) / 100, reverse=True)
    return {
        "features": features,
        "status": worst,
        "thresholds": {
            "psi_warn": DRIFT_PSI_WARN,
            "psi_alert": DRIFT_PSI_ALERT,
            "length_warn_rel": DRIFT_LENGTH_WARN,
        },
    }


def distribution_from_rows(rows: list[dict], field: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for row in rows:
        counts[str(row.get(field))] = counts.get(str(row.get(field)), 0.0) + 1
    return normalize_dist(counts) if counts else {}
