from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import relationship, declarative_base
import enum

Base = declarative_base()

# Defining the Enums as required
class UserRole(str, enum.Enum):
    author = "author"
    public = "public"

class PostStatus(str, enum.Enum):
    draft = "draft"
    scheduled = "scheduled"
    published = "published"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(Enum(UserRole), default=UserRole.public)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    slug = Column(String, unique=True, index=True)
    content = Column(Text)
    status = Column(Enum(PostStatus), default=PostStatus.draft)
    author_id = Column(Integer, ForeignKey("users.id"))
    scheduled_for = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationship to history
    revisions = relationship("PostRevision", back_populates="post")

class PostRevision(Base):
    __tablename__ = "post_revisions"
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"))
    title_snapshot = Column(String)
    content_snapshot = Column(Text)
    revision_author_id = Column(Integer, ForeignKey("users.id"))
    revision_timestamp = Column(DateTime, server_default=func.now())

    post = relationship("Post", back_populates="revisions")