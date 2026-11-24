# Milo Chat

Milo Chat is a React and FastAPI chatbot with SQLite conversation history, automatic LiteLLM key failover, and per-reply cache, model, latency, and token metadata.

## Live URLs

| Deliverable | URL |
| --- | --- |
| Frontend | [Milo on Vercel](https://lyftr-chat-assignment.vercel.app/) |
| Backend | [FastAPI on Render](https://lyftr-chat-assignment.onrender.com/) |
| Public GitHub repository | [rohangoyal3/lyftr-chat-assignment](https://github.com/rohangoyal3/lyftr-chat-assignment) |
| Demo video | [Watch the demo on Google Drive](https://drive.google.com/file/d/1yszXNRWwyFb3PTw41qn3ZLYZFQ7sm1ym/view?usp=drive_link) |

### Deploy on Render

1. Push this project to a public GitHub repository. If starting from the local checkout, commit the project files and push to the empty repository you create. `.env`, SQLite files, and the assignment PDF are ignored.
2. In Render, create a Blueprint from the repository. [`render.yaml`](render.yaml) provisions a Docker backend with a persistent disk mounted at `/data` and a static frontend. Render persistent disks require a paid backend service. [Render Blueprints](https://render.com/docs/infrastructure-as-code) · [Persistent disks](https://render.com/docs/disks)
3. Enter two distinct provider keys in the backend's `LLM_API_KEYS` secret. Use keys with access to `gemini/gemini-3.5-flash-lite` or set `LLM_MODEL` to your provider's LiteLLM model name. Separate quota pools make failover useful when a project exceeds its quota. [LiteLLM model providers](https://docs.litellm.ai/docs/providers)
4. Enter the public frontend origin, such as `https://lyftr-chat-web.onrender.com`, in the backend's `ALLOWED_ORIGINS`. Set the frontend's `VITE_API_BASE_URL` to the public backend URL, such as `https://lyftr-chat-api.onrender.com`. The service names can vary. If Render assigns different URLs, update both variables and rebuild the frontend.
5. Check the public backend `/health`, run the verification script below against the public API, and open the public frontend to send a message. Update the table with the verified links.

## Run locally

Copy `.env.example` to `.env` in the repository root and set `LLM_API_KEYS` to two comma-separated keys. Set `LLM_MODEL` if your keys use a different provider or model. Keep `.env` local and use hosting secrets for deployment.

### With Docker

With Docker Compose v2 and `make` installed, run from the repository root:

```sh
make up
```

- Frontend at `http://localhost:3000`
- Backend health at `http://localhost:8000/health`

Run `make down` to stop both containers. The named `lyftr_data` volume retains the SQLite database across restarts and `make down` followed by `make up`. On a machine without `make`, use `docker compose up --build -d` and `docker compose down`.

### Without Docker

Use Python 3.11+ and Node.js 20+ with npm. In one terminal, from the repository root:

```sh
python -m venv .venv
```

Activate the virtual environment with `.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` on macOS/Linux. Then start the API:

```sh
python -m pip install -r backend/requirements.txt
cd backend
python -m app
```

In a second terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. In standalone mode SQLite defaults to `backend/data/app.db`. To change the frontend's API target, set `VITE_API_BASE_URL` in `frontend/.env.local` or export it in the frontend terminal before starting Vite. Compose reads it from the root `.env` at build time.

| Setting | Default or meaning |
| --- | --- |
| `LLM_API_KEYS` | Required. Comma-separated keys, used in order as `key_1`, `key_2`, and so on |
| `LLM_MODEL` | `gemini/gemini-3.5-flash-lite` |
| `LLM_API_BASE` | Optional provider API base for a compatible endpoint |
| `DATABASE_URL` | `sqlite:///./data/app.db` standalone, `sqlite:////data/app.db` in Docker |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` |
| `ENABLE_FAILURE_SIMULATION` | `true` in `.env.example`, Compose and the Render Blueprint, `false` when omitted in standalone mode |
| `DEFAULT_SYSTEM_PROMPT` | A short prompt for clear and accurate answers |
| `LLM_TIMEOUT_SECONDS` | `20` seconds per provider attempt |
| `CACHE_TTL_SECONDS` | `3600` seconds, with in-memory capacity managed by LiteLLM |
| `HOST`, `PORT` | `0.0.0.0`, `8000` for the standalone backend |
| `VITE_API_BASE_URL` | `http://localhost:8000`, baked into the frontend build |

## Design decisions

- **Ordered fallback.** LiteLLM Router gives each configured key a deployment alias and tries the aliases in order. It makes one attempt per deployment and returns the winning deployment ID. All exhausted routes yield `503` with `{"detail":"all providers unavailable"}`.
- **Request-scoped simulation.** A valid `X-Simulate-Failure` excludes the specified keys from that request's route. The supported statuses are `429`, `500`, `502`, and `503`. Use `*` for every key. The request bypasses cache lookups and writes so the test exercises the eligible provider even for warmed prompts.
- **Exact cache matches.** LiteLLM's local `Cache` keys each answer on the configured model and the full ordered list of messages, including the system prompt. A hit returns the stored reply and token counts, measures its own latency, and reports a null `key_id` and zero `fallback_attempts`.
- **Transactional history.** FastAPI loads the session prompt and history in order and appends the current message for inference. SQLite writes the two messages, metadata, and optional prompt change in one transaction after success. A per-session lock keeps concurrent turns in sequence. Deploy one backend worker and one replica per SQLite file.
- **Per-request usage.** The assistant metadata uses the provider's input and output counts from the response. The input covers the full prompt of that call. The backend copies those counts from the cache on a hit.

## Verification

The backend tests use a controlled OpenAI-compatible HTTP server. They exercise the actual LiteLLM Router and cache without live credentials. From the repository root, with the virtual environment active:

```sh
python -m pip install -r backend/requirements-dev.txt
cd backend
python -m pytest -q
```

From the repository root, run the smoke checks against a running service with failure simulation enabled:

```sh
python scripts/verify_api.py
python scripts/verify_api.py --api-base https://your-api.onrender.com
```

The script checks `/health`, identical live and cached replies across sessions, per-request usage, multi-turn history, failover to `key_2` on `429` and `500`, and the `503`, `422`, and `404` error responses. It creates unique verification sessions each run.

### Demo recording outline

- **0:00–0:40** Open the public frontend, send a fresh prompt, and point out `LIVE_INFERENCE`, the model, latency, and tokens. Send a follow-up about the first message to show conversation context.
- **0:40–1:15** Start a new chat and repeat the first prompt verbatim. Show `LLM_CACHE`, the identical reply, and the lower latency.
- **1:15–2:10** Run the verification script against the public API on screen. Show `/health`, ordered history, `key_2` answering after the simulated failure, and the clean `503` when all keys fail.
- **2:10–2:30** Briefly explain why the cache uses the full prompt and how the mounted SQLite disk preserves history. Record with your own narration, upload the video where it can be opened without signing in, and add the URL above.

## Setup Used

- Codex desktop and PowerShell for implementation and local verification.
- React, Vite, FastAPI, LiteLLM, SQLite, Docker Compose, and pytest.

## Bonus features (if any)

- A session settings dialog lets you set or clear a custom system prompt. The backend stores it with the session and includes it in the cache key.
- The chat supports Markdown replies and shows the winning key ID and fallback count where applicable.
- A deployment Blueprint and a dependency-free API verification script support the live demo.
