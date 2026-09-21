"""Простейший retrieval по локальной базе знаний."""
import json
import math
from collections import Counter
from functools import lru_cache

from app.config import DATA_DIR
from app.textutils import tokens

KB_PATH = DATA_DIR / "knowledge_base.json"


@lru_cache(maxsize=1)
def load_kb() -> list[dict]:
    with open(KB_PATH, encoding="utf-8") as fh:
        docs = json.load(fh)
    for doc in docs:
        doc["_tokens"] = tokens(doc["title"] + " " + doc["text"])
    return docs


def _idf(docs: list[dict]) -> dict[str, float]:
    df = Counter()
    for doc in docs:
        df.update(set(doc["_tokens"]))
    total = len(docs)
    return {term: math.log((total + 1) / (count + 0.5)) for term, count in df.items()}


def search(query: str, top_k: int = 3) -> list[dict]:
    docs = load_kb()
    idf = _idf(docs)
    query_terms = tokens(query)
    scored = []
    for doc in docs:
        counts = Counter(doc["_tokens"])
        length = len(doc["_tokens"]) or 1
        score = sum(
            idf.get(term, 0.0) * counts[term] / length
            for term in query_terms
            if term in counts
        )
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {"id": doc["id"], "title": doc["title"], "text": doc["text"], "score": round(score, 4)}
        for score, doc in scored[:top_k]
    ]


def build_context(chunks: list[dict]) -> str:
    if not chunks:
        return ""
    return "\n".join(f"[{c['id']}] {c['title']}: {c['text']}" for c in chunks)
