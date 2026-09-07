# Repository Guidelines

## Project Structure & Module Organization

- `backend/src/app/` contains the FastAPI application, organized by API, domain, engine, LLM, sandbox, RBAC, SSE, and tracing concerns.
- `backend/tests/` contains pytest coverage; `backend/alembic/` holds migrations and `backend/seed/` holds idempotent seed scripts.
- `frontend/src/` contains the React/Vite SPA, including user workbench and admin pages. `services/` contains the sandbox daemon, mock sales service, and forecast model.
- `tools/` contains sandbox-executed business tools; `docs/` contains the PRD, API contracts, plans, and task status. Root Docker files define the deployable stack.

## Build, Test, and Development Commands

Run commands from Git Bash. For backend work, use `cd backend && uv sync` to install locked dependencies. Start or repair the local database with `bash scripts/dev_db_pg.sh`, then run `uv run uvicorn app.main:app --port 8000`. Use `bash scripts/start_dev_stack.sh` for the local integration stack and `bash scripts/stop_dev_stack.sh` to stop it.

Run backend tests with `cd backend && uv run pytest`; fixtures require PostgreSQL and isolate each test schema. Run `uv run pytest tests/test_engine.py -k send` for a focused test. Run `uv run ruff check .` for linting. For the frontend, run `cd frontend && npm install`, `npm run dev`, or `npm run build` (TypeScript check plus Vite production build). Frontend has no test script.

## Coding Style & Naming Conventions

Use four-space indentation in Python and follow Ruff (`E`, `F`, `I`, `W`; 120-column configuration). Use `snake_case` for Python modules/functions and `PascalCase` for React components; keep TypeScript imports and existing two-space JSX formatting consistent with nearby code. Add new environment variables to both `config.py` and the appropriate `.env.example` file.

## Testing Guidelines

Name backend tests `test_*.py` and test functions `test_*`. Add regression tests beside the affected API, service, or engine behavior. Contract changes should update the relevant tests and `docs/api-contract.md`; run the full backend suite before opening a PR.

## Commit & Pull Request Guidelines

Keep commits small and imperative. Existing history uses concise prefixes such as `release:` and `docs:`; use a similarly clear scope (for example, `feat: add forecast trace`). PRs should explain behavior and validation commands, link the relevant task or issue, call out migration/configuration changes, and include UI screenshots or API examples when applicable.

## Security & Configuration

Never commit `.env` files, credentials, tokens, database dumps, or generated logs. Start from `.env.example`, use development-only credentials locally, and review Docker/network changes carefully because the sandbox and internal services rely on restricted networking and internal tokens.
