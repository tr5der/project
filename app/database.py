from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .settings import DB_PATH
from .models import Base

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 15})

@event.listens_for(engine, "connect")
def pragmas(connection, _):
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def init_db():
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(bind=engine)
