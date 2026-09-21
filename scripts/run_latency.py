"""CASE 1. Прогон нагрузки и расчёт latency-метрик."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import charts, metrics, pipeline, storage  # noqa: E402
from app.config import ALERT_P95_MS, ALERT_P99_MS, DATA_DIR, REPORTS_DIR  # noqa: E402

BASELINE = "latency_baseline"
SLOW = "latency_slow"

SLOW_PROMPTS = [
    "Разбери по шагам, как устроен мониторинг latency в LLM-сервисе, и предложи метрики. Ответ развёрнутый, не менее 10 пунктов.",
    "Составь подробный план расследования роста p99 с проверкой каждого этапа пайплайна. Ответ развёрнутый, не менее 10 пунктов.",
    "Объясни развёрнуто, как контекст влияет на время ответа и на стоимость запроса. Ответ развёрнутый, не менее 10 пунктов.",
    "Опиши полный чеклист подготовки RAG-пайплайна к продакшену. Ответ развёрнутый, не менее 10 пунктов.",
    "Сравни стратегии кэширования ответов и дай рекомендации по каждой. Ответ развёрнутый, не менее 10 пунктов.",
]


def run_phase(prompts: list[dict], scenario: str, num_predict: int,
              padding: int = 0) -> list[dict]:
    rows = []
    for index, item in enumerate(prompts, start=1):
        record = pipeline.run(
            item["prompt"],
            endpoint=item.get("endpoint", "chat"),
            scenario=scenario,
            num_predict=num_predict,
            padding_tokens=padding,
        )
        rows.append(record)
        print(f"[{scenario}] {index}/{len(prompts)} "
              f"{record['endpoint']:<7} {record['latency_ms']:>9.1f} ms "
              f"in={record['input_tokens']:<5} out={record['output_tokens']}")
    return rows


def draw_histogram(baseline: list[float], slow: list[float]) -> None:
    fig, ax = charts.new_figure(8.2, 4.0)
    ax.hist(baseline, bins=18, color=charts.ACCENT, alpha=0.85, label="обычные запросы")
    if slow:
        ax.hist(slow, bins=8, color=charts.DANGER, alpha=0.8, label="медленные запросы")
    ax.set_xlabel("latency, ms")
    ax.set_ylabel("количество запросов")
    ax.set_title("Распределение latency")
    ax.legend()
    charts.save(fig, "latency_hist.png")


def draw_percentiles(before: dict, after: dict) -> None:
    keys = ["avg", "p50", "p95", "p99", "max"]
    fig, ax = charts.new_figure(7.6, 4.0)
    x = range(len(keys))
    width = 0.38
    ax.bar([i - width / 2 for i in x], [before[k] for k in keys], width,
           color=charts.ACCENT, label="без медленных запросов")
    ax.bar([i + width / 2 for i in x], [after[k] for k in keys], width,
           color=charts.WARN, label="с медленными запросами")
    ax.set_xticks(list(x))
    ax.set_xticklabels([k.upper() for k in keys])
    ax.set_ylabel("latency, ms")
    ax.set_title("Влияние медленных запросов на метрики")
    ax.legend()
    charts.save(fig, "latency_percentiles.png")


def draw_stages(stages: list[dict]) -> None:
    fig, ax = charts.new_figure(7.6, 3.6)
    names = [s["stage"] for s in stages][::-1]
    values = [s["avg_ms"] for s in stages][::-1]
    colors = [charts.DANGER if v == max(values) else charts.ACCENT_2 for v in values]
    ax.barh(names, values, color=colors)
    ax.set_xscale("log")
    ax.set_xlabel("среднее время, ms (лог. шкала)")
    ax.set_title("Этапы пайплайна")
    charts.save(fig, "latency_stages.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="CASE 1: latency")
    parser.add_argument("--requests", type=int, default=36, help="сколько обычных запросов")
    parser.add_argument("--slow", type=int, default=5, help="сколько медленных запросов")
    parser.add_argument("--num-predict", type=int, default=160)
    parser.add_argument("--recalc", action="store_true",
                        help="не вызывать модель, пересчитать метрики по базе")
    args = parser.parse_args()

    storage.init_db()

    if not args.recalc:
        with open(DATA_DIR / "prompts.json", encoding="utf-8") as fh:
            prompts = json.load(fh)[:args.requests]
        run_phase(prompts, BASELINE, args.num_predict)
        slow_prompts = [{"prompt": p, "endpoint": "rag"} for p in SLOW_PROMPTS[:args.slow]]
        run_phase(slow_prompts, SLOW, num_predict=800, padding=4500)

    baseline_rows = storage.fetch(scenario=BASELINE)
    slow_rows = storage.fetch(scenario=SLOW)
    baseline_values = [r["latency_ms"] for r in baseline_rows]
    slow_values = [r["latency_ms"] for r in slow_rows]

    baseline_metrics = metrics.summary(baseline_values)
    mixed_metrics = metrics.summary(baseline_values + slow_values)
    stages = metrics.stage_breakdown(baseline_rows)

    report = {
        "baseline": baseline_metrics,
        "with_slow_requests": mixed_metrics,
        "comparison": metrics.compare(baseline_metrics, mixed_metrics),
        "by_endpoint": metrics.group_summary(baseline_rows, "endpoint"),
        "stages": stages,
        "slowest_stage": stages[0]["stage"] if stages else None,
        "histogram": metrics.histogram(baseline_values, bins=18),
        "alert": {
            "rule": (
                f"p95 (окно 5 минут) > {ALERT_P95_MS} ms в течение 10 минут "
                f"или p99 > {ALERT_P99_MS} ms в течение 5 минут"
            ),
            "state_baseline": metrics.alert_state(baseline_metrics),
            "state_with_slow": metrics.alert_state(mixed_metrics),
        },
        "production_metrics": ["p50", "p95", "p99", "error_rate", "tokens_per_second"],
    }

    (REPORTS_DIR / "latency_metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    storage.export_csv(REPORTS_DIR / "telemetry.csv")

    draw_histogram(baseline_values, slow_values)
    draw_percentiles(baseline_metrics, mixed_metrics)
    draw_stages(stages)

    print("\nБазовая выборка:", baseline_metrics)
    print("С медленными запросами:", mixed_metrics)
    print("Самый медленный этап:", report["slowest_stage"])


if __name__ == "__main__":
    main()
