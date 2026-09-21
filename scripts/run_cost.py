"""CASE 2. Стоимость запросов, эксперимент с размером контекста и анализ cost leak."""
import argparse
import csv
import json
import pathlib
import sys
from statistics import mean

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import charts, pipeline, pricing, storage  # noqa: E402
from app.config import DATA_DIR, REPORTS_DIR  # noqa: E402

SCENARIO = "cost_context"
CONTEXT_SIZES = (500, 1000, 2000, 4000)
QUESTION = "Что делать при ошибке 429 и какие лимиты действуют на аккаунт?"

# Агент делает 5-7 вызовов на один пользовательский запрос
AGENT_CALLS_RANGE = (5, 7)


def run_context_experiment(repeats: int, num_predict: int) -> list[dict]:
    rows = []
    for size in CONTEXT_SIZES:
        for attempt in range(repeats):
            record = pipeline.run(
                QUESTION,
                endpoint="rag",
                scenario=SCENARIO,
                num_predict=num_predict,
                padding_tokens=size,
            )
            record["context_size"] = size
            rows.append(record)
            print(f"[context {size:>4}] {attempt + 1}/{repeats} "
                  f"{record['latency_ms']:>9.1f} ms in={record['input_tokens']} "
                  f"out={record['output_tokens']} cost={record['cost_usd']:.6f}")
    return rows


def aggregate_context(rows: list[dict]) -> list[dict]:
    result = []
    for size in CONTEXT_SIZES:
        subset = [r for r in rows if r.get("context_size") == size]
        if not subset:
            continue
        avg_in = mean(r["input_tokens"] for r in subset)
        avg_out = mean(r["output_tokens"] for r in subset)
        result.append({
            "context_size": size,
            "runs": len(subset),
            "avg_input_tokens": round(avg_in, 1),
            "avg_output_tokens": round(avg_out, 1),
            "avg_latency_ms": round(mean(r["latency_ms"] for r in subset), 1),
            "avg_cost_usd": round(mean(r["cost_usd"] for r in subset), 8),
            "cost_per_1k_requests": round(mean(r["cost_usd"] for r in subset) * 1000, 4),
        })
    return result


def load_endpoints() -> list[dict]:
    with open(DATA_DIR / "endpoints.csv", encoding="utf-8") as fh:
        return [
            {
                "endpoint": row["endpoint"],
                "requests": int(row["requests"]),
                "avg_input": int(row["avg_input"]),
                "avg_output": int(row["avg_output"]),
            }
            for row in csv.DictReader(fh)
        ]


def analyze_endpoints(rows: list[dict]) -> dict:
    naive = []
    realistic = []
    for row in rows:
        calls_low, calls_high = 1.0, 1.0
        if row["endpoint"] == "agent":
            calls_low, calls_high = AGENT_CALLS_RANGE

        naive_item = pricing.endpoint_cost(row["requests"], row["avg_input"], row["avg_output"])
        naive_item["endpoint"] = row["endpoint"]
        naive.append(naive_item)

        avg_calls = mean([calls_low, calls_high])
        real_item = pricing.endpoint_cost(row["requests"], row["avg_input"],
                                          row["avg_output"], calls_per_request=avg_calls)
        real_item["endpoint"] = row["endpoint"]
        real_item["calls_low"] = calls_low
        real_item["calls_high"] = calls_high
        real_item["cost_low"] = pricing.endpoint_cost(
            row["requests"], row["avg_input"], row["avg_output"], calls_low)["total_cost"]
        real_item["cost_high"] = pricing.endpoint_cost(
            row["requests"], row["avg_input"], row["avg_output"], calls_high)["total_cost"]
        realistic.append(real_item)

    total_naive = sum(item["total_cost"] for item in naive)
    total_real = sum(item["total_cost"] for item in realistic)
    leader = max(realistic, key=lambda item: item["total_cost"])
    for item in naive:
        item["share"] = round(item["total_cost"] / total_naive, 4)
    for item in realistic:
        item["share"] = round(item["total_cost"] / total_real, 4)

    return {
        "naive": naive,
        "with_agent_fanout": realistic,
        "total_naive": round(total_naive, 2),
        "total_with_fanout": round(total_real, 2),
        "fanout_overhead": round(total_real - total_naive, 2),
        "cost_leak": {
            "endpoint": leader["endpoint"],
            "share_of_total": leader["share"],
            "reason": ("agent даёт 2000 запросов из 67000, это 3 процента трафика, "
                       "но из-за 5-7 вызовов на запрос и 9000 входных токенов "
                       "забирает наибольшую долю счёта"),
            "second_source": "rag: 4200 входных токенов на запрос при 10000 запросов",
        },
    }


