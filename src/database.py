import os
import time
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

# allow override from environment for flexibility
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/cms_db")

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def wait_for_db():
    retries = 10
    while retries > 0:
        try:
            conn = engine.connect()
            conn.close()
            print("Successfully connected to the database!")
            return
        except Exception as e:
            print(f"Database not ready yet... ({e})")
            retries -= 1
            time.sleep(5)
    raise Exception("Could not connect to the database")