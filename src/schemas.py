from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime
from enum import Enum

class UserRole(str, Enum):
    author = "author"
    public = "public"

class PostStatus(str, Enum):
    draft = "draft"
    scheduled = "scheduled"
    published = "published"

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    role: UserRole
    # Modern Pydantic V2 Config
    model_config = ConfigDict(from_attributes=True)

class TokenResponse(BaseModel):
    token: str
    user: UserResponse

class PostBase(BaseModel):
    title: str
    content: str

class PostCreate(PostBase):
    pass

class PostSchedule(BaseModel):
    scheduled_for: datetime

class PostResponse(PostBase):
    id: int
    slug: str
    status: PostStatus
    author_id: int
    created_at: datetime
    updated_at: Optional[datetime]
    published_at: Optional[datetime]
    scheduled_for: Optional[datetime]
    
    model_config = ConfigDict(from_attributes=True)

class PostRevisionResponse(BaseModel):
    revision_id: int
    post_id: int
    title_snapshot: str
    content_snapshot: str
    revision_author: str
    revision_timestamp: datetime

    model_config = ConfigDict(from_attributes=True)