import time
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from . import models, schemas

# MUST MATCH YOUR database.py
DATABASE_URL = "postgresql://postgres:postgres@db:5432/cms_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def publish_scheduled_posts():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        # Find posts that are scheduled and the time has passed
        posts = db.query(models.Post).filter(
            models.Post.status == schemas.PostStatus.scheduled,
            models.Post.scheduled_for <= now
        ).all()

        for post in posts:
            print(f"Worker: Publishing post {post.id} - {post.title}", flush=True)
            post.status = schemas.PostStatus.published
            post.published_at = now
        
        db.commit()
    except Exception as e:
        print(f"Worker Error: {e}", flush=True)
    finally:
        db.close()

if __name__ == "__main__":
    print("Worker started: Monitoring scheduled posts...", flush=True)
    while True:
        publish_scheduled_posts()
        time.sleep(30)  # Check every 30 seconds