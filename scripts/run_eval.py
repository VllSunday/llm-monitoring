"""CASE 4. Прогон evaluation dataset и разметка галлюцинаций по утверждениям."""
import argparse
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import charts, evaluation, pipeline, storage  # noqa: E402
from app.config import DATA_DIR, REPORTS_DIR  # noqa: E402

SCENARIO = "eval"

INCIDENT = {
    "facts": {
        "hallucination_rate": {"before": 0.03, "after": 0.09},
        "retrieval_relevance": {"before": 0.86, "after": 0.59},
        "context_size_tokens": {"before": 1200, "after": 4500},
        "model": "без изменений",
        "prompt": "без изменений",
    },
    "investigation": [
        {
            "change": "контекст вырос с 1.2k до 4.5k токенов",
            "symptom": "hallucination rate вырос втрое, retrieval relevance упал на 27 пунктов",
            "hypothesis": ("увеличили top-k или размер чанка, в контекст попал шум, "
                           "релевантный фрагмент утонул среди нерелевантных"),
            "metric_to_check": ("top-k и размер чанка в конфиге retriever, средний score top-1, "
                                "позиция релевантного чанка в контексте, recall@k"),
            "root_cause": "retriever отдаёт больше документов при той же точности, контекст размывается",
            "mitigation": ("вернуть top-k, добавить переранжирование и порог по score, "
                           "обрезать чанки, вернуть цитирование источника в ответе"),
        },
        {
            "change": "модель и промпт не менялись",
            "symptom": "качество упало без релиза модели",
            "hypothesis": "проблема не в модели, а в данных на входе, то есть в retrieval",
            "metric_to_check": "версия индекса и эмбеддера, дата переиндексации, объём корпуса",
            "root_cause": "переиндексация или смена эмбеддера без прогона golden на retrieval",
            "mitigation": "гейт на выкатку индекса: прогон retrieval-метрик перед переключением",
        },
        {
            "change": "выросла доля длинных пользовательских запросов",
            "symptom": "контекст раздувается ещё и за счёт самого запроса",
            "hypothesis": "длинный запрос ухудшает поиск и вытесняет полезный контекст",
            "metric_to_check": "длина запроса по перцентилям, корреляция длины и hallucination",
            "root_cause": "нет нормализации запроса перед поиском",
            "mitigation": "сжимать запрос перед retrieval, искать по извлечённым ключевым сущностям",
        },
    ],
    "monitoring": [
        "hallucination_rate по скользящему окну 1 час, алерт при значении выше 5 процентов",
        "retrieval_relevance и recall@k, алерт при падении ниже 75 процентов",
        "средний и p95 context_size, алерт при росте более чем на 50 процентов к baseline",
        "доля ответов без ссылки на источник и доля ответов нет данных",
        "ежедневный прогон golden dataset плюс canary после каждой выкатки индекса",
        "связка алертов: рост context_size вместе с падением relevance открывает инцидент сразу",
    ],
}

PRODUCTION_METRICS = [
    "hallucination_rate на сэмпле продового трафика",
    "grounding rate: доля утверждений, подтверждённых контекстом",
    "retrieval relevance, recall@k, доля запросов без релевантного чанка",
    "доля ответов нет данных и доля пустых ответов",
    "user feedback: тумблеры и жалобы на ответ",
    "доля ответов с числами, которых нет в контексте",
]


def run_dataset(items: list[dict], num_predict: int) -> list[dict]:
    results = []
    for index, item in enumerate(items, start=1):
        record = pipeline.run(item["question"], endpoint="rag", scenario=SCENARIO,
                              num_predict=num_predict)
        verdict = evaluation.evaluate_answer(record["response"], item["reference_answer"])
        verdict.update({
            "id": item["id"],
            "question": item["question"],
            "question_type": item["question_type"],
            "reference_answer": item["reference_answer"],
            "model_answer": record["response"],
            "latency_ms": record["latency_ms"],
            "input_tokens": record["input_tokens"],
            "output_tokens": record["output_tokens"],
            "request_id": record["request_id"],
        })
        results.append(verdict)
        flag = "ГАЛЛЮЦИНАЦИЯ" if verdict["hallucination"] else "ok"
        print(f"{index:>2}/{len(items)} {item['id']} score={verdict['score']:.2f} {flag}")
    return results


