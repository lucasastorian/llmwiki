# LLM Wiki

[![License](https://img.shields.io/badge/license-Apache%202.0-green)](https://opensource.org/licenses/Apache-2.0)

Open-source implementation of [Karpathy's LLM Wiki](https://x.com/karpathy/status/2039805659525644595) ([spec](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)).

Point it at a folder. Connect Claude. Get a compiled, cross-referenced wiki that maintains itself.

![LLM Wiki — a compiled wiki page with citations and table of contents](wiki-page.png)

## How It Works

1. **You have a folder** — PDFs, notes, articles, spreadsheets. Your research.
2. **LLM Wiki indexes it** — extracts text, chunks for search, builds a local SQLite index.
3. **Claude connects via MCP** — reads your sources, writes wiki pages, maintains cross-references and citations.
4. **The wiki compounds** — every source and every question makes it richer. Knowledge is built up, not re-derived.

Your files stay on disk. The wiki is real markdown files in a `wiki/` folder. Everything is local.

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

# Start the app
./llmwiki serve ~/research
```

Open [localhost:3000](http://localhost:3000). Your files are indexed, wiki is scaffolded, ready to go.

### Connect Claude

```bash
./llmwiki mcp-config ~/research
```

This prints a JSON snippet. Add it to your `claude_desktop_config.json` (Claude Desktop) or `.claude/settings.json` (Claude Code).

Then tell Claude: *"Read the guide, then ingest my sources and start building the wiki."*

### One-Command Start

```bash
./llmwiki open ~/research
```

Does everything: init if needed, start servers, open browser, print MCP config hint.

## CLI Reference

| Command | What it does |
|---------|-------------|
| `llmwiki open <folder>` | Init + serve + open browser |
| `llmwiki init <folder>` | Create `.llmwiki/` + `wiki/`, index existing files |
| `llmwiki serve <folder>` | Start API on :8000 + web on :3000 |
| `llmwiki mcp <folder>` | Run stdio MCP server (for Claude config) |
| `llmwiki mcp-config <folder>` | Print `claude_desktop_config.json` snippet |
| `llmwiki reindex <folder>` | Rebuild the index from disk |

## What Gets Created

LLM Wiki adds two things to your folder. Nothing else is touched.

```
~/research/                  # Your existing files (untouched)
  papers/paper.pdf
  notes.md
  data.xlsx
  wiki/                      # Wiki pages (created by LLM Wiki)
    overview.md
    log.md
    concepts/
      attention.md
  .llmwiki/                  # Local index (hidden, rebuildable)
    index.db
    cache/
```

- `wiki/` — real markdown files. Edit them anywhere. Claude writes them via MCP.
- `.llmwiki/` — SQLite index + processed artifacts. Delete it anytime; `llmwiki reindex` rebuilds it.

## MCP Tools

Once connected, Claude has full access to your workspace:

| Tool | Description |
|------|-------------|
| `guide` | Explains how the wiki works, lists what's in the workspace |
| `search` | Browse files (`list`) or full-text search (`search`) |
| `read` | Read documents — PDFs with page ranges, glob batch reads |
| `write` | Create wiki pages, edit with `str_replace`, append. SVG/CSV assets |
| `delete` | Delete documents by path or glob pattern |

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

**Local mode** (default):
- SQLite for search index (FTS5)
- Files on disk are the source of truth
- pdf-oxide for PDF extraction (free, local, no API keys)
- File watcher auto-indexes changes
- One workspace = one MCP server

**Hosted mode** (opt-in, for [llmwiki.app](https://llmwiki.app)):
- Postgres + Supabase Auth + S3
- Multi-tenant with RLS
- Remote MCP via OAuth

## Document Processing

All processing runs locally. No API keys required for basic usage.

| Format | Parser | Notes |
|--------|--------|-------|
| PDF | pdf-oxide | Fast Rust-based extraction. Free. |
| Markdown/Text | native | Indexed and chunked directly |
| HTML | webmd | Extracts clean markdown from web pages |
| Excel/CSV | openpyxl | Sheet-by-sheet extraction |
| Images | native | Stored as-is, viewable inline |
| Word/PowerPoint | LibreOffice | Optional — install LibreOffice for office conversion |

**Pro tip:** Set `MISTRAL_API_KEY` for higher-quality PDF OCR (better tables, better layout detection). pdf-oxide is the free default.

## Self-Hosting the Hosted Version

If you want to run the multi-tenant hosted version (like llmwiki.app):

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

## Why This Works

The tedious part of maintaining a knowledge base is not the reading or the thinking — it's the bookkeeping. Updating cross-references, keeping summaries current, noting when new data contradicts old claims, maintaining consistency across dozens of pages.

Humans abandon personal wikis because the maintenance burden grows faster than the value. LLMs don't get bored, don't forget to update a cross-reference, and can touch 15 files in one pass. The wiki stays maintained because the cost of maintenance drops to near zero.

The human's job is to curate sources, direct the analysis, ask good questions, and think about what it all means. The LLM's job is everything else.

## License

Apache 2.0
