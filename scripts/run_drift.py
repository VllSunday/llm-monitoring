"""CASE 3. Сравнение baseline и production, детектор дрейфа, разбор инцидента."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import charts, drift, storage  # noqa: E402
from app.config import DATA_DIR, REPORTS_DIR  # noqa: E402
from app.textutils import estimate_tokens  # noqa: E402

INCIDENT_HYPOTHESES = [
    {
        "hypothesis": "Сменился состав трафика, golden dataset его не покрывает",
        "why": ("support вырос с 30 до 50 процентов, ru с 20 до 40, длина запроса выросла "
                "в 2.8 раза, а golden остался на старом распределении"),
        "metrics_to_check": [
            "quality в разрезе language и topic, а не в целом",
            "PSI по language, topic и длине запроса по дням",
            "доля запросов, у которых нет похожего примера в golden dataset",
            "покрытие golden dataset по сегментам продового трафика",
        ],
        "confirms_if": "падение качества сосредоточено в ru и support, в en и faq качество прежнее",
    },
    {
        "hypothesis": "Деградировал retrieval на новых длинных запросах",
        "why": "длинный запрос размывает поисковый запрос, top-k возвращает нерелевантные чанки",
        "metrics_to_check": [
            "retrieval relevance и recall@k по сегментам",
            "средний score top-1 и доля запросов без релевантного чанка",
            "доля ответов без ссылок на контекст",
            "корреляция длины запроса и оценки качества",
        ],
        "confirms_if": "relevance падает вместе с ростом длины запроса, quality коррелирует с relevance",
    },
    {
        "hypothesis": "Контекст переполняется и обрезается",
        "why": "длинные запросы плюс история диалога упираются в лимит окна",
        "metrics_to_check": [
            "доля запросов с truncation и средний context size",
            "распределение input_tokens по перцентилям",
            "доля ответов вида нет данных",
        ],
        "confirms_if": "доля truncation выросла синхронно с падением качества",
    },
    {
        "hypothesis": "Изменился способ измерения качества в проде",
        "why": ("golden прогоняется автоматически и почти не изменился, продовая оценка "
                "зависит от разметчиков и выборки"),
        "metrics_to_check": [
            "состав и объём выборки для оценки, доля новых разметчиков",
            "согласованность оценок между разметчиками",
            "версия промпта LLM-судьи, если оценка автоматическая",
        ],
        "confirms_if": "при переразметке старой выборки новым процессом качество тоже падает",
    },
    {
        "hypothesis": "Изменилось окружение инференса, хотя модель и промпт формально те же",
        "why": "квантование, версия рантайма или роутинг на другой пул могли поменяться",
        "metrics_to_check": [
            "версия рантайма и хэш весов по запросам",
            "распределение quality по инстансам и зонам",
            "latency и tokens per second по пулам",
        ],
        "confirms_if": "качество падает только на части инстансов",
    },
]


def sample_from_distribution(dist: dict, size: int, seed: int) -> list[str]:
    import random

    rng = random.Random(seed)
    keys = list(dist)
    weights = [dist[k] for k in keys]
    return rng.choices(keys, weights=weights, k=size)


def draw_distribution(feature: dict, filename: str, title: str) -> None:
    keys = sorted(set(feature["baseline"]) | set(feature["production"]))
    fig, ax = charts.new_figure(7.2, 3.8)
    x = range(len(keys))
    width = 0.38
    ax.bar([i - width / 2 for i in x], [feature["baseline"].get(k, 0) * 100 for k in keys],
           width, color=charts.ACCENT_2, label="baseline")
    ax.bar([i + width / 2 for i in x], [feature["production"].get(k, 0) * 100 for k in keys],
           width, color=charts.WARN, label="production")
    ax.set_xticks(list(x))
    ax.set_xticklabels(keys)
    ax.set_ylabel("доля трафика, %")
    ax.set_title(title)
    ax.legend()
    charts.save(fig, filename)


def draw_psi(report: dict) -> None:
    features = [f for f in report["features"] if f["type"] == "categorical"]
    fig, ax = charts.new_figure(7.2, 3.4)
    names = [f["feature"] for f in features]
    values = [f["psi"] for f in features]
    colors = [charts.DANGER if v >= report["thresholds"]["psi_alert"]
              else charts.WARN if v >= report["thresholds"]["psi_warn"]
              else charts.ACCENT for v in values]
    ax.bar(names, values, color=colors, width=0.5)
    ax.axhline(report["thresholds"]["psi_warn"], color=charts.WARN,
               linestyle="--", linewidth=1, label="warn 0.1")
    ax.axhline(report["thresholds"]["psi_alert"], color=charts.DANGER,
               linestyle="--", linewidth=1, label="alert 0.25")
    ax.set_ylabel("PSI")
    ax.set_title("Дрейф признаков")
    ax.legend()
    charts.save(fig, "drift_psi.png")


def draw_quality(incident: dict) -> None:
    fig, ax = charts.new_figure(7.2, 3.6)
    labels = ["до", "после"]
    prod = [incident["production_quality"]["before"] * 100,
            incident["production_quality"]["after"] * 100]
    golden = [incident["golden_dataset_quality"]["before"] * 100,
              incident["golden_dataset_quality"]["after"] * 100]
    ax.plot(labels, prod, marker="o", color=charts.DANGER, linewidth=2, label="production")
    ax.plot(labels, golden, marker="o", color=charts.ACCENT, linewidth=2, label="golden dataset")
    ax.set_ylabel("качество, %")
    ax.set_ylim(75, 95)
    ax.set_title("Расхождение продового качества и golden dataset")
    ax.legend()
    charts.save(fig, "drift_quality.png")


def live_traffic_report(baseline: dict) -> dict | None:
    rows = storage.fetch()
    if len(rows) < 10:
        return None
    lengths = [estimate_tokens(row["prompt"]) for row in rows]
    live = {
        "language": drift.distribution_from_rows(rows, "language"),
        "topic": drift.distribution_from_rows(rows, "topic"),
        "query_length_tokens": sum(lengths) / len(lengths),
    }
    report = drift.detect(baseline, live)
    report["sample_size"] = len(rows)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="CASE 3: drift")
    parser.add_argument("--sample", type=int, default=2000,
                        help="размер синтетической выборки для проверки детектора")
    args = parser.parse_args()

    with open(DATA_DIR / "drift_profiles.json", encoding="utf-8") as fh:
        profiles = json.load(fh)

    baseline, production = profiles["baseline"], profiles["production"]
    report = drift.detect(baseline, production)

    # Проверяем детектор на выборках, собранных из тех же распределений
    sampled_baseline = sample_from_distribution(baseline["language"], args.sample, seed=1)
    sampled_production = sample_from_distribution(production["language"], args.sample, seed=2)
    sampled = drift.categorical_report(
        "language_sampled",
        {k: sampled_baseline.count(k) for k in set(sampled_baseline)},
        {k: sampled_production.count(k) for k in set(sampled_production)},
    )

    result = {
        "baseline": baseline,
        "production": production,
        "drift": report,
        "sampled_check": sampled,
        "live_traffic": live_traffic_report(baseline),
        "most_changed": [
            {"feature": f["feature"],
             "metric": "psi" if f["type"] == "categorical" else "delta_pct",
             "value": f.get("psi", f.get("delta_pct")),
             "status": f["status"]}
            for f in report["features"]
        ],
        "thresholds_rationale": {
            "psi_warn": "0.1 - заметный сдвиг, ставим тикет и смотрим сегменты",
            "psi_alert": "0.25 - распределение поменялось, нужен прогон обновлённого golden",
            "length_warn_rel": "0.3 - рост средней длины запроса на 30 процентов меняет и стоимость, и качество",
            "window": "скользящее окно 24 часа против baseline за последние 30 дней",
            "min_sample": "не считаем PSI на выборке меньше 200 запросов",
        },
        "incident": {
            "facts": profiles["quality_incident"],
            "reading": ("golden почти не изменился, значит сама модель на старых данных "
                        "работает как раньше, проблема в новом продовом трафике или в том, "
                        "что вокруг модели"),
            "hypotheses": INCIDENT_HYPOTHESES,
            "priority_checks": [
                "разложить продовое качество по language, topic и длине запроса",
                "сравнить retrieval relevance до и после по тем же сегментам",
                "посчитать PSI по дням и найти день, когда началось расхождение",
                "проверить покрытие golden dataset новыми сегментами и дополнить его",
            ],
        },
    }

    (REPORTS_DIR / "drift_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    features = {f["feature"]: f for f in report["features"]}
    draw_distribution(features["language"], "drift_language.png", "Распределение языков")
    draw_distribution(features["topic"], "drift_topic.png", "Распределение тем")
    draw_psi(report)
    draw_quality(profiles["quality_incident"])

    print("Статус дрейфа:", report["status"])
    for feature in report["features"]:
        value = feature.get("psi", feature.get("delta_pct"))
        print(f"  {feature['feature']:<20} {feature['status']:<6} {value}")


if __name__ == "__main__":
    main()
