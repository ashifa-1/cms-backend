import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import fakeredis

# imports from app code
from src.main import app, redis_client
from src.database import Base, get_db
from src import worker

# set up an isolated SQLite DB for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    # seed an author account for authentication tests
    from src import auth, models
    db = TestingSessionLocal()
    hashed_pw = auth.get_password_hash("admin123")
    db.add(models.User(username="admin", email="admin@example.com", password_hash=hashed_pw, role="author"))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("src.main.redis_client", fake)
    monkeypatch.setattr("src.worker.redis_client", fake)
    return fake


def get_auth_header():
    resp = client.post("/auth/login", json={"email": "admin@example.com", "password": "admin123"})
    assert resp.status_code == 200
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_auth_login():
    h = get_auth_header()
    assert "Bearer" in h["Authorization"]


def test_create_update_delete_post_and_revisions():
    headers = get_auth_header()
    # create
    resp = client.post("/posts", json={"title": "Hello", "content": "World"}, headers=headers)
    assert resp.status_code == 200
    post = resp.json()
    assert post["slug"].startswith("hello")
    post_id = post["id"]

    # update
    resp = client.put(f"/posts/{post_id}", json={"title": "Hello again", "content": "Universe"}, headers=headers)
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["title"] == "Hello again"
    # revisions endpoint
    resp = client.get(f"/posts/{post_id}/revisions", headers=headers)
    revs = resp.json()
    assert len(revs) == 1
    assert revs[0]["title_snapshot"] == "Hello"

    # delete
    resp = client.delete(f"/posts/{post_id}", headers=headers)
    assert resp.status_code == 200
    resp = client.get(f"/posts/{post_id}", headers=headers)
    assert resp.status_code == 404


def test_publish_and_search_cache_and_listing():
    headers = get_auth_header()
    # create draft
    resp = client.post("/posts", json={"title": "Searchable", "content": "Find me"}, headers=headers)
    post = resp.json()
    post_id = post["id"]

    # publish immediately
    resp = client.post(f"/posts/{post_id}/publish", headers=headers)
    assert resp.status_code == 200
    published = resp.json()
    assert published["status"] == "published"
    assert published["published_at"] is not None

    # public list should return it and cache should populate
    resp = client.get("/posts/published")
    assert resp.status_code == 200
    results = resp.json()
    assert any(p["id"] == post_id for p in results)
    assert redis_client.get("published_list_0_10") is not None

    # search should find
    resp = client.get("/search?q=Find")
    assert resp.status_code == 200
    assert any(p["id"] == post_id for p in resp.json())

    # update published post to check cache invalidation
    resp = client.put(f"/posts/{post_id}", json={"title": "Searchable", "content": "Updated"}, headers=headers)
    assert resp.status_code == 200
    assert redis_client.get(f"post_cache_{post_id}") is None


def test_schedule_and_worker_runs():
    headers = get_auth_header()
    future = datetime.utcnow() + timedelta(seconds=1)
    resp = client.post("/posts", json={"title": "Timer", "content": "Tick"}, headers=headers)
    post = resp.json()
    post_id = post["id"]
    resp = client.post(f"/posts/{post_id}/schedule", json={"scheduled_for": future.isoformat()}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "scheduled"

    # run worker to simulate passage of time
    worker.publish_scheduled_posts()
    resp = client.get(f"/posts/{post_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"


def test_public_endpoints_access():
    resp = client.get("/posts/published")
    assert resp.status_code == 200
    resp = client.get("/posts/published/1")
    assert resp.status_code in (200, 404)


def test_search_endpoint_public():
    resp = client.get("/search?q=hello")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_slug_uniqueness():
    headers = get_auth_header()
    r1 = client.post("/posts", json={"title": "Duplicate", "content": "a"}, headers=headers)
    r2 = client.post("/posts", json={"title": "Duplicate", "content": "b"}, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["slug"] != r2.json()["slug"]
