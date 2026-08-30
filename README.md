# Voxdoc 🎙️

Voice-first document assistant. Upload PDFs, Word docs, spreadsheets or web
pages, then ask questions about them — by typing or by speaking.

## Features

- 📄 **Chat over documents** — PDF, DOCX, TXT, and scraped web pages
- 📊 **Real spreadsheet analysis** — the agent writes pandas code, runs it in a
  sandbox, and reports the computed number (CSV, Excel)
- 🔍 **Hybrid search** — dense embeddings + BM25, fused with Reciprocal Rank Fusion
- 🧠 **Local embeddings** — runs on CPU via ONNX; indexing makes **zero** API calls
- 📝 **Auto-summary** on upload, generated once and stored
- 🎙️ **Voice input** — browser speech recognition, with a Gemini fallback
- 🔊 **Voice output** — answers read aloud via the browser's speech synthesiser
- 🔐 **Real auth** — bcrypt passwords, verified JWTs, per-workspace isolation
- ⚡ **Answer cache** — a repeated question costs nothing

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI, LangGraph, `google-genai` |
| Frontend | React 18, Vite, Tailwind CSS |
| Vector store | ChromaDB (persistent) |
| Embeddings | fastembed / ONNX — `BAAI/bge-small-en-v1.5`, 384-d |
| Keyword search | BM25 (`rank-bm25`), cached per workspace |
| Database | SQLite via SQLAlchemy |

---

## Quick start (Docker)

```bash
cp backend/.env.example backend/.env    # then add your GEMINI_API_KEY
docker compose up --build
```

Open <http://localhost:5173>. The API is on <http://localhost:8000>, docs at
<http://localhost:8000/docs>.

## Local development

**Backend** (Python 3.12+; 3.14 works and is what this was built against):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # add your GEMINI_API_KEY
uvicorn app.main:app --reload
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `localhost:8000`, so both run side by side with no CORS
configuration needed.

**Tests** — 89 tests, fully offline (every Gemini call is stubbed):

```bash
cd backend && pytest -q
```

---

## How it works

```
React ──/api──> FastAPI ──> LangGraph agent ──> Gemini
                   │              │
                   │              ├── search_documents ──> hybrid search
                   │              │                          ├── Chroma (dense)
                   │              │                          └── BM25 (sparse)
                   │              └── run_pandas_code ─────> AST sandbox
                   └──> SQLite (users, workspaces, messages, answer cache)
```

The agent is an explicit LangGraph `StateGraph` rather than the `create_react_agent`
one-liner, so the ReAct loop is visible and controllable:

```
START ─> call_model ──(no tool calls)──> END
            │  ▲
            ▼  └── tool results appended to state
          tools
```

`workspace_id` and the spreadsheet location reach the tools through LangGraph's
`InjectedState`, so they never appear in the model's tool schema — the model
supplies only a search query or a line of pandas.

### Keeping API costs down

| Technique | Effect |
|---|---|
| Local ONNX embeddings | Indexing a 200-page PDF: hundreds of API calls → **0** |
| Answer cache, keyed on question + document-set version | Repeat questions → **0** calls |
| Browser `SpeechRecognition` / `speechSynthesis` | Voice in and out → **0** calls |
| Model tiering (`flash-lite` for summaries, `flash` for chat) | Cheaper on the high-volume path |
| Summaries generated once and stored | One call per document, ever |
| History capped in SQL, schema-only spreadsheet context | Smaller prompts |
| `recursion_limit` on the graph | Bounds a runaway tool loop |
| Cached BM25 index | Removes a full-corpus rebuild per query |

In practice a normal session only calls Gemini for **new** questions.

### The pandas sandbox

The agent writes pandas code, which is validated before it runs:

- the AST is rejected for imports, dunder names or attributes, function/class
  definitions, and calls to anything outside a small builtin allowlist;
- `__builtins__` is replaced with a curated mapping;
- `pd` is a proxy exposing only analysis helpers — the real module has
  `read_pickle` (arbitrary code execution) and a family of file writers;
- execution is capped by wall clock and output size.

Blocking dunder access is the load-bearing rule: nearly every Python sandbox
escape routes through `__class__` / `__subclasses__` / `__globals__`.
`test_sandbox.py` asserts 20 specific escape attempts are refused.

---

## Configuration

All settings live in `backend/.env` — see [.env.example](backend/.env.example).
The ones worth knowing:

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | — | Required |
| `SECRET_KEY` | — | App refuses to start with the default unless `DEBUG=true` |
| `EMBEDDING_PROVIDER` | `local` | `local` or `gemini` |
| `CHAT_MODEL` | `gemini-3.6-flash` | Google retires models often — check the [deprecations page](https://ai.google.dev/gemini-api/docs/deprecations) |
| `MAX_UPLOAD_MB` | `25` | |

**Changing `EMBEDDING_PROVIDER` or `LOCAL_EMBEDDING_MODEL` invalidates every
stored vector.** Delete `backend/chroma_db/` and re-upload; the app raises a
clear error rather than returning quietly wrong results.

### Behind a corporate proxy

HuggingFace's Xet backend is blocked on many corporate networks, which makes the
first model download hang at 0 bytes. The app sets `HF_HUB_DISABLE_XET=1` itself,
so this should just work — if you hit it elsewhere, that is the fix.

---

## Project structure

```
voxdoc/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + lifespan
│   │   ├── config.py          # settings (models, limits, paths)
│   │   ├── deps.py            # auth + workspace-ownership dependencies
│   │   ├── security.py        # bcrypt hashing, JWT encode/decode
│   │   ├── rate_limit.py
│   │   ├── routers/           # auth, chat, documents, voice
│   │   ├── agent/
│   │   │   ├── graph.py       # LangGraph StateGraph
│   │   │   ├── tools.py       # search_documents, run_pandas_code
│   │   │   ├── sandbox.py     # AST allowlist + restricted exec
│   │   │   └── prompts.py
│   │   ├── services/          # gemini, embeddings, vector_store,
│   │   │                      # hybrid_search, ingestion
│   │   └── db/                # models, crud, session
│   └── tests/                 # 89 tests, no network required
├── frontend/
│   └── src/
│       ├── pages/             # Login, Workspace
│       ├── components/        # Sidebar, DocumentPanel, SummaryCard,
│       │                      # ChatWindow, VoiceButton
│       ├── context/           # AuthContext
│       └── services/api.js    # axios client + interceptors
└── docker-compose.yml
```

## Known limitations

- **No migrations.** Tables are created with `create_all`; a model change means
  deleting `voxdoc.db`. Add Alembic before this holds data you care about.
- **The sandbox timeout cannot kill a thread.** Python has no safe way to stop a
  running thread, so a runaway computation keeps using CPU in the background
  until it finishes. It is bounded in Docker by the container's limits.
- **Answers are not streamed** — the reply appears all at once.
- **SQLite and the in-memory rate limiter** mean a single backend instance.
  Multiple replicas need Postgres and Redis.
- **Voice input quality** depends on the browser; Firefox falls back to the
  Gemini endpoint, which is slower and costs an API call.