def draw_scores(results: list[dict]) -> None:
    fig, ax = charts.new_figure(7.2, 3.6)
    ax.hist([r["score"] for r in results], bins=10, range=(0, 1), color=charts.ACCENT_2)
    ax.set_xlabel("score")
    ax.set_ylabel("количество вопросов")
    ax.set_title("Распределение оценок ответов")
    charts.save(fig, "eval_scores.png")


def draw_claims(summary: dict) -> None:
    labels = [evaluation.SUPPORTED, evaluation.PARTIALLY_SUPPORTED,
              evaluation.UNSUPPORTED, evaluation.CONTRADICTED]
    colors = [charts.ACCENT, charts.ACCENT_2, charts.WARN, charts.DANGER]
    fig, ax = charts.new_figure(7.6, 3.6)
    ax.bar([label.replace("_", "\n") for label in labels],
           [summary["claim_counts"][label] for label in labels], color=colors, width=0.55)
    ax.set_ylabel("количество утверждений")
    ax.set_title("Разметка утверждений")
    charts.save(fig, "eval_claims.png")


def draw_by_type(summary: dict) -> None:
    items = summary["by_question_type"]
    names = list(items)
    values = [items[name]["hallucination_rate"] * 100 for name in names]
    colors = [charts.DANGER if v >= 50 else charts.WARN if v > 0 else charts.ACCENT
              for v in values]
    fig, ax = charts.new_figure(7.6, 3.6)
    ax.bar(names, values, color=colors, width=0.55)
    ax.set_ylabel("hallucination rate, %")
    ax.set_title("Галлюцинации по типам вопросов")
    charts.save(fig, "eval_by_type.png")


def export_csv(results: list[dict], path: pathlib.Path) -> None:
    fields = ["id", "question_type", "question", "reference_answer", "model_answer",
              "score", "hallucination", "abstained", "unsupported_share", "latency_ms",
              "input_tokens", "output_tokens"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="CASE 4: hallucinations")
    parser.add_argument("--num-predict", type=int, default=200)
    parser.add_argument("--limit", type=int, default=0, help="ограничить число вопросов")
    args = parser.parse_args()

    storage.init_db()
    with open(DATA_DIR / "eval_dataset.json", encoding="utf-8") as fh:
        items = json.load(fh)
    if args.limit:
        items = items[:args.limit]

    results = run_dataset(items, args.num_predict)
    summary = evaluation.aggregate(results)

    report = {
        "summary": summary,
        "results": results,
        "production_metrics": PRODUCTION_METRICS,
        "incident": INCIDENT,
        "method": {
            "claim_split": "ответ режется на предложения и пункты списка",
            "labels": ["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"],
            "rule": ("доля значимых слов утверждения, найденных в эталоне: "
                     "от 0.6 SUPPORTED, от 0.3 PARTIALLY_SUPPORTED, ниже UNSUPPORTED; "
                     "расхождение чисел или отрицания даёт CONTRADICTED"),
            "hallucination_rule": ("есть CONTRADICTED, либо половина утверждений "
                                   "не подтверждена, либо score ниже 0.4"),
            "abstain_rule": ("ответ вида нет данных считается отказом: на вопросе вне базы "
                             "это правильный ответ, на вопросе из базы это промах, "
                             "но не галлюцинация"),
            "limitations": ("правило работает на пересечении слов, поэтому не видит "
                            "перефразирование; на проде поверх этого нужен LLM-судья "
                            "или NLI-модель"),
        },
    }

    (REPORTS_DIR / "eval_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    export_csv(results, REPORTS_DIR / "eval_results.csv")
    storage.export_csv(REPORTS_DIR / "telemetry.csv")

    draw_scores(results)
    draw_claims(summary)
    draw_by_type(summary)

    print("\nhallucination rate:", summary["hallucination_rate"])
    print("средний score:", summary["avg_score"])
    print("по типам вопросов:", json.dumps(summary["by_question_type"], ensure_ascii=False))


if __name__ == "__main__":
    main()
