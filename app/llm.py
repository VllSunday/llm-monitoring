"""Клиент локального рантайма Ollama."""
import time

import requests

from app.config import (CONTEXT_WINDOW, DEFAULT_NUM_PREDICT, MODEL, OLLAMA_URL,
                        REQUEST_TIMEOUT)
from app.textutils import estimate_tokens


class LLMUnavailable(RuntimeError):
    pass


def is_available(url: str = OLLAMA_URL) -> bool:
    try:
        requests.get(f"{url}/api/tags", timeout=3).raise_for_status()
        return True
    except requests.RequestException:
        return False


def list_models(url: str = OLLAMA_URL) -> list[str]:
    try:
        data = requests.get(f"{url}/api/tags", timeout=5).json()
        return [m["name"] for m in data.get("models", [])]
    except requests.RequestException:
        return []


def generate(prompt: str, model: str = MODEL, num_predict: int = DEFAULT_NUM_PREDICT,
             temperature: float = 0.2, seed: int | None = 42,
             url: str = OLLAMA_URL) -> dict:
    """Один вызов модели. Возвращает текст, токены и тайминги рантайма."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
            "num_ctx": CONTEXT_WINDOW,
        },
    }
    if seed is not None:
        payload["options"]["seed"] = seed

    started = time.perf_counter()
    try:
        response = requests.post(f"{url}/api/generate", json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LLMUnavailable(
            f"Не удалось получить ответ от Ollama по адресу {url}: {exc}"
        ) from exc

    data = response.json()
    elapsed_ms = (time.perf_counter() - started) * 1000
    text = data.get("response", "")
    return {
        "text": text,
        "model": data.get("model", model),
        "input_tokens": int(data.get("prompt_eval_count") or estimate_tokens(prompt)),
        "output_tokens": int(data.get("eval_count") or estimate_tokens(text)),
        "llm_ms": elapsed_ms,
        "load_ms": (data.get("load_duration") or 0) / 1e6,
        "prompt_eval_ms": (data.get("prompt_eval_duration") or 0) / 1e6,
        "eval_ms": (data.get("eval_duration") or 0) / 1e6,
    }
