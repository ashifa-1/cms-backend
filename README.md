# CMS Backend Project

This repository contains a production-style backend API for a simple content management system (CMS). It supports draft/scheduled/published workflows, content versioning, full-text search, media uploads, JWT authentication with role-based access, caching, and a background job for scheduled publishing. The entire stack is containerized using Docker and can be started with a single `docker-compose up` command.

---

## Architecture
The service consists of three main components:

1. **API Server** (`app` service) – FastAPI application exposing REST endpoints and handling authentication, content management, and caching logic. It's stateless and relies on JWTs for authentication.
2. **Database** (`db` service) – PostgreSQL stores users, posts, and post revisions. SQLAlchemy ORM is used with transaction-aware operations, and indices are applied for performance.
3. **Cache** (`cache` service) – Redis is used to cache published posts and list queries. The service uses a cache‑aside strategy with explicit invalidation when content changes.
4. **Worker** (`worker` service) – A lightweight Python process that polls the database periodically (every 30s) and publishes scheduled posts when their time arrives. The worker is idempotent and also clears relevant Redis entries.

Detailed component interactions are documented in `ARCHITECTURE.md`.

---

## Getting Started
1. Install [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/).
2. Clone the repo and navigate to the project directory.
3. Run:
   ```sh
   docker-compose up --build
   ```
4. The API will be reachable at `http://localhost:8000`.
5. Swagger/OpenAPI documentation is automatically available at `http://localhost:8000/docs`.
6. An initial author user is seeded automatically:
   - **Email:** `admin@example.com`
   - **Password:** `admin123`

---

## API Overview
The application exposes the following main endpoints (see full spec via `/docs`):

- `POST /auth/login` – obtain JWT token.
- Author-only routes (require `Authorization: Bearer <token>`):
  - CRUD on `/posts` (including `/publish` and `/schedule`).
  - `/posts/{id}/revisions` to view version history.
  - `/media/upload` for file uploads.
- Public routes:
  - `/posts/published` and `/posts/published/{id}`
  - `/search?q=` for full-text queries.

Pagination is supported via `skip`/`limit` query parameters.

---

## Testing
Automated tests are included under `tests/`. They exercise core workflows, caching logic, and the background worker. To run them inside the container:

```sh

docker-compose run --rm app bash
# inside container
pytest
```

The `submission.yml` file defines commands for automated evaluation.
