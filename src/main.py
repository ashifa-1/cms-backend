import os
import shutil
import json
import redis
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from slugify import slugify
from typing import List
from datetime import datetime
from jose import jwt, JWTError

from . import models, schemas, auth, database

app = FastAPI(title="CMS Backend")

# --- DATABASE STARTUP SAFETY ---
database.wait_for_db()
models.Base.metadata.create_all(bind=database.engine)

# --- REDIS SETUP ---
# 'cache' is the hostname of the redis container defined in docker-compose.yml
redis_client = redis.Redis(host='cache', port=6379, db=0, decode_responses=True)
CACHE_EXPIRE = 3600  # Cache expires in 1 hour (3600 seconds)

# --- MEDIA STORAGE SETUP ---
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --- AUTH CONFIG ---
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

# --- HELPERS ---

def get_current_user(token: str = Depends(api_key_header), db: Session = Depends(database.get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    
    actual_token = token.replace("Bearer ", "") 
    
    try:
        payload = jwt.decode(actual_token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    if user.role != schemas.UserRole.author:
        raise HTTPException(status_code=403, detail="Not authorized: Authors only")
    
    return user

def clear_post_cache(post_id: int = None):
    """Invalidates cache for a specific post and all list views."""
    if post_id:
        redis_client.delete(f"post_cache_{post_id}")
    
    # Clear all paginated list caches
    list_keys = redis_client.keys("published_list_*")
    if list_keys:
        redis_client.delete(*list_keys)

# --- AUTH ROUTES ---

@app.post("/auth/login", response_model=schemas.TokenResponse)
def login(user_credentials: schemas.UserLogin, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == user_credentials.email).first()
    if not user or not auth.verify_password(user_credentials.password, user.password_hash):
        raise HTTPException(status_code=403, detail="Invalid email or password")
    
    access_token = auth.create_access_token(data={"sub": user.email})
    return {"token": access_token, "user": user}

# --- POST CONTENT ROUTES (Author Only) ---

@app.post("/posts", response_model=schemas.PostResponse)
def create_post(post_in: schemas.PostCreate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    new_post = models.Post(
        title=post_in.title,
        content=post_in.content,
        slug=slugify(post_in.title),
        author_id=current_user.id,
        status=schemas.PostStatus.draft
    )
    db.add(new_post)
    db.commit()
    db.refresh(new_post)
    # Clear list cache because a new post might eventually be published
    clear_post_cache()
    return new_post

# ==========================================
# PUBLIC FACING ENDPOINTS (WITH REDIS CACHING)
# ==========================================

@app.get("/posts/published", response_model=List[schemas.PostResponse])
def list_published_posts(skip: int = 0, limit: int = 10, db: Session = Depends(database.get_db)):
    cache_key = f"published_list_{skip}_{limit}"
    
    # 1. Try to get from Cache
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    # 2. If not in cache, get from DB
    posts = db.query(models.Post).filter(
        models.Post.status == schemas.PostStatus.published
    ).offset(skip).limit(limit).all()
    
    # 3. Save to cache (convert objects to serializable dicts first)
    serializable_data = [json.loads(schemas.PostResponse.from_orm(p).json()) for p in posts]
    redis_client.setex(cache_key, CACHE_EXPIRE, json.dumps(serializable_data))
    
    return posts

@app.get("/posts/published/{id}", response_model=schemas.PostResponse)
def get_published_post(id: int, db: Session = Depends(database.get_db)):
    cache_key = f"post_cache_{id}"
    
    # 1. Try to get from Cache
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    # 2. If not in cache, get from DB
    post = db.query(models.Post).filter(
        models.Post.id == id, 
        models.Post.status == schemas.PostStatus.published
    ).first()
    
    if not post:
        raise HTTPException(status_code=404, detail="Published post not found")
    
    # 3. Save to cache
    serializable_data = json.loads(schemas.PostResponse.from_orm(post).json())
    redis_client.setex(cache_key, CACHE_EXPIRE, json.dumps(serializable_data))
    
    return post

@app.get("/search", response_model=List[schemas.PostResponse])
def search_posts(q: str, db: Session = Depends(database.get_db)):
    """Full-text search (Not cached as queries vary too widely)."""
    results = db.query(models.Post).filter(
        models.Post.status == schemas.PostStatus.published,
        (models.Post.title.ilike(f"%{q}%")) | (models.Post.content.ilike(f"%{q}%"))
    ).all()
    return results

# ==========================================
# END PUBLIC FACING ENDPOINTS
# ==========================================

@app.get("/posts", response_model=List[schemas.PostResponse])
def list_posts(skip: int = 0, limit: int = 10, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Post).filter(models.Post.author_id == current_user.id).offset(skip).limit(limit).all()

@app.get("/posts/{id}", response_model=schemas.PostResponse)
def get_post(id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post

@app.put("/posts/{id}", response_model=schemas.PostResponse)
def update_post(id: int, post_in: schemas.PostCreate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    revision = models.PostRevision(
        post_id=post.id,
        title_snapshot=post.title,
        content_snapshot=post.content,
        revision_author_id=current_user.id
    )
    db.add(revision)
    
    post.title = post_in.title
    post.content = post_in.content
    post.slug = slugify(post_in.title)
    post.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(post)
    
    # --- INVALIDATE CACHE ---
    clear_post_cache(id)
    
    return post

@app.delete("/posts/{id}")
def delete_post(id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    db.delete(post)
    db.commit()
    
    # --- INVALIDATE CACHE ---
    clear_post_cache(id)
    
    return {"message": "Post deleted successfully"}

@app.post("/posts/{id}/publish", response_model=schemas.PostResponse)
def publish_post(id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    post.status = schemas.PostStatus.published
    post.published_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    
    # --- INVALIDATE CACHE ---
    clear_post_cache(id)
    
    return post

@app.post("/posts/{id}/schedule", response_model=schemas.PostResponse)
def schedule_post(id: int, sched: schemas.PostSchedule, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    post.status = schemas.PostStatus.scheduled
    post.scheduled_for = sched.scheduled_for
    db.commit()
    db.refresh(post)
    
    # --- INVALIDATE CACHE ---
    clear_post_cache(id)
    
    return post

@app.post("/media/upload")
def upload_media(file: UploadFile = File(...), current_user: models.User = Depends(get_current_user)):
    timestamp = int(datetime.utcnow().timestamp())
    filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {
        "filename": file.filename,
        "url": f"/uploads/{filename}",
        "content_type": file.content_type
    }

@app.get("/posts/{id}/revisions", response_model=List[schemas.PostRevisionResponse])
def get_revisions(id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
        
    revisions = db.query(models.PostRevision).filter(models.PostRevision.post_id == id).all()
    
    response = []
    for r in revisions:
        rev_user = db.query(models.User).filter(models.User.id == r.revision_author_id).first()
        timestamp = getattr(r, 'revision_timestamp', getattr(r, 'created_at', datetime.utcnow()))
        
        response.append({
            "revision_id": r.id,
            "post_id": r.post_id,
            "title_snapshot": r.title_snapshot,
            "content_snapshot": r.content_snapshot,
            "revision_author": rev_user.username if rev_user else "System",
            "revision_timestamp": timestamp
        })
    return response