import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "agent.sqlite3"
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() in {"true", "1", "yes"}
SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30")) * 60
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
