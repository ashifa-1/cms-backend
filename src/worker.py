import time
import redis
import json
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from . import models, schemas

# Database Configuration (can be overridden via env)
import os
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/cms_db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redis Configuration for Cache Invalidation
# This ensures that when a post is published by the worker, the public list updates immediately
try:
    redis_client = redis.Redis(host='cache', port=6379, db=0, decode_responses=True)
except Exception as e:
    print(f"Worker: Redis connection failed (caching will not be invalidated): {e}")
    redis_client = None

def clear_published_cache():
    """Clears the public post list cache in Redis."""
    if redis_client:
        keys = redis_client.keys("published_list_*")
        if keys:
            redis_client.delete(*keys)
            print(f"Worker: Invalidated {len(keys)} cache keys.", flush=True)

def publish_scheduled_posts():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        # Find posts that are scheduled and whose time has passed
        posts = db.query(models.Post).filter(
            models.Post.status == schemas.PostStatus.scheduled,
            models.Post.scheduled_for <= now
        ).all()

        if posts:
            for post in posts:
                print(f"Worker: Publishing post {post.id} - {post.title}", flush=True)
                post.status = schemas.PostStatus.published
                # Update published_at to the current time it actually went live
                post.published_at = now
            
            db.commit()
            # Clear the Redis cache so the public can see the new posts immediately
            clear_published_cache()
        
    except Exception as e:
        print(f"Worker Error: {e}", flush=True)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    interval = int(os.getenv("WORKER_INTERVAL_SECONDS", "30"))
    print(f"Worker started: Monitoring scheduled posts every {interval} seconds...", flush=True)
    while True:
        publish_scheduled_posts()
        time.sleep(interval)