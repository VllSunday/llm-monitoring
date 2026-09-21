"""Оценка ответов модели и разметка галлюцинаций на уровне утверждений."""
from app.textutils import numbers, split_claims, tokens

STOPWORDS = {
    "и", "в", "на", "что", "это", "как", "для", "не", "с", "по", "из", "то",
    "а", "или", "же", "бы", "быть", "есть", "the", "a", "an", "is", "are",
    "of", "to", "in", "for", "and", "or", "that", "this", "it", "you", "we",
}

SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
CONTRADICTED = "CONTRADICTED"

CLAIM_WEIGHTS = {
    SUPPORTED: 1.0,
    PARTIALLY_SUPPORTED: 0.5,
    UNSUPPORTED: 0.0,
    CONTRADICTED: -0.5,
}

NEGATIONS = {"не", "нет", "никогда", "нельзя", "not", "never", "no"}

# Формулировки отказа: модель говорит, что данных нет
REFUSAL_MARKERS = (
    "нет данных", "нет информации", "не содержится", "не указан", "не найдено",
    "не могу ответить", "отсутствует информация", "no information", "not available",
    "cannot answer", "i do not have", "нет сведений",
)


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 2]


def overlap(claim: str, reference: str) -> float:
    """Доля значимых слов утверждения, найденных в эталоне."""
    claim_terms = content_tokens(claim)
    if not claim_terms:
        return 0.0
    ref_terms = set(content_tokens(reference))
    hits = sum(1 for term in claim_terms if term in ref_terms or _stem_hit(term, ref_terms))
    return hits / len(claim_terms)


def _stem_hit(term: str, ref_terms: set[str]) -> bool:
    stem = term[:5]
    return any(other.startswith(stem) for other in ref_terms)


def is_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def classify_claim(claim: str, reference: str) -> dict:
    ratio = overlap(claim, reference)
    claim_numbers = numbers(claim)
    ref_numbers = numbers(reference)
    conflict = bool(claim_numbers) and bool(ref_numbers) and not (claim_numbers & ref_numbers)

    # Отрицание считаем конфликтом только если оно есть в ответе и его нет в эталоне
    claim_neg = bool(set(tokens(claim)) & NEGATIONS)
    ref_neg = bool(set(tokens(reference)) & NEGATIONS)
    negation_conflict = claim_neg and not ref_neg and ratio >= 0.6

    if conflict and ratio >= 0.3:
        label = CONTRADICTED
    elif negation_conflict:
        label = CONTRADICTED
    elif ratio >= 0.6:
        label = SUPPORTED
    elif ratio >= 0.3:
        label = PARTIALLY_SUPPORTED
    else:
        label = UNSUPPORTED

    return {
        "claim": claim,
        "label": label,
        "overlap": round(ratio, 3),
        "numeric_conflict": conflict,
    }


def evaluate_answer(model_answer: str, reference_answer: str) -> dict:
    reference_is_refusal = is_refusal(reference_answer)
    answer_is_refusal = is_refusal(model_answer)

    if reference_is_refusal:
        # Вопрос вне базы знаний: правильное поведение - сказать, что данных нет
        return {
            "score": 1.0 if answer_is_refusal else 0.0,
            "hallucination": not answer_is_refusal,
            "abstained": answer_is_refusal,
            "claims": [{
                "claim": model_answer.strip(),
                "label": SUPPORTED if answer_is_refusal else UNSUPPORTED,
                "overlap": round(overlap(model_answer, reference_answer), 3),
                "numeric_conflict": False,
            }],
            "claim_counts": {
                SUPPORTED: int(answer_is_refusal),
                PARTIALLY_SUPPORTED: 0,
                UNSUPPORTED: int(not answer_is_refusal),
                CONTRADICTED: 0,
            },
            "unsupported_share": 0.0 if answer_is_refusal else 1.0,
        }

    if answer_is_refusal:
        # Ответ в базе есть, но модель отказалась: это промах, а не выдумка
        return {
            "score": 0.0,
            "hallucination": False,
            "abstained": True,
            "claims": [{
                "claim": model_answer.strip(),
                "label": UNSUPPORTED,
                "overlap": round(overlap(model_answer, reference_answer), 3),
                "numeric_conflict": False,
            }],
            "claim_counts": {SUPPORTED: 0, PARTIALLY_SUPPORTED: 0,
                             UNSUPPORTED: 1, CONTRADICTED: 0},
            "unsupported_share": 1.0,
        }

    claims = split_claims(model_answer) or [model_answer.strip()]
    classified = [classify_claim(claim, reference_answer) for claim in claims]

    raw = sum(CLAIM_WEIGHTS[item["label"]] for item in classified) / len(classified)
    score = round(max(0.0, min(1.0, raw)), 3)

    counts = {label: 0 for label in CLAIM_WEIGHTS}
    for item in classified:
        counts[item["label"]] += 1

    unsupported_share = (counts[UNSUPPORTED] + counts[CONTRADICTED]) / len(classified)
    hallucination = counts[CONTRADICTED] > 0 or unsupported_share >= 0.5 or score < 0.4

    return {
        "score": score,
        "hallucination": bool(hallucination),
        "abstained": False,
        "claims": classified,
        "claim_counts": counts,
        "unsupported_share": round(unsupported_share, 3),
    }


def aggregate(results: list[dict]) -> dict:
    if not results:
        return {}
    total = len(results)
    hallucinated = sum(1 for r in results if r["hallucination"])
    abstained = sum(1 for r in results if r.get("abstained"))
    scores = [r["score"] for r in results]
    claim_counts = {label: 0 for label in CLAIM_WEIGHTS}
    for result in results:
        for label, value in result["claim_counts"].items():
            claim_counts[label] += value
    total_claims = sum(claim_counts.values()) or 1

    by_type: dict[str, dict] = {}
    for result in results:
        qtype = result.get("question_type", "unknown")
        bucket = by_type.setdefault(qtype, {"total": 0, "hallucinated": 0, "score_sum": 0.0})
        bucket["total"] += 1
        bucket["hallucinated"] += int(result["hallucination"])
        bucket["score_sum"] += result["score"]
    for bucket in by_type.values():
        bucket["hallucination_rate"] = round(bucket["hallucinated"] / bucket["total"], 3)
        bucket["avg_score"] = round(bucket["score_sum"] / bucket["total"], 3)
        bucket.pop("score_sum")

    return {
        "total": total,
        "hallucination_rate": round(hallucinated / total, 3),
        "abstain_rate": round(abstained / total, 3),
        "avg_score": round(sum(scores) / total, 3),
        "accuracy_at_06": round(sum(1 for s in scores if s >= 0.6) / total, 3),
        "claim_counts": claim_counts,
        "claim_shares": {k: round(v / total_claims, 3) for k, v in claim_counts.items()},
        "by_question_type": dict(sorted(
            by_type.items(), key=lambda kv: kv[1]["hallucination_rate"], reverse=True
        )),
    }
