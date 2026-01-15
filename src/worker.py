import time
from datetime import datetime
from sqlalchemy.orm import Session
from .database import SessionLocal, engine
from .models import Post, PostStatus

def check_scheduled_posts():
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        # Find posts that are 'scheduled' and the time has passed
        scheduled_posts = db.query(Post).filter(
            Post.status == PostStatus.scheduled,
            Post.scheduled_for <= now
        ).all()

        for post in scheduled_posts:
            print(f"Publishing scheduled post: {post.title} (ID: {post.id})")
            post.status = PostStatus.published
            post.published_at = now
            db.add(post)
        
        db.commit()
    except Exception as e:
        print(f"Worker Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("Background worker started...")
    while True:
        check_scheduled_posts()
        # Run every 60 seconds
        time.sleep(60)