def draw_context_charts(aggregated: list[dict]) -> None:
    sizes = [item["context_size"] for item in aggregated]

    fig, ax = charts.new_figure(7.4, 3.8)
    ax.plot(sizes, [item["cost_per_1k_requests"] for item in aggregated],
            marker="o", color=charts.ACCENT, linewidth=2)
    ax.set_xlabel("размер контекста, токены")
    ax.set_ylabel("стоимость 1000 запросов, $")
    ax.set_title("Контекст и стоимость")
    charts.save(fig, "cost_context_cost.png")

    fig, ax = charts.new_figure(7.4, 3.8)
    ax.plot(sizes, [item["avg_latency_ms"] for item in aggregated],
            marker="o", color=charts.ACCENT_2, linewidth=2)
    ax.set_xlabel("размер контекста, токены")
    ax.set_ylabel("latency, ms")
    ax.set_title("Контекст и latency")
    charts.save(fig, "cost_context_latency.png")


def draw_endpoint_chart(analysis: dict) -> None:
    items = analysis["with_agent_fanout"]
    names = [item["endpoint"] for item in items]
    naive_by_name = {item["endpoint"]: item["total_cost"] for item in analysis["naive"]}
    fig, ax = charts.new_figure(7.6, 4.0)
    x = range(len(names))
    width = 0.38
    ax.bar([i - width / 2 for i in x], [naive_by_name[n] for n in names], width,
           color=charts.ACCENT_2, label="1 вызов на запрос")
    ax.bar([i + width / 2 for i in x], [item["total_cost"] for item in items], width,
           color=charts.DANGER, label="с учётом фанаута агента")
    ax.set_xticks(list(x))
    ax.set_xticklabels(names)
    ax.set_ylabel("стоимость, $")
    ax.set_title("Стоимость по эндпоинтам за период")
    ax.legend()
    charts.save(fig, "cost_endpoints.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="CASE 2: cost")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--num-predict", type=int, default=160)
    parser.add_argument("--recalc", action="store_true")
    args = parser.parse_args()

    storage.init_db()
    if args.recalc:
        rows = storage.fetch(scenario=SCENARIO)
        for row in rows:
            row["context_size"] = min(CONTEXT_SIZES,
                                      key=lambda s: abs(row["input_tokens"] - s))
    else:
        rows = run_context_experiment(args.repeats, args.num_predict)

    aggregated = aggregate_context(rows)
    sample = rows[0] if rows else None
    measured = pricing.breakdown(
        int(sample["input_tokens"]) if sample else 700,
        int(sample["output_tokens"]) if sample else 150,
    ).as_dict()
    typical = pricing.breakdown(700, 150).as_dict()

    report = {
        "prices": {"input_per_1m": pricing.PRICE_INPUT_PER_1M,
                   "output_per_1m": pricing.PRICE_OUTPUT_PER_1M},
        "assumptions": {"requests_per_day": pricing.REQUESTS_PER_DAY,
                        "days_per_month": pricing.DAYS_PER_MONTH},
        "single_request_measured": measured,
        "typical_chat_request": typical,
        "context_experiment": aggregated,
        "endpoints": analyze_endpoints(load_endpoints()),
        "optimizations": [
            {
                "action": "Кэш ответов по хэшу нормализованного промпта на FAQ-трафике",
                "effect": "около 35 процентов chat-запросов не доходят до модели",
                "estimate": "минус 17-18 процентов счёта chat-эндпоинта",
            },
            {
                "action": "Ограничить фанаут агента: максимум 2-3 вызова и бюджет токенов на задачу",
                "effect": "агент перестаёт быть основным источником расходов",
                "estimate": "минус 55-60 процентов стоимости agent-эндпоинта",
            },
            {
                "action": "Сжать RAG-контекст: top-3 вместо top-10, переранжирование и обрезка чанков",
                "effect": "входные токены rag падают с 4200 до 1500-1800",
                "estimate": "минус 55 процентов входной стоимости rag",
            },
            {
                "action": "Ограничить max_tokens и требовать короткий формат ответа",
                "effect": "выходные токены стоят в 4 раза дороже входных",
                "estimate": "минус 20-30 процентов на summary и chat",
            },
            {
                "action": "Роутинг по сложности: дешёвая модель на FAQ, дорогая на research",
                "effect": "дорогая модель остаётся только там, где она нужна",
                "estimate": "минус 25-40 процентов общего счёта",
            },
        ],
    }

    (REPORTS_DIR / "cost_analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    storage.export_csv(REPORTS_DIR / "telemetry.csv")

    if aggregated:
        draw_context_charts(aggregated)
    draw_endpoint_chart(report["endpoints"])

    print("\nИзмеренный запрос: {0} вход, {1} выход, {2:.6f} $".format(
        measured["input_tokens"], measured["output_tokens"], measured["per_request"]))
    print("1000 запросов: {0:.3f} $, день: {1:.2f} $, месяц: {2:.2f} $".format(
        measured["per_1k_requests"], measured["per_day"], measured["per_month"]))
    print("Основной источник cost leak:", report["endpoints"]["cost_leak"]["endpoint"])


if __name__ == "__main__":
    main()
