import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "300000"))
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
IMAGE_ENABLED = os.getenv("IMAGE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
IMAGE_CPU_OFFLOAD = os.getenv("IMAGE_CPU_OFFLOAD", "false").strip().lower() in {"1", "true", "yes", "on"}
CUTOUT_MODEL = "isnet-general-use"
CUTOUT_POST_PROCESS_MASK = False
CUTOUT_MAX_EDGE = 2048
CUTOUT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SHOP_DB_PATH = Path(os.getenv("SHOP_DB_PATH", "data/shops/shops.db"))
if not SHOP_DB_PATH.is_absolute():
    SHOP_DB_PATH = PROJECT_ROOT / SHOP_DB_PATH
