# FinAlly

AI-powered trading workstation: live-streaming watchlist, simulated portfolio, and an LLM chat assistant that can analyze and execute trades. See `SPEC.md` for the full design.

## Prerequisites

- Docker
- An `OPENROUTER_API_KEY` (required for the AI chat). Copy `.env.example` to `.env` and fill it in.

```bash
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY
```

## Start

One command from the repo root.

**macOS / Linux:**
```bash
./scripts/start_mac.sh
```

**Windows (PowerShell):**
```powershell
./scripts/start_windows.ps1
```

The app is then available at http://localhost:8000.

## Stop

**macOS / Linux:**
```bash
./scripts/stop_mac.sh
```

**Windows (PowerShell):**
```powershell
./scripts/stop_windows.ps1
```

The SQLite database persists in a Docker volume across restarts.

## Layout

- `frontend/` — Next.js (TypeScript, static export)
- `backend/` — FastAPI (Python, `uv`)
- `db/` — SQLite volume mount (`finally.db` is created here at runtime, gitignored)
- `scripts/` — start/stop wrappers
- `test/` — Playwright E2E tests
- `planning/` — agent-shared design docs
