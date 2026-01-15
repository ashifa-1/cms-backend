from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from slugify import slugify
from typing import List
from datetime import datetime
from jose import jwt, JWTError

from . import models, schemas, auth, database

app = FastAPI(title="CMS Backend")

# --- DATABASE STARTUP SAFETY ---
# This prevents the app from crashing if the DB container is still "syncing"
database.wait_for_db()
models.Base.metadata.create_all(bind=database.engine)

# This defines the single "Value" box in the Authorize popup
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

# --- AUTH DEPENDENCY ---
def get_current_user(token: str = Depends(api_key_header), db: Session = Depends(database.get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    
    # Clean the token: remove 'Bearer ' if the user included it in the box
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
    
    # Ensure only authors can access these management endpoints
    if user.role != schemas.UserRole.author:
        raise HTTPException(status_code=403, detail="Not authorized: Authors only")
    
    return user

# --- AUTH ROUTES ---
@app.post("/auth/login", response_model=schemas.TokenResponse)
def login(user_credentials: schemas.UserLogin, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == user_credentials.email).first()
    if not user or not auth.verify_password(user_credentials.password, user.password_hash):
        raise HTTPException(status_code=403, detail="Invalid email or password")
    
    access_token = auth.create_access_token(data={"sub": user.email})
    return {"token": access_token, "user": user}

# --- POST CONTENT ROUTES ---

# 1. CREATE POST
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
    return new_post

# 2. LIST ALL POSTS BY AUTHOR (Pagination)
@app.get("/posts", response_model=List[schemas.PostResponse])
def list_posts(skip: int = 0, limit: int = 10, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Post).filter(models.Post.author_id == current_user.id).offset(skip).limit(limit).all()

# 3. GET SPECIFIC POST BY ID
@app.get("/posts/{id}", response_model=schemas.PostResponse)
def get_post(id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post

# 4. UPDATE POST (Triggers Versioning)
@app.put("/posts/{id}", response_model=schemas.PostResponse)
def update_post(id: int, post_in: schemas.PostCreate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # Save current version to revisions table before applying updates
    revision = models.PostRevision(
        post_id=post.id,
        title_snapshot=post.title,
        content_snapshot=post.content,
        revision_author_id=current_user.id
    )
    db.add(revision)
    
    # Apply new values
    post.title = post_in.title
    post.content = post_in.content
    post.slug = slugify(post_in.title)
    post.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(post)
    return post

# 5. DELETE POST
@app.delete("/posts/{id}")
def delete_post(id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    db.delete(post)
    db.commit()
    return {"message": "Post deleted successfully"}

# 6. PUBLISH POST
@app.post("/posts/{id}/publish", response_model=schemas.PostResponse)
def publish_post(id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    post.status = schemas.PostStatus.published
    post.published_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    return post

# 7. SCHEDULE POST
@app.post("/posts/{id}/schedule", response_model=schemas.PostResponse)
def schedule_post(id: int, sched: schemas.PostSchedule, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    post.status = schemas.PostStatus.scheduled
    post.scheduled_for = sched.scheduled_for
    db.commit()
    db.refresh(post)
    return post

# --- VERSIONING ENDPOINTS ---

# 8. GET REVISIONS HISTORY
@app.get("/posts/{id}/revisions", response_model=List[schemas.PostRevisionResponse])
def get_revisions(id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
        
    revisions = db.query(models.PostRevision).filter(models.PostRevision.post_id == id).all()
    
    response = []
    for r in revisions:
        rev_user = db.query(models.User).filter(models.User.id == r.revision_author_id).first()
        
        # Fallback for timestamp attribute names
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

# 9. RESTORE A PREVIOUS VERSION
@app.post("/posts/{id}/restore/{revision_id}", response_model=schemas.PostResponse)
def restore_revision(id: int, revision_id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    post = db.query(models.Post).filter(models.Post.id == id, models.Post.author_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
        
    revision = db.query(models.PostRevision).filter(models.PostRevision.id == revision_id, models.PostRevision.post_id == id).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
        
    post.title = revision.title_snapshot
    post.content = revision.content_snapshot
    post.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(post)
    return post
# Ready