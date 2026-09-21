"""Пайплайн обработки запроса с замером каждого этапа."""
import time
import uuid
from datetime import datetime, timezone

from app.config import DEFAULT_NUM_PREDICT, MODEL
from app.llm import generate
from app.pricing import request_cost
from app.retrieval import build_context, load_kb, search
from app.storage import save
from app.textutils import detect_language, detect_topic, estimate_tokens, normalize

SYSTEM_PROMPT = (
    "Ты ассистент технической поддержки LLM-платформы. "
    "Отвечай кратко и по делу, максимум 4 предложения, на языке вопроса. "
    "Если данных не хватает, скажи об этом прямо."
)

AGENT_CALLS = {"agent": 2}


class Stages:
    """Замер этапов пайплайна в миллисекундах."""

    def __init__(self):
        self.data: dict[str, float] = {}
        self._name: str | None = None
        self._started = 0.0

    def __call__(self, name: str):
        self._name = name
        return self

    def __enter__(self):
        self._started = time.perf_counter()
        return self

    def __exit__(self, *exc):
        elapsed = (time.perf_counter() - self._started) * 1000
        self.data[self._name] = round(self.data.get(self._name, 0.0) + elapsed, 3)
        return False


def context_filler(target_tokens: int) -> str:
    """Добивает контекст до нужного размера текстами из базы знаний."""
    if target_tokens <= 0:
        return ""
    pool = [f"{doc['title']}. {doc['text']}" for doc in load_kb()]
    parts: list[str] = []
    total = 0
    index = 0
    while total < target_tokens:
        chunk = pool[index % len(pool)]
        parts.append(chunk)
        total += estimate_tokens(chunk)
        index += 1
    return "\n".join(parts)


def build_prompt(question: str, context: str, filler: str) -> str:
    blocks = [SYSTEM_PROMPT]
    if filler:
        blocks.append("История диалога и справочные материалы:\n" + filler)
    if context:
        blocks.append("Контекст из базы знаний:\n" + context)
    blocks.append("Вопрос пользователя: " + question)
    return "\n\n".join(blocks)


def run(prompt: str, endpoint: str = "chat", scenario: str = "manual",
        num_predict: int | None = None, padding_tokens: int = 0,
        model: str = MODEL, persist: bool = True) -> dict:
    stages = Stages()
    started = time.perf_counter()
    request_id = uuid.uuid4().hex[:12]
    num_predict = num_predict or DEFAULT_NUM_PREDICT

    with stages("validate"):
        if not prompt or not prompt.strip():
            raise ValueError("Пустой промпт")
        if len(prompt) > 20_000:
            raise ValueError("Промпт длиннее 20000 символов")

    with stages("preprocess"):
        question = normalize(prompt)
        language = detect_language(question)
        topic = detect_topic(question)
        filler = context_filler(padding_tokens)

    chunks: list[dict] = []
    with stages("retrieval"):
        if endpoint in ("rag", "agent"):
            chunks = search(question, top_k=3)
    context = build_context(chunks)

    calls = AGENT_CALLS.get(endpoint, 1)
    input_tokens = output_tokens = 0
    answer = ""
    llm_meta: dict = {}
    with stages("llm_call"):
        notes = ""
        for step in range(calls):
            if step == 0 and calls > 1:
                step_prompt = build_prompt(
                    f"Составь план ответа из трёх пунктов на вопрос: {question}",
                    context, filler,
                )
            else:
                extra = f"\n\nПлан ответа:\n{notes}" if notes else ""
                step_prompt = build_prompt(question + extra, context, filler)
            result = generate(step_prompt, model=model, num_predict=num_predict)
            input_tokens += result["input_tokens"]
            output_tokens += result["output_tokens"]
            llm_meta = result
            if step == 0 and calls > 1:
                notes = result["text"]
            else:
                answer = result["text"]

    with stages("postprocess"):
        answer = answer.strip()
        cost = request_cost(input_tokens, output_tokens)

    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    record = {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "model": llm_meta.get("model", model),
        "prompt": question,
        "response": answer,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "endpoint": endpoint,
        "language": language,
        "topic": topic,
        "cost_usd": cost,
        "prompt_tokens_est": estimate_tokens(question),
        "scenario": scenario,
        "stages": stages.data,
        "error": None,
    }

    if persist:
        # Запись меряем отдельно, в latency_ms попадает только обработка запроса
        with stages("persist"):
            save(record)
        record["stages"] = stages.data

    record["retrieved"] = chunks
    record["calls"] = calls
    return record
