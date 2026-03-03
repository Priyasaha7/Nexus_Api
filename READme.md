# NexusAPI

A multi-tenant, credit-gated backend API built with FastAPI, PostgreSQL, Redis, and ARQ. Built as part of the Kasparro AI Backend Engineering assignment.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local Setup](#local-setup)
- [Environment Variables](#environment-variables)
- [Running Migrations](#running-migrations)
- [Running the Application](#running-the-application)
- [Running the Background Worker](#running-the-background-worker)
- [API Reference](#api-reference)
- [Example API Calls](#example-api-calls)
- [Failure Mode Handling](#failure-mode-handling)
- [Deployment](#deployment)

---

## Overview

NexusAPI is a production-shaped backend platform that provides:

- **Multi-tenancy** — Every user belongs to an organisation. Data from one organisation is never visible to another. Enforced at the database query level.
- **Credit gating** — API access costs credits. Credits are tracked via an append-only transaction ledger. No balance column — the current balance is always derived from the sum of transactions.
- **Google OAuth** — Users authenticate via Google. JWT tokens are issued on login and validated on every protected request.
- **Background jobs** — The summarise endpoint processes work asynchronously via ARQ and Redis. Job status is pollable.
- **Idempotency** — Duplicate requests with the same `Idempotency-Key` return the original response without deducting credits again.
- **Rate limiting** — 60 requests per minute per organisation, shared across all product endpoints.

---

## Tech Stack

| Layer           | Technology                 |
| --------------- | -------------------------- |
| Framework       | FastAPI (Python 3.11+)     |
| Database        | PostgreSQL (via Neon.tech) |
| ORM             | SQLAlchemy (async)         |
| Migrations      | Alembic                    |
| Auth            | Google OAuth 2.0 + JWT     |
| Background Jobs | ARQ + Redis                |
| Rate Limiting   | SlowAPI + Redis            |
| Config          | Pydantic Settings          |

---

## Project Structure

```
nexus-api/
├── app/
│   ├── main.py                    # FastAPI app, middleware, global handlers
│   ├── config.py                  # Environment variable loading
│   ├── database.py                # Async DB engine and session
│   ├── dependencies.py            # JWT auth dependency (get_current_user)
│   ├── exceptions.py              # Custom exceptions (InsufficientCreditsError)
│   ├── rate_limiter.py            # Rate limiting setup (per-org, shared bucket)
│   ├── worker.py                  # ARQ background worker + stale job cleanup
│   ├── models/
│   │   ├── organisation.py        # Organisation table
│   │   ├── user.py                # User table
│   │   ├── credit_transaction.py  # Credit ledger table
│   │   ├── job.py                 # Background job table
│   │   └── idempotency.py         # Idempotency records table
│   ├── routers/
│   │   ├── auth.py                # /auth/google, /auth/callback
│   │   ├── users.py               # /me
│   │   ├── credits.py             # /credits/balance, /credits/grant
│   │   └── api.py                 # /api/analyse, /api/summarise, /api/jobs/{id}
│   └── services/
│       ├── credit_service.py      # deduct_credits, grant_credits, get_balance
│       └── idempotency_service.py # get/save idempotency records
├── alembic/                       # Migration files
├── alembic.ini
├── .env                           # Local environment variables (never commit)
├── .env.example                   # Template for environment variables
├── requirements.txt
├── DECISIONS.md
└── README.md
```

---

## Prerequisites

Before running this project, make sure you have the following installed:

- Python 3.11 or higher
- Redis (running locally on port 6379)
- A PostgreSQL database (local or cloud — we recommend [Neon.tech](https://neon.tech) for free cloud PostgreSQL)
- A Google Cloud project with OAuth 2.0 credentials configured

---

## Local Setup

### Step 1 — Clone the repository

```bash
git clone https://github.com/your-username/nexus-api.git
cd nexus-api
```

### Step 2 — Create and activate a virtual environment

```bash
python -m venv venv

# Mac/Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Set up environment variables

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with your actual credentials. See [Environment Variables](#environment-variables) section below for details on each variable.

### Step 5 — Run database migrations

```bash
alembic upgrade head
```

### Step 6 — Start Redis

Make sure Redis is running locally:

```bash
redis-server
```

Verify it is running:

```bash
redis-cli ping
# Expected output: PONG
```

### Step 7 — Start the application

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

Interactive API docs (Swagger UI) are available at `http://localhost:8000/docs`.

### Step 8 — Start the background worker (separate terminal)

```bash
arq app.worker.WorkerSettings
```

This worker processes summarise jobs from the Redis queue and runs a cleanup job every 60 seconds to mark stale jobs as failed.

---

## Environment Variables

All configuration is loaded from environment variables. No secrets are hardcoded anywhere in the codebase.

Create a `.env` file in the root of the project with the following variables:

```bash
# ── Database ──────────────────────────────────────────────────
# Async PostgreSQL connection string
# Format: postgresql+asyncpg://user:password@host/dbname
# For Neon.tech: replace ?sslmode=require with ?ssl=true
DATABASE_URL=postgresql+asyncpg://user:password@host/nexusdb?ssl=true

# ── JWT ───────────────────────────────────────────────────────
# Secret key used to sign and verify JWT tokens
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your-super-secret-key-minimum-32-characters

# Signing algorithm — do not change
ALGORITHM=HS256

# Token expiry in hours
ACCESS_TOKEN_EXPIRE_HOURS=24

# ── Google OAuth ──────────────────────────────────────────────
# From Google Cloud Console → APIs & Services → Credentials
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-client-secret

# Must match the redirect URI registered in Google Cloud Console
# For local development: http://localhost:8000/auth/callback
# For production: https://your-deployed-url.com/auth/callback
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# ── Redis ─────────────────────────────────────────────────────
# Redis connection URL used for background jobs and rate limiting
# For local: redis://localhost:6379
# For production: redis://your-redis-host:6379
REDIS_URL=redis://localhost:6379

# ── Debug ─────────────────────────────────────────────────────
# Set to true to enable SQL query logging (development only)
# Set to false in production
DEBUG=false
```

### `.env.example`

An `.env.example` file is included in the repository. It contains all required keys with placeholder values. Never commit your actual `.env` file.

---

## Running Migrations

This project uses Alembic for database migrations. Every schema change is versioned — never edit the database directly.

**Apply all migrations (run on first setup and after every pull):**

```bash
alembic upgrade head
```

**Create a new migration after changing a model:**

```bash
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

**Check current migration state:**

```bash
alembic current
```

**Rollback one migration:**

```bash
alembic downgrade -1
```

---

## Running the Application

**Development (with auto-reload):**

```bash
uvicorn app.main:app --reload
```

**Production:**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

**Background worker (required for /api/summarise to process jobs):**

```bash
arq app.worker.WorkerSettings
```

The worker must run alongside the API server. Without it, summarise jobs will remain in `pending` state and be marked as `failed` after 5 minutes by the built-in stale job cleanup.

---

## API Reference

All protected endpoints require a `Bearer` token in the `Authorization` header obtained from `/auth/callback`.

| Method | Path                 | Auth      | Description                                                |
| ------ | -------------------- | --------- | ---------------------------------------------------------- |
| GET    | `/health`            | None      | Returns 200 if healthy, 503 if database unreachable        |
| GET    | `/auth/google`       | None      | Redirects to Google OAuth login                            |
| GET    | `/auth/callback`     | None      | Handles OAuth callback, returns JWT                        |
| GET    | `/me`                | JWT       | Returns current user profile and organisation              |
| GET    | `/credits/balance`   | JWT       | Returns org credit balance and last 10 transactions        |
| POST   | `/credits/grant`     | Admin JWT | Grants credits to the organisation                         |
| POST   | `/api/analyse`       | JWT       | Synchronous text analysis. Costs 25 credits                |
| POST   | `/api/summarise`     | JWT       | Async text summarisation. Costs 10 credits. Returns job_id |
| GET    | `/api/jobs/{job_id}` | JWT       | Polls background job status                                |

---

## Example API Calls

Replace `YOUR_TOKEN` with the `access_token` received from `/auth/callback`.

### 1. Health Check

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "healthy",
  "database": "connected"
}
```

### 2. Get Current User Profile

```bash
curl http://localhost:8000/me \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Expected response:

```json
{
  "id": "05e173a8-d899-44fd-a36d-8d539b009fd7",
  "email": "user@gmail.com",
  "name": "Your Name",
  "role": "admin",
  "organisation": {
    "id": "0d32a3fb-d392-4926-80fe-3f1ecdbff2c5",
    "name": "gmail.com",
    "slug": "gmail-com"
  }
}
```

### 3. Grant Credits (Admin only)

```bash
curl -X POST http://localhost:8000/credits/grant \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"amount\": 500, \"reason\": \"Initial credit grant\"}"
```

Expected response:

```json
{
  "message": "Credits granted successfully",
  "transaction_id": "5c64ec29-b653-49c7-b05d-2468d8dfb2c2",
  "amount_added": 500,
  "new_balance": 500
}
```

### 4. Check Credit Balance

```bash
curl http://localhost:8000/credits/balance \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Expected response:

```json
{
  "organisation_id": "0d32a3fb-d392-4926-80fe-3f1ecdbff2c5",
  "balance": 500,
  "recent_transactions": [
    {
      "id": "5c64ec29-b653-49c7-b05d-2468d8dfb2c2",
      "amount": 500,
      "reason": "Initial credit grant",
      "created_at": "2026-03-01T06:47:42.176270"
    }
  ]
}
```

### 5. Analyse Text (Synchronous — costs 25 credits)

```bash
curl -X POST http://localhost:8000/api/analyse \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"The quick brown fox jumps over the lazy dog\"}"
```

Expected response:

```json
{
  "result": "Analysis complete. Word count: 9. Unique words: 8.",
  "credits_remaining": 475
}
```

### 6. Analyse with Idempotency Key (safe to retry)

```bash
curl -X POST http://localhost:8000/api/analyse \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: unique-key-abc-123" \
  -d "{\"text\": \"The quick brown fox jumps over the lazy dog\"}"
```

Sending the exact same request again with the same `Idempotency-Key` within 24 hours returns the original response without deducting credits.

### 7. Summarise Text (Async — costs 10 credits)

```bash
curl -X POST http://localhost:8000/api/summarise \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"Artificial intelligence is transforming industries across the world by enabling machines to learn from data and make intelligent decisions.\"}"
```

Expected response (returned immediately, under 200ms):

```json
{
  "job_id": "fda7446f-0637-4172-a710-5cf3987fd48d",
  "status": "pending",
  "message": "Job queued. Poll /api/jobs/{job_id} for result."
}
```

### 8. Poll Job Status

```bash
curl http://localhost:8000/api/jobs/fda7446f-0637-4172-a710-5cf3987fd48d \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Expected response when completed:

```json
{
  "job_id": "fda7446f-0637-4172-a710-5cf3987fd48d",
  "status": "completed",
  "result": "Summary (19 words): Artificial intelligence is transforming industries across the world by enabling machines to learn from data and make",
  "error": null,
  "created_at": "2026-03-01T10:44:14.053185",
  "updated_at": "2026-03-01T10:44:15.763871"
}
```

---

## Failure Mode Handling

The system handles all failure scenarios explicitly with correct HTTP status codes and structured error responses.

**Authentication failures:**

- Missing token → `401 unauthorized`
- Expired token → `401 token_expired`
- Tampered token → `401 invalid_token`
- User deleted from DB → `401 user_not_found`

**Credit failures:**

- 0 or insufficient credits → `402 insufficient_credits` with current balance
- Two simultaneous requests with exact credits → only one succeeds (PostgreSQL `SELECT FOR UPDATE` lock)
- Worker fails after credits deducted → job marked `failed` after 5 minutes, credits logged for manual review

**Input validation failures:**

- Text under 10 characters → `422 validation_error`
- Text over 2000 characters → `422 validation_error`
- Missing text field → `422 validation_error`
- Job ID not found → `404 job_not_found`
- Job ID belongs to another org → `403 forbidden`

**Infrastructure failures:**

- Database unreachable → `/health` returns `503`
- Redis unreachable → rate limiting fails open (requests allowed through), API keeps running
- Job pending over 5 minutes → automatically marked `failed` by scheduled worker cleanup

**All error responses follow this consistent shape:**

```json
{
  "error": "error_code",
  "message": "Human readable description.",
  "request_id": "uuid-for-support-reference"
}
```

---

## Deployment

This API is deployed on [Railway](https://railway.app) (or Render/Fly.io).

**Live URL:** `https://web-production-9d4b6.up.railway.app`

**To deploy your own instance:**

1. Push your code to GitHub
2. Create a new project on Railway → connect your GitHub repo
3. Add all environment variables from the [Environment Variables](#environment-variables) section
4. Update `GOOGLE_REDIRECT_URI` to your deployed URL: `https://your-url.up.railway.app/auth/callback`
5. Update the redirect URI in Google Cloud Console to match
6. Add a Redis service in Railway and update `REDIS_URL`
7. Railway auto-deploys on every push to main

---

## License

Built for the Kasparro AI Backend Engineering internship assignment.
