[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/lucasastorian-llmwiki-badge.png)](https://mseep.ai/app/lucasastorian-llmwiki)

# LLM Wiki

[![License](https://img.shields.io/badge/license-Apache%202.0-green)](https://opensource.org/licenses/Apache-2.0)

Open-source implementation of [Karpathy's LLM Wiki](https://x.com/karpathy/status/2039805659525644595) ([spec](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)).

I built this because research folders accumulate useful material faster than I can keep summaries, links, and citations current by hand. LLM Wiki offloads that editing work to Claude so I can focus on source selection and analysis instead.

Point it at a folder, start the local app, and connect Claude over MCP. From there, Claude reads your sources, writes wiki pages, and keeps links and citations in sync.

![LLM Wiki — a compiled wiki page with citations and table of contents](wiki-page.png)

## What actually happens

1. **You have a folder** — PDFs, notes, articles, spreadsheets. Your existing research.
2. **LLM Wiki indexes it** — extracts text, chunks for search, builds a local SQLite index. Source files stay where they are.
3. **Claude connects via MCP** — reads sources, writes wiki pages under `wiki/`, maintains cross-references and footnote citations.
4. **The wiki improves** as Claude reads more of the workspace and writes more pages. Summaries, entity pages, and cross-references accumulate instead of being re-derived from scratch each conversation.

## Quick Start

**Requirements:** Python 3.11+, Node.js 20+

```bash
git clone https://github.com/lucasastorian/llmwiki.git
cd llmwiki

# Install Python deps
cd api && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ..

# Install web deps
cd web && npm install && cd ..

# Initialize a workspace (point at any folder with your files)
./llmwiki init ~/research

# Start API + web UI
./llmwiki serve ~/research
```

Open [localhost:3000](http://localhost:3000). Your files are indexed, wiki is scaffolded, ready to go.

> If `./llmwiki init` errors out on a fresh checkout, first make sure you're up to date with `master` and try again. If it still fails, open an issue with the full output; local setup gets fewer reports, so there may be undocumented edge cases.

### Connect Claude

```bash
./llmwiki mcp-config ~/research
```

This prints a JSON snippet for `claude_desktop_config.json` (Claude Desktop) or `.claude/settings.json` (Claude Code). One workspace runs as one MCP server entry, so if you have multiple research folders, add one entry per folder.

Then tell Claude: *"Read the guide, then ingest my sources and start building the wiki."*

### Using with non-Claude clients

LLM Wiki is an MCP server, so any MCP-capable client works — not just Claude Desktop / Code. The server-side tools (`guide`, `search`, `read`, `create`, `edit`, `append`, `delete`) are the same across clients; agent quality is up to whichever client/model is at the other end.

Useful options for offline / corporate-firewall / local-model setups:

- **opencode** — open-source coding agent with MCP support. Runs against Ollama, vLLM, or any OpenAI-compatible local endpoint.
- **continue.dev** — VS Code / JetBrains extension with MCP (Agent mode) and Ollama support.
- **Cursor** and **Cline** — IDE-based clients with MCP support.

Point your client's MCP config at the same `llmwiki mcp <workspace>` command you'd use for Claude (see `llmwiki mcp-config` output). Multiple clients can point at the same workspace, but avoid simultaneous writes to the same page — there's no cross-process write lock, so concurrent edits can lose updates.

Local models need reliable tool/function calling — most Llama / Qwen-class models can do this, but quality varies a lot by model, context length, and client configuration. The `guide` tool is your friend: have the client call it first so the model gets the workspace structure and conventions before it starts writing.

### One-command start

```bash
./llmwiki open ~/research
```

Does everything: init if needed, start servers, open browser, print MCP config hint.

## CLI

| Command | What it does |
|---------|-------------|
| `llmwiki open <folder>` | Init + serve + open browser |
| `llmwiki init <folder>` | Create `.llmwiki/` + `wiki/`, index existing files |
| `llmwiki serve <folder>` | Start API on :8000 + web on :3000 |
| `llmwiki mcp <folder>` | Run stdio MCP server (for Claude config) |
| `llmwiki mcp-config <folder>` | Print `claude_desktop_config.json` snippet |
| `llmwiki reindex <folder>` | Rebuild the index from disk |

## What happens on disk

LLM Wiki adds two things to your folder. Source files are not moved or modified.

```
~/research/                  # Your existing files (untouched)
  papers/paper.pdf
  notes.md
  data.xlsx
  wiki/                      # Generated pages (created by LLM Wiki)
    overview.md
    log.md
    concepts/
      attention.md
  .llmwiki/                  # Index + cache (hidden, rebuildable)
    index.db
    cache/
```

- `wiki/` — ordinary markdown files. Edit them in any editor. Claude writes and updates them via MCP.
- `.llmwiki/` — SQLite search index and processed artifacts. Delete it anytime; `llmwiki reindex` rebuilds from the source files.

By default, indexing, storage, and file writes happen on your machine. No cloud services required.

## How Claude interacts with the workspace

Once connected, Claude has these tools:

| Tool | Description |
|------|-------------|
| `guide` | Explains how the wiki works, lists what's in the workspace |
| `search` | Browse files (`list`) or full-text search (`search`) |
| `read` | Read documents — PDFs with page ranges, glob batch reads |
| `create` | Create a new wiki page or asset (markdown, SVG, CSV, JSON, XML, HTML) |
| `edit` | Edit an existing page via `str_replace` |
| `append` | Append content to the end of an existing page |
| `delete` | Delete documents by path or glob pattern |

All writes go to disk first, then update the search index. If Claude creates `/wiki/concepts/attention.md`, that file appears on disk immediately.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Next.js    │────▶│   FastAPI    │────▶│   SQLite     │
│   Frontend   │     │   Backend    │     │   (local)    │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                     ┌──────┴───────┐
                     │  MCP Server  │◀──── Claude Desktop / Code
                     │   (stdio)    │
                     └──────────────┘
                            │
                     ┌──────┴───────┐
                     │  Filesystem  │  ← source of truth
                     └──────────────┘
```

The filesystem is the source of truth. SQLite is a derived index — it accelerates search and stores extracted page data, but it can always be rebuilt from the files. A background file watcher picks up changes you make outside the app.

## Document processing

All processing runs locally. No API keys required for basic usage.

| Format | Parser | Notes |
|--------|--------|-------|
| PDF | pdf-oxide | Rust-based text extraction. Works well for text-heavy papers. Scanned PDFs still benefit from real OCR. |
| Markdown/Text | native | Indexed and chunked directly |
| HTML | webmd | Strips nav/ads, extracts clean markdown |
| Excel/CSV | openpyxl | Sheet-by-sheet extraction |
| Images | native | Stored as-is, viewable inline |
| Word/PowerPoint | LibreOffice | Optional. Install LibreOffice for office conversion; without it, these formats are stored but not extracted. |

Set `MISTRAL_API_KEY` for higher-quality PDF OCR with better table and layout detection. pdf-oxide is the free default and handles most text-heavy documents well enough.

## Limitations and tradeoffs

- **One workspace = one MCP server.** If you work across multiple research projects, each gets its own folder and its own MCP entry. This is intentional — it keeps context and file access scoped.
- **PDF table extraction is rough.** pdf-oxide extracts prose reliably but tables come through as messy text. For financial filings or data-heavy PDFs, Mistral OCR is significantly better.
- **LibreOffice adds setup friction.** Office file conversion requires a local LibreOffice install. If you mostly work with PDFs and markdown, you can skip it entirely.
- **No vector search in local mode.** Full-text search uses SQLite FTS5 (porter stemming). It works well for keyword queries but does not do semantic/embedding search. The hosted version at llmwiki.app uses PGroonga for ranked search.

## Self-hosting the multi-tenant version

If you want to run the hosted version (like [llmwiki.app](https://llmwiki.app)) with Postgres, Supabase auth, and S3:

<details>
<summary>Hosted setup instructions</summary>

### Prerequisites

- Python 3.11+
- Node.js 20+
- A [Supabase](https://supabase.com) project
- An S3-compatible bucket

### Database

```bash
psql $DATABASE_URL -f supabase/migrations/001_initial.sql
```

### API

```bash
cd api
pip install -r requirements.txt
MODE=hosted DATABASE_URL=postgresql://... uvicorn main:app --port 8000
```

### MCP Server

```bash
cd mcp
pip install -r requirements.txt
MODE=hosted DATABASE_URL=postgresql://... uvicorn server:app --port 8080
```

### Web

```bash
cd web
npm install
NEXT_PUBLIC_MODE=hosted \
NEXT_PUBLIC_SUPABASE_URL=https://your-ref.supabase.co \
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key \
NEXT_PUBLIC_API_URL=http://localhost:8000 \
npm run dev
```

### Environment Variables

**API**
```
MODE=hosted
DATABASE_URL=postgresql://...
SUPABASE_URL=https://your-ref.supabase.co
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_BUCKET=your-bucket
MISTRAL_API_KEY=              # optional, for better PDF OCR
CONVERTER_URL=                # optional, for office conversion
```

**Web**
```
NEXT_PUBLIC_MODE=hosted
NEXT_PUBLIC_SUPABASE_URL=https://your-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_API_URL=http://localhost:8000
```

</details>

## Why this beats a static notes folder

Personal wikis usually fail on maintenance, not intent. Someone has to update links, fix stale summaries, merge overlapping pages, and keep citations aligned with the source material. That work scales with the number of sources, and people stop doing it.

LLM Wiki offloads that editing work. You choose the source material and direct the analysis. Claude handles the repetitive bookkeeping — updating cross-references, keeping summaries current, flagging contradictions, touching the 15 pages that a single new source affects.

## License

Apache 2.0
