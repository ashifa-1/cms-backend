import os
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    # Retry logic to wait for the Postgres container to be fully ready
    retries = 5
    while retries > 0:
        try:
            from .models import Base
            Base.metadata.create_all(bind=engine)
            print("Database connected and tables created!")
            break
        except OperationalError:
            retries -= 1
            print(f"Database not ready yet... retrying in 5 seconds ({retries} retries left)")
            time.sleep(5)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()