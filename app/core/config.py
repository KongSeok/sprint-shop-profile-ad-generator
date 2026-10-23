import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SHOP_DB_PATH = Path(os.getenv("SHOP_DB_PATH", "data/shops/shops.db"))
if not SHOP_DB_PATH.is_absolute():
    SHOP_DB_PATH = PROJECT_ROOT / SHOP_DB_PATH
