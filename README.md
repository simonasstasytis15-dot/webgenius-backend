# WebGenius — Backend API

FastAPI backend for the WebGenius AI learning platform.
Stack: FastAPI · PostgreSQL · Redis · Python 3.12

---

## Deploy to Railway (for testing & sharing)

Railway gives you a live HTTPS URL in about 10 minutes, free tier included.

### 1 — Push to GitHub

```bash
cd webgenius
git init
git add .
git commit -m "initial commit"
```

Create a new **private** repo on github.com (call it `webgenius-backend`), then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/webgenius-backend.git
git push -u origin main
```

---

### 2 — Create the Railway project

1. Go to [railway.app](https://railway.app) → sign in with GitHub
2. **New Project → Deploy from GitHub repo**
3. Select `webgenius-backend`
4. Railway detects the Dockerfile and starts building

It will fail on first build — environment variables aren't set yet. Continue below.

---

### 3 — Add PostgreSQL

In your Railway project dashboard:
1. Click **+ New → Database → PostgreSQL**
2. Railway creates the database and auto-injects `DATABASE_URL` into the project

---

### 4 — Add Redis

1. Click **+ New → Database → Redis**
2. Railway auto-injects `REDIS_URL`

---

### 5 — Set environment variables

Click your **API service** (not the DB services) → **Variables** tab.

Add these manually:

| Variable | How to get the value |
|---|---|
| `APP_ENV` | `development` |
| `DEBUG` | `false` |
| `SECRET_KEY` | Run: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `JWT_SECRET` | Run the same command again (different value) |
| `ENCRYPTION_KEY` | Run: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `FRONTEND_URL` | `*` (open for now, lock down to your actual frontend URL later) |

> ⚠️ **Save ENCRYPTION_KEY in a password manager.**
> It encrypts all stored student API keys. Lose it and those keys are unreadable.

**One extra step for DATABASE_URL:**
Railway sets `DATABASE_URL` as `postgresql://...` but the app needs the async driver prefix.
In Variables, override it:

```
DATABASE_URL = postgresql+asyncpg://[paste everything after postgresql:// from the Railway-provided value]
```

You can find the Railway-provided value by clicking the PostgreSQL service → **Connect** tab.

---

### 6 — Redeploy

Push any small change (or click **Deploy** in the Railway dashboard).
Build takes 2–3 minutes. When the indicator goes green, your API is live.

- **API:** `https://your-project.up.railway.app`
- **Swagger UI:** `https://your-project.up.railway.app/docs`

---

### 7 — Create your first teacher account

For now, use the Railway database console to seed the first teacher.

1. Click the **PostgreSQL service → Data tab** (or Connect → Query)
2. Run this SQL — it creates a teacher with password `changeme123`:

```sql
INSERT INTO users (
  id, email, display_name, hashed_password,
  role, is_active, avatar_emoji, created_at, updated_at
) VALUES (
  gen_random_uuid(),
  'teacher@yourschool.com',
  'Ms. Johnson',
  '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',
  'teacher', true, '👩‍🏫', now(), now()
);
```

3. Log in via `POST /v1/auth/login` at `/docs` — use the token to create a proper password.

---

### Sharing with your partner

Send them:
- Your Railway URL
- Their login credentials
- The `/docs` link so they can explore the API interactively

---

## Run locally

```bash
# 1. Copy and fill in the env file
cp .env.example .env
# Edit .env: fill in SECRET_KEY, JWT_SECRET, ENCRYPTION_KEY

# 2. Start Postgres and Redis via Docker
docker-compose up postgres redis -d

# 3. Install Python deps
pip install -r requirements.txt

# 4. Start the API
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000
# → http://localhost:8000/docs
```

---

## API reference

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/v1/auth/login` | Any | Get JWT token |
| GET | `/v1/auth/me` | Any | Current user info |
| POST | `/v1/students/bulk` | Teacher | Create all student accounts |
| POST | `/v1/classes` | Teacher | Create a class |
| POST | `/v1/classes/{id}/students/{sid}` | Teacher | Add student to class |
| GET | `/v1/classes/{id}/students` | Teacher | Students + progress + key status |
| GET | `/v1/classes/{id}/usage` | Teacher | Today's usage per student |
| PUT | `/v1/api-keys/student/{id}` | Teacher | Set one student's API key |
| POST | `/v1/api-keys/bulk` | Teacher | Set keys for whole class |
| DELETE | `/v1/api-keys/student/{id}/{provider}` | Teacher | Revoke a key |
| POST | `/v1/api-keys/student/{id}/{provider}/validate` | Teacher | Re-check key is still valid |
| POST | `/v1/ai/chat` | Student | Gemini Flash/Pro chat |
| POST | `/v1/ai/imagen` | Student | Imagen 3 image generation |
| POST | `/v1/ai/tts/gemini` | Student | Gemini TTS voiceover |
| POST | `/v1/ai/tts/elevenlabs` | Student | ElevenLabs voiceover |
| POST | `/v1/ai/veo` | Student | Start Veo 2 video generation |
| GET | `/v1/ai/veo/poll/{op}` | Student | Poll Veo job completion |
| GET | `/health` | Any | Health check |
