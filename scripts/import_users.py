"""Manual CSV import: username,password. Existing users are never overwritten."""
import argparse
import csv
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.passwords import generate_password_hash
from app.database import SessionLocal, init_db
from app.models import User

p = argparse.ArgumentParser()
p.add_argument("csv_file", type=Path)
p.add_argument("--dry-run", action="store_true")
args = p.parse_args()
with args.csv_file.open(encoding="utf-8-sig", newline="") as handle:
    reader = csv.DictReader(handle)
    if not reader.fieldnames or not {"username", "password"}.issubset(reader.fieldnames):
        p.error("CSV requires username,password columns")
    rows = list(reader)
seen = set()
valid = []
for line, row in enumerate(rows, 2):
    name = (row.get("username") or "").strip()
    pwd = row.get("password") or ""
    if not name or not pwd or len(name) > 128 or name in seen:
        p.error(f"Invalid or duplicate user on CSV line {line}")
    seen.add(name)
    valid.append((name, pwd))
init_db()
with SessionLocal.begin() as db:
    existing = set(db.scalars(select(User.username).where(User.username.in_([name for name,_ in valid]))))
    pending = [(name,pwd) for name,pwd in valid if name not in existing]
    print(f"Rows: {len(valid)}; new: {len(pending)}; existing: {len(existing)}; dry run: {args.dry_run}")
    if not args.dry_run:
        for name, pwd in pending:
            db.add(User(username=name, password_hash=generate_password_hash(pwd)))
    else:
        db.rollback()
