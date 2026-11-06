# FastAPI Agent Shell — SQLite sign-in, chat, and future agent extensions

A GitHub/Codespaces → Render-ready single-port FastAPI shell. It **reimplements the sign-in behavior from the attached `fastapi-site-main` project**, while deliberately eliminating its Redis dependency. It is a starting shell for further development, **not** a completed A2A/wallet/payment implementation.

## What's included

- HTML/Jinja2 login and chat pages; single Uvicorn port (`app.main:app`).
- `username,password` CSV import; Werkzeug-compatible scrypt password hashing using Python’s standard library; existing users are never overwritten.
- Signed HttpOnly session cookie (`SESSION_SECRET_KEY`), SameSite=Lax, CSRF double-submit cookie.
- One active session per user (second login rejected), 30-minute sliding inactivity timeout, explicit EXIT.
- SQLite persistence for users, login sessions, chat messages, current long-term memory, and memory summaries by session.
- OpenAI Responses API with optional built-in web search; editable `harness/instructions.md`.
- Chat context is passed to OpenAI as simple `{role,content}` string pairs (not Gradio history structures).
- EXIT summarizes conversation to saved memory; **if OpenAI fails, EXIT preserves all chat and retains the active session for retry**.
- Chat history is not deleted when a session ends or times out. An uncleanly expired session's messages remain in SQLite; automatic summarization on subsequent login is **not yet implemented** (a conscious simplification from the original Redis project).
- Clear extension points for A2A tasks, student directories, wallet integration, audit, etc.

## Repo layout

```text
.devcontainer/devcontainer.json
app/
  main.py          # Login/chat/API, one ASGI app
  security.py      # Cookie signing and CSRF
  database.py      # SQLite engine, WAL
  models.py        # Users, sessions, chat, memory
  agent.py         # OpenAI integration, future tools
  settings.py
harness/
  instructions.md
  memory_instructions.md
scripts/
  init_db.py
  import_users.py
static/
  chat.js
  style.css
templates/
  login.html
  chat.html
requirements.txt
users.example.csv   # FICTITIOUS examples, not the uploaded login list
.env.example
.gitignore
```

## Codespaces setup (dependencies automatic; database, users, and server manual)

1. Create a GitHub repo from the contents of this ZIP. Keep `.devcontainer/` and `.gitignore` folders/files intact.
2. In the repo's GitHub Codespaces secrets, set:
   - `OPENAI_API_KEY` — your OpenAI API key.
   - `SESSION_SECRET_KEY` — long random value; example generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
3. Create a Codespace. The devcontainer **only installs `requirements.txt`**. It does **not** run `scripts/init_db.py`, import user accounts, or launch Uvicorn. `forwardPorts` only makes port 8000 convenient to open after you start the server; it does not start the server.
4. Optionally initialize the SQLite schema manually (the application also creates missing tables automatically on FastAPI startup; user import also initializes the schema if needed):
   ```bash
   python scripts/init_db.py
   ```
5. Import accounts manually. For a quick demonstration, use the included **fictional** `users.example.csv` file:
   ```bash
   python scripts/import_users.py users.example.csv --dry-run
   python scripts/import_users.py users.example.csv
   ```
   For actual class accounts, replace `users.example.csv` with the path to a separate `username,password` CSV uploaded privately to your Codespace. Never commit a CSV containing real student passwords to Git.
6. Start the server manually:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   Open the forwarded port 8000 and sign in.

The bundled `users.example.csv` is intended for fictional test accounts only. Keep any real login CSV only in your Codespace, not in Git. Chat sends on Enter or the visible Send button; Shift+Enter inserts a newline. EXIT attempts to save memory then releases the session.

To test on `http://localhost:8000`, set `COOKIE_SECURE=false` in your local environment. **Do not set it to false for production HTTPS.**

## Render deployment (separate from Codespaces manual launch)

Render **Web Service**, runtime **Python**, not a static site or database service. Connect the repo; auto-deploy on Git push.

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (**Render requires an explicit start command**; this does not change the fact that Codespaces launches Uvicorn manually). FastAPI initializes missing SQLite tables at startup; account import remains manual.
- Render Starter paid Web Service with persistent disk mounted at **`/var/data`**.
- Environment variables:
  - `DATA_DIR=/var/data` (critical — SQLite stays on the disk)
  - `SESSION_SECRET_KEY=<same stable secret after every redeploy>`
  - `OPENAI_API_KEY=<key>`
  - `COOKIE_SECURE=true`
  - `OPENAI_MODEL=gpt-4.1-mini` (or another supported Responses/web-search model)
  - `SESSION_TIMEOUT_MINUTES=30`

`OPENAI_API_KEY` and `SESSION_SECRET_KEY` should be supplied as Codespaces secrets for development and Render environment variables for deployment. Never put their values in source control.

### Importing users on Render

The database on the new persistent disk begins empty. **Accounts created in Codespaces do not automatically appear on Render.** Import via Render Shell (if your service supports interactive shell access):

```bash
python scripts/import_users.py /var/data/users.csv
```

The example users are **not** automatically imported on Render. If Render Shell or uploading files is unavailable, do **not** commit plaintext passwords to Git. Instead, perform a one-time secure admin bootstrap using a script run against the mounted disk in a compatible environment, or migrate an existing SQLite DB file (including a consistent backup) to the disk. The shell does not expose a public user-import HTTP endpoint.

If creating the shell on Codespaces *before* migrating to Render, you may keep the login CSV local and arrange secure database migration; otherwise you must create/import the users on Render independently.

### SQLite notes

Only one Render instance should write this SQLite database. Render persistent disk is adequate; do not create a Render Postgres or Redis service. WAL writes `agent.sqlite3-wal` and `agent.sqlite3-shm` beside the DB, on the same disk. Data and sessions survive normal redeploys. Existing Codespaces data is **not** automatically copied to Render.

### Future integrations

Extend `app/agent.py` for multiple agents, tools, and policies; create separate modules for wallet/keystore, audits, A2A registry and A2A task lifecycle. If adding a wallet, place it under `/var/data/wallet` on Render. This shell deliberately has **no exposed public A2A endpoint yet**; a complete A2A implementation should use a compatible SDK/protocol version.

## Important differences from the original attachment

| Behavior | Original | New shell |
|---|---|---|
| Password hashes / CSV import | Yes | Retained |
| One active login / inactivity timeout | Redis | SQLite |
| CSRF and signed cookie | Yes | Retained |
| Chat history | Redis (24h TTL) | SQLite (retained) |
| Memory on EXIT | Redis→SQLite | SQLite→SQLite |
| Recovery of abandoned chats on subsequent login | Yes, when still in Redis | **Not automated**; archived records retained |
| Login-attempt throttling | Redis | SQLite (5 failed attempts per username/IP bucket per 10 minutes) |
| OpenAI/web search | Yes | Yes |
| Render dependency | Redis + database | One disk / SQLite |

## Optional developer checks

```bash
python -m compileall -q app scripts
pytest -q
```

`python scripts/init_db.py` is an optional manual database setup step, **not** part of Codespaces initialization.

Verify manually: valid login, invalid login, second simultaneous login rejected, EXIT releases session, login again succeeds, post-follow-up chat history, cookie expiration, and Render disk persistence. Real OpenAI responses require a valid key and credits.
