"""Разбор текста: язык, тема, приблизительный подсчёт токенов."""
import re
import unicodedata

KZ_CHARS = set("әғқңөұүіһ") | set("ӘҒҚҢӨҰҮІҺ")
CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
LATIN = re.compile(r"[a-zA-Z]")

TOPIC_KEYWORDS = {
    "faq": ["как", "что такое", "где", "сколько", "what is", "how to", "цена",
            "тариф", "инструкц", "документ", "definition", "объясни"],
    "support": ["ошибк", "не работает", "проблем", "сломал", "упал", "error",
                "failed", "timeout", "не могу", "помог", "баг", "issue", "fix",
                "крашит", "зависает"],
    "research": ["сравни", "анализ", "почему", "исследов", "обоснуй", "compare",
                 "analyze", "trade-off", "архитектур", "оптимиз", "выбрать",
                 "стратег", "метрик"],
}


# Калибровка по llama3: на русском тексте выходит примерно 2 токена на слово
TOKENS_PER_WORD = 2.0


def estimate_tokens(text: str) -> int:
    """Оценка числа токенов, используется когда рантайм их не вернул."""
    if not text:
        return 0
    words = len(re.findall(r"\w+", text))
    punctuation = len(re.findall(r"[^\w\s]", text))
    return max(1, int(words * TOKENS_PER_WORD) + punctuation // 2)


def detect_language(text: str) -> str:
    if not text:
        return "unknown"
    if any(ch in KZ_CHARS for ch in text):
        return "kz"
    cyr = len(CYRILLIC.findall(text))
    lat = len(LATIN.findall(text))
    if cyr == 0 and lat == 0:
        return "unknown"
    return "ru" if cyr >= lat else "en"


def detect_topic(text: str) -> str:
    lowered = text.lower()
    scores = {
        topic: sum(1 for kw in keywords if kw in lowered)
        for topic, keywords in TOPIC_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "faq"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def split_claims(text: str) -> list[str]:
    """Режем ответ на отдельные утверждения по границам предложений и спискам."""
    text = re.sub(r"\n+", "\n", text.strip())
    parts: list[str] = []
    for line in text.split("\n"):
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if not line:
            continue
        parts.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip())
    return [p for p in parts if len(re.findall(r"\w+", p)) >= 3]


def tokens(text: str) -> list[str]:
    return re.findall(r"[\w%°]+", text.lower())


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text.replace(",", ".")))
