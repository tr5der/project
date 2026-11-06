from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import init_db
from app.settings import DB_PATH
init_db()
print("SQLite database ready:", DB_PATH)
