# LLM Wiki

Open-source implementation of [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern.

Your LLM compiles and maintains a structured wiki from raw sources. You rarely write the wiki yourself — that's the LLM's job.

**[llmwiki.app](https://llmwiki.app)**

## How it works

Most people's experience with LLMs and documents looks like RAG: upload files, retrieve chunks at query time, generate an answer. The LLM rediscovers knowledge from scratch on every question. Nothing accumulates.

LLM Wiki is different. When you add a source, the LLM reads it, extracts key information, and integrates it into a persistent wiki — updating entity pages, revising summaries, flagging contradictions, strengthening the evolving synthesis. The wiki is a **compounding artifact** that gets richer with every source you add and every question you ask.

### Three layers

| Layer | Description |
|-------|-------------|
| **Raw Sources** | PDFs, articles, notes, transcripts. Your immutable source of truth. The LLM reads them but never modifies them. |
| **The Wiki** | LLM-generated markdown pages — summaries, entity pages, cross-references. The LLM owns this layer. You read it; the LLM writes it. |
| **The Tools** | Search, read, and write. Claude connects via MCP and does the rest. |

### Operations

**Ingest** — Drop a source in. The LLM reads it, writes a summary, updates entity and concept pages across the wiki, and flags anything that contradicts existing knowledge. A single source might touch 10-15 wiki pages.

**Query** — Ask complex questions against the compiled wiki. Knowledge is already synthesized — not re-derived from raw chunks each time. Good answers get filed back as new pages, so your explorations compound.

**Lint** — Run health checks. Find inconsistent data, stale claims, orphan pages, missing cross-references. The LLM suggests new questions to ask and new sources to look for.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Next.js    │────▶│   FastAPI    │────▶│  Supabase   │
│   Frontend   │     │   Backend    │     │  (Postgres)  │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │  MCP Server  │◀──── Claude
                    └─────────────┘
```

| Component | Stack | What it does |
|-----------|-------|-------------|
| **Web** (`web/`) | Next.js 16, React 19, Tailwind, Radix UI | Dashboard, PDF/HTML viewer, wiki editor, onboarding |
| **API** (`api/`) | FastAPI, asyncpg, aioboto3 | Auth, uploads (TUS), document processing, OCR (Mistral) |
| **MCP** (`mcp/`) | FastMCP, Supabase OAuth | `guide`, `search`, `read`, `write`, `delete` tools for Claude |
| **Database** | Supabase (Postgres + RLS + PGroonga) | Documents, chunks, knowledge bases, users |
| **Storage** | S3 | Raw uploads, tagged HTML, extracted images |

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 20+
- A [Supabase](https://supabase.com) project
- An S3-compatible bucket (optional — needed for file uploads)

### 1. Database

Run the migrations against your Supabase project:

```bash
# Apply in order
psql $DATABASE_URL -f supabase/migrations/001_initial.sql
psql $DATABASE_URL -f supabase/migrations/002_pgroonga.sql
# ... etc
```

Or use the local Docker setup:

```bash
docker compose up -d
```

### 2. API

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env  # edit with your Supabase credentials
uvicorn main:app --reload --port 8000
```

### 3. MCP Server

```bash
cd mcp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# uses the same .env as api
uvicorn server:app --reload --port 8080
```

### 4. Web

```bash
cd web
npm install
cp .env.example .env.local  # edit with your Supabase + API URLs
npm run dev
```

### 5. Connect Claude

Copy the MCP URL and add it as a connector in Claude:

1. Open **Settings** > **Connectors**
2. Click **Add custom connector**
3. Paste `http://localhost:8080/mcp`
4. Sign in with your Supabase account when prompted

## Environment variables

### API (`api/.env`)

```
DATABASE_URL=postgresql://...
SUPABASE_URL=https://your-ref.supabase.co
SUPABASE_JWT_SECRET=          # optional, for legacy HS256 projects
MISTRAL_API_KEY=              # for PDF OCR
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
S3_BUCKET=your-bucket
APP_URL=http://localhost:3000
```

### Web (`web/.env.local`)

```
NEXT_PUBLIC_SUPABASE_URL=https://your-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_MCP_URL=http://localhost:8080/mcp
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `guide` | Returns how the wiki works and lists your knowledge bases |
| `search` | Browse files (`list` mode) or keyword search with PGroonga ranking (`search` mode) |
| `read` | Read documents — PDFs with page ranges, images inline, markdown sections |
| `write` | Create wiki pages, edit with `str_replace`, append. SVG and CSV asset support |
| `delete` | Archive documents by path or glob pattern |

## Background

LLM Wiki started as a stripped-down version of [Supasearch](https://github.com/lucasastorian/supasearch-platform), a document processing platform with GPU-accelerated layout detection, vector search, and a full research assistant. Supasearch was essentially an operating system for agents — massive filesystem with search, read/write, and ephemeral databases.

LLM Wiki takes the core document pipeline and MCP tooling from Supasearch and wraps it in a focused product around Karpathy's wiki pattern: upload sources, let the LLM compile a wiki, query against synthesized knowledge instead of raw chunks.

## License

Apache 2.0
