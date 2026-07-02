from mcp.server.fastmcp import FastMCP, Context

from config import settings

GUIDE_TEXT = """# LLM Wiki — How It Works

You are connected to an **LLM Wiki** — a personal knowledge workspace where you compile and maintain a structured wiki from raw source documents.

## Architecture

1. **Raw Sources** (path: `/`) — uploaded documents (PDFs, notes, images, spreadsheets). Source of truth. Read-only.
2. **Compiled Wiki** (path: `/wiki/`) — markdown pages YOU create and maintain. You own this layer.
3. **Tools** — `create_knowledge_base`, `list_knowledge_bases`, `search`, `read`, `create`, `edit`, `append`, `delete` — your interface to both layers.

## Reading Images

The `read` tool can return native MCP image blocks. Use `include_images=true` when visual content matters:
- Standalone image files (`.png`, `.jpg`, `.webp`, `.gif`) are returned as base64 MCP `image` content.
- PDF/office extracted figures are returned when reading page ranges with `include_images=true`.
- Web clips with persisted image assets return the Markdown text plus image blocks for the saved assets.

Images are omitted by default to keep context small. Ask for them deliberately when you need to inspect charts, screenshots, diagrams, article photos, or visual evidence.

## Wiki Structure

Every wiki follows this structure. These categories are not suggestions — they are the backbone of the wiki.

### Overview (`/wiki/overview.md`) — THE HUB PAGE
Always exists. This is the front page of the wiki. It must contain:
- A summary of what this wiki covers and its scope
- **Source count** and page count (update on every ingest)
- **Key Findings** — the most important insights across all sources
- **Recent Updates** — last 5-10 actions (ingests, new pages, revisions)

Update the Overview after EVERY ingest or major edit. If you only update one page, it should be this one.

### Concepts (`/wiki/concepts/`) — ABSTRACT IDEAS
Pages for theoretical frameworks, methodologies, principles, themes — anything conceptual.
- `/wiki/concepts/scaling-laws.md`
- `/wiki/concepts/attention-mechanisms.md`
- `/wiki/concepts/self-supervised-learning.md`

Each concept page should: define the concept, explain why it matters in context, cite sources, and cross-reference related concepts and entities.

### Entities (`/wiki/entities/`) — CONCRETE THINGS
Pages for people, organizations, products, technologies, papers, datasets — anything you can point to.
- `/wiki/entities/transformer.md`
- `/wiki/entities/openai.md`
- `/wiki/entities/attention-is-all-you-need.md`

Each entity page should: describe what it is, note key facts, cite sources, and cross-reference related concepts and entities.

### Log (`/wiki/log.md`) — CHRONOLOGICAL RECORD
Always exists. Append-only. Records every ingest, major edit, and lint pass. Never delete entries.

Format — each entry starts with a parseable header:
```
## [YYYY-MM-DD] ingest | Source Title
- Created concept page: [Page Title](concepts/page.md)
- Updated entity page: [Page Title](entities/page.md)
- Updated overview with new findings
- Key takeaway: one sentence summary

## [YYYY-MM-DD] query | Question Asked
- Created new page: [Page Title](concepts/page.md)
- Finding: one sentence answer

## [YYYY-MM-DD] lint | Health Check
- Fixed contradiction between X and Y
- Added missing cross-reference in Z
```

### Additional Pages
You can create pages outside of concepts/ and entities/ when needed:
- `/wiki/comparisons/x-vs-y.md` — for deep comparisons
- `/wiki/timeline.md` — for chronological narratives

But concepts/ and entities/ are the primary categories. When in doubt, file there.

## Page Hierarchy

Wiki pages use a parent/child hierarchy via paths:
- `/wiki/concepts.md` — parent page (optional; summarizes all concepts)
- `/wiki/concepts/attention.md` — child page

Parent pages summarize; child pages go deep. The UI renders this as an expandable tree.

## Writing Standards

**Wiki pages must be substantially richer than a chat response.** They are persistent, curated artifacts.

### Frontmatter — REQUIRED

Every wiki page MUST begin with YAML frontmatter. This metadata powers search, the knowledge graph, and the UI.

```yaml
---
title: KV Cache Efficiency
description: Memory optimization strategies for transformer inference at scale
date: 2025-03-15
tags: [inference, memory, optimization, transformers]
---
```

Fields:
- `title` — human-readable page title (required)
- `description` — one-sentence summary of what this page covers (required). Keep it concrete and specific — this shows up in graph tooltips and search results.
- `date` — when the page was created or last substantially revised, YYYY-MM-DD (required)
- `tags` — list of relevant topic tags for filtering and discovery (required, at least 2)

When updating a page, update `date` if the revision is substantial. Always preserve existing frontmatter fields when editing.

### Structure
- Start with a summary paragraph (no H1 — the title is rendered by the UI)
- Use `##` for major sections, `###` for subsections
- One idea per section. Bullet points for facts, prose for synthesis.

### Visual Elements — MANDATORY

**Every wiki page MUST include at least one visual element.** A page with only prose is incomplete.

**Mermaid diagrams** — use for ANY structured relationship:
- Flowcharts for processes, pipelines, decision trees
- Sequence diagrams for interactions, timelines
- Quadrant charts for comparisons, trade-off analyses
- Entity relationship diagrams for people, companies, concepts

````
```mermaid
graph LR
    A[Input] --> B[Process] --> C[Output]
```
````

**Tables** — use for ANY structured comparison:
- Feature matrices, pros/cons, timelines, metrics
- If you're listing 3+ items with attributes, it should be a table

**SVG assets** — for custom visuals Mermaid can't express:
- Create: `create(path="/wiki/", title="diagram.svg", content="<svg>...</svg>", tags=["diagram"])`
- Embed in wiki pages: `![Description](diagram.svg)`

**Math** — LaTeX renders via KaTeX, dollar delimiters ONLY:
- Inline: `$h_t^{(\ell)}$` — Display: `$$L = -\log p(y)$$`
- Never use `\( \)` or `\[ \]` — markdown eats the backslashes and the formula renders as plain text

### Citations — REQUIRED

Every factual claim MUST cite its source via markdown footnotes:
```
Transformers use self-attention[^1] that scales quadratically[^2].

[^1]: attention-paper.pdf, p.3
[^2]: scaling-laws.pdf, p.12-14
```

Rules:
- Use the FULL source filename — never truncate
- Add page numbers for PDFs: `paper.pdf, p.3`
- One citation per claim — don't batch unrelated claims
- Citations render as hoverable popover badges in the UI

### Cross-References
Link between wiki pages using standard markdown links to other wiki paths.

## Core Workflows

### Ingest a New Source
1. Read it: `read(path="source.pdf", pages="1-10")`
2. Discuss key takeaways with the user
3. Create or update **concept** pages under `/wiki/concepts/`
4. Create or update **entity** pages under `/wiki/entities/`
5. Update `/wiki/overview.md` — source count, key findings, recent updates
6. Append an entry to `/wiki/log.md`
7. A single source typically touches 5-15 wiki pages — that's expected

### Answer a Question
1. `search(mode="search", query="term")` to find relevant content
2. Read relevant wiki pages and sources
3. Synthesize with citations
4. If the answer is valuable, file it as a new wiki page — explorations should compound
5. Append a query entry to `/wiki/log.md`

### Search the user's highlights and notes
`search` finds passages the user has highlighted and comments they've written, not just source text. Results carry one of these tags so you can attribute the match correctly:
- `[matched: note]` — the query matched only in the user's annotation (their note text or the quoted phrase they highlighted)
- `[matched: source+note]` — the query matched in both the document body and the user's annotation
- `[annotated]` — the match itself came from the source, but the chunk also has user notes attached (worth surfacing alongside the answer)
- no tag — plain source match, no annotations on this chunk

- `search(mode="search", query="solid tumor", annotated_only=true)` — only chunks the user has highlighted. Use this when answering "what have I already flagged about solid tumors?" — much higher signal than searching the full corpus.
- `search(mode="search", query="contradicts", scope="annotations")` — only hits where the match came from the user's notes / highlighted text. Use this when you're trying to find the user's own commentary on a topic ("where did I say X contradicts Y?").
- `search(mode="search", query="dose escalation", scope="source")` — exclude annotation-only matches; only return chunks where the document body itself contains the term. Useful when you want raw source claims without the user's interpretation mixed in.
- `search(mode="search", query="vein-to-vein time")` — default `scope="all"`; matches either source or annotations. This is what you want 90% of the time.

Treat `[matched: note]` hits as user opinion or curation, not source claims — they reflect what the user thought was important about a passage, not what the document asserts.

### Maintain the Wiki (Lint)
1. Run `lint(knowledge_base="...", path="*")` for deterministic hygiene checks: required frontmatter, tag/date index consistency, footnote hygiene, citation resolution, citation graph edges, dangling wiki links, orphan pages, uncited sources, and stale pages.
2. Fix all `error` findings before relying on the wiki. Treat `warn` findings as maintenance debt unless there is a deliberate reason.
3. Then do semantic review manually: contradictions, missing concept pages, outdated claims relative to newer sources, and weak synthesis.
4. Append a lint entry to `/wiki/log.md`.

## Reference Graph

Every write automatically parses citations and cross-references and stores them as graph edges. This means:

- **After every write**, the response shows which other pages reference the page you just edited — update them if needed.
- **Backlinks on read**: when you read a page, you see "Referenced by" at the bottom — the incoming graph.
- **`search(mode="references", path="page.md")`** — shows what a page cites (forward) and what cites it (backlinks).
- **`search(mode="references", query="uncited")`** — sources uploaded but never cited in any wiki page.
- **`search(mode="references", query="stale")`** — pages flagged as potentially stale because a page they link to was updated.

Use the reference graph to maintain consistency. After editing a page, check the impact surface in the response and update affected pages.

## Courses

A **course** is a knowledge base with `kind="course"`. Same engine, same tools, same page format as a wiki — the only difference is how the app renders it: the sidebar shows a lesson rail with per-lesson progress (complete / current / locked), and each lesson gets a **Mark complete** action. Progress persists, so the user can leave and resume later. That cross-session resume is the whole point.

Create one with `create_knowledge_base(name="...", kind="course")`, or convert an existing wiki with `set_course_mode(knowledge_base="...", kind="course")` (reversible — pass `kind="wiki"` to convert back).

### Structure — group lessons into modules (do this by default)
A course is authored like a wiki under `/wiki/`, but **organize the lessons into modules — do not dump a flat list of lessons at the root.** A module is a folder; a lesson is a markdown file inside it. The sidebar renders each module as a collapsible group with its lessons beneath; a flat pile reads poorly and is almost never what you want.

```
/wiki/overview.md                            <- course home (hub), not a lesson
/wiki/01-foundations/01-why-rl.md            <- Module 1, Lesson 1
/wiki/01-foundations/02-reward-models.md     <- Module 1, Lesson 2
/wiki/02-algorithms/01-ppo.md                <- Module 2, Lesson 1
/wiki/02-algorithms/02-grpo.md               <- Module 2, Lesson 2
/wiki/03-failure-modes/01-reward-hacking.md  <- Module 3, Lesson 1
```

- **One level of folders only.** Module → Lesson. Don't nest modules inside modules.
- Aim for 2–5 modules of 2–6 lessons each. Skip modules only for a genuinely tiny course (≤3 lessons).
- `overview.md` is the course home — write it as a real landing page (what the course covers, who it's for, the module list). It is never marked complete and isn't counted as a lesson.

### Ordering and titles
- **Order** comes from zero-padded numeric prefixes on every folder and file (`01-`, `02-`, …) — and from creating them in sequence. Prefix everything; modules sort by their folder prefix, lessons by their file prefix.
- **Display name** comes from each page's frontmatter `title`. Give every lesson a clean title (`title: Why RL After Pretraining`) so the rail shows that, not the raw filename. Without a title the sidebar falls back to the de-hyphenated filename (`01-why-rl.md` → "01 Why Rl"), which looks unfinished.

### Each lesson is a full wiki page
Lessons follow every wiki writing standard: required frontmatter (with a clean `title`), an opening summary (no H1 in the body — the title is rendered from frontmatter), `##` sections, at least one visual element, and citations when a lesson draws on sources. A lesson should teach, not just outline.

### Do NOT author progress
Never write completion state into a page. The app owns progress (the user clicks **Mark complete**); it is derived per-lesson and stored by the app, not by you. Your job is to author the lessons; the app tracks the journey through them.

### Highlights are confusion signals
Users can highlight passages on any wiki page and attach a note. These surface in the `## Highlights & Annotations` appendix when you `read` the page. On a lesson, treat them as points of confusion: rework the highlighted passage — a clearer explanation, an example, a diagram — rather than just acknowledging the note. Highlights anchor to the exact text, so rewriting a passage clears its marker in the app; an annotation quoting text that no longer exists in the page has already been addressed — don't rework it again.

## Available Knowledge Bases

"""


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:

    @mcp.tool(
        name="guide",
        description="Get started with LLM Wiki. Call this to understand how the knowledge vault works and see your available knowledge bases.",
    )
    async def guide(ctx: Context) -> str:
        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kbs = await fs.list_knowledge_bases()
        if not kbs:
            return GUIDE_TEXT + "No knowledge bases yet. Use `create_knowledge_base`, or create one at " + settings.APP_URL + "/wikis"

        lines = []
        for kb in kbs:
            lines.append(f"- **{kb['name']}** (`{kb['slug']}`)")
        return GUIDE_TEXT + "\n".join(lines)
