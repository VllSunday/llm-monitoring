"""Общие настройки проекта."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
WEB_DIR = ROOT / "web"

DB_PATH = Path(os.getenv("LLM_MON_DB", DATA_DIR / "telemetry.db"))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("LLM_MON_MODEL", "llama3:8b")
REQUEST_TIMEOUT = int(os.getenv("LLM_MON_TIMEOUT", "300"))
DEFAULT_NUM_PREDICT = int(os.getenv("LLM_MON_NUM_PREDICT", "160"))
CONTEXT_WINDOW = int(os.getenv("LLM_MON_NUM_CTX", "8192"))

# Условные цены из задания, доллары за 1M токенов
PRICE_INPUT_PER_1M = 2.0
PRICE_OUTPUT_PER_1M = 8.0

ENDPOINTS = ("chat", "rag", "summary", "agent")

# Пороги для алертов, подобраны по замерам из reports/latency_metrics.json
ALERT_P95_MS = 6000
ALERT_P99_MS = 12000
ALERT_ERROR_RATE = 0.02

# Пороги дрейфа
DRIFT_PSI_WARN = 0.1
DRIFT_PSI_ALERT = 0.25
DRIFT_LENGTH_WARN = 0.3  # относительное изменение средней длины запроса

REPORTS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
