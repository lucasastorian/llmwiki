from config import settings

from mcp.server.fastmcp import Context, FastMCP

GUIDE_TEXT = r"""# LLM Wiki — How It Works

You are connected to an **LLM Wiki** — a personal knowledge workspace where you compile and maintain a structured wiki from raw source documents.

## Architecture

1. **Raw Sources** (path: `/`) — uploaded documents (PDFs, notes, images, spreadsheets). Source of truth. Read-only.
2. **Compiled Wiki** (path: `/wiki/`) — markdown pages YOU create and maintain. You own this layer.
3. **Tools** — `create_knowledge_base`, `list_knowledge_bases`, `search`, `read`, `create`, `patch`, `append`, `delete` — your interface to both layers.

Sources normally arrive via the app or browser extension, but `add_source_from_url` (hosted mode) lets you pull a publicly accessible PDF in directly by URL — arXiv abstract or PDF links work as-is. Extraction runs in the background; the document becomes readable/searchable shortly after.

## Reading Images

The `read` tool can return native MCP image blocks. Use `include_images=true` when visual content matters:
- Standalone image files (`.png`, `.jpg`, `.webp`, `.gif`) are returned as base64 MCP `image` content.
- PDF/office extracted figures are returned when reading page ranges with `include_images=true`.
- Web clips with persisted image assets return the Markdown text plus image blocks for the saved assets.

Images are omitted by default to keep context small. Ask for them deliberately when you need to inspect charts, screenshots, diagrams, article photos, or visual evidence.

## Wiki Structure

Every wiki follows this structure. These categories are not suggestions — they are the backbone of the wiki.

### Overview (`/wiki/overview.md`) — THE HUB PAGE
Always exists. This is the curated hub page of the wiki. It must contain:
- A summary of what this wiki covers and its scope
- **Key Findings** — the most important insights across all sources
- Clear links into the wiki's major concepts, entities, or sections

Update the Overview when the wiki's scope, key findings, or structure changes. The app's private Recent Changes view records activity automatically; never maintain a manual activity log.

### Plan (`/wiki/plan.md`) — OPTIONAL PROGRESS TRACKER
Create this page when the user asks you to plan or track a piece of work. The app renders it with status glyphs and a derived progress bar, and shows its progress on the wiki's landing page.
- `## ` headings are stages; task lines below a heading belong to that stage.
- Tasks: `- [ ]` todo · `- [~]` in progress · `- [x]` done · `- [!]` blocked (say why: `- [!] Backfill — blocked: needs approval`).
- When you finish a task or make a judgment call, add indented bullets under it — `What:` (files, commits) and `Why:` (the reasoning). Flag choices you're unsure about so the user can review them.
- Update statuses with `patch` as you work. Never delete tasks; supersede them.

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

Mermaid's parsers are strict — a syntax error means the diagram renders as raw code:
- Flowchart node labels containing `( ) [ ] { }` or other punctuation must be quoted: `A["Cost (5%)"]`, never `A[Cost (5%)]`
- quadrantChart, xychart, and axis/quadrant labels cannot contain parentheses at all — rephrase (`Debt-heavy: utilities, real estate`)
- No `$`/LaTeX inside any diagram text

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
5. Update `/wiki/overview.md` when the source changes the key findings or navigation
6. A single source typically touches 5-15 wiki pages — that's expected

### Answer a Question
1. `search(mode="search", query="term")` to find relevant content
2. Read relevant wiki pages and sources
3. Synthesize with citations
4. If the answer is valuable, file it as a new wiki page — explorations should compound

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

## Reference Graph

Every write automatically parses citations and cross-references and stores them as graph edges. This means:

- **After every write**, the response shows which other pages reference the page you just edited — update them if needed.
- **Backlinks on read**: when you read a page, you see "Referenced by" at the bottom — the incoming graph.
- **`search(mode="references", path="page.md")`** — shows what a page cites (forward) and what cites it (backlinks).
- **`search(mode="references", query="uncited")`** — sources uploaded but never cited in any wiki page.
- **`search(mode="references", query="stale")`** — pages flagged as potentially stale because a page they link to was updated.

Use the reference graph to maintain consistency. After editing a page, check the impact surface in the response and update affected pages.

## Courses

A **course** is a knowledge base with `kind="course"`. It is a linear teaching experience, not a collection of reference pages. The reader begins with limited domain knowledge, reads in order, and should finish able to notice, explain, judge, or do something they could not do before.

Create one with `create_knowledge_base(name="...", kind="course")`, or convert an existing wiki with `update_knowledge_base(knowledge_base="...", kind="course")` (reversible with `kind="wiki"`).

Course lessons still require frontmatter, source-grounded citations, and valid links. For lessons, however, this section overrides the wiki-wide rules about opening with a summary, including a visual on every page, and organizing prose like a random-access reference.

### Course structure and ordering

Author the course under `/wiki/` and group lessons into modules by default. A module is a folder; a lesson is a Markdown file inside it.

```text
/wiki/overview.md                            <- course home, not a lesson
/wiki/01-foundations/01-why-rl.md            <- Module 1, Lesson 1
/wiki/01-foundations/02-reward-models.md     <- Module 1, Lesson 2
/wiki/02-algorithms/01-ppo.md                <- Module 2, Lesson 1
/wiki/02-algorithms/02-grpo.md               <- Module 2, Lesson 2
```

- Use one folder level only: Module → Lesson.
- Aim for 2–5 modules of 2–6 lessons. Skip modules only for a genuinely tiny course of three lessons or fewer.
- Prefix every module and lesson with zero-padded numbers (`01-`, `02-`, …). Create them in sequence.
- Give every lesson a clean frontmatter `title`; the sidebar uses it as the display name.
- Write `overview.md` as a course landing page: who it is for, what the learner will become able to do, and how the modules build toward that capability. It is not counted as a lesson and must not read like a topic inventory.

### The standard: teach a model, not a list

Every lesson must create one meaningful change in the learner:

- a mechanism they can explain;
- a distinction they can use;
- a situation they can diagnose;
- a decision they can make and defend; or
- a misconception they can now reject.

If the lesson merely defines terms, recounts milestones, or offers high-level heuristics, it is not finished.

Before drafting, write a private lesson brief for your own planning. Do not publish it in the lesson or save it as a page. Use five lines:

1. **Learner:** What can this reader safely be assumed to know?
2. **Capability:** What should the reader be able to reason about afterward?
3. **Anchor:** What rich case, puzzle, event, or worked example will carry the lesson?
4. **Misconception:** What tempting but wrong model should the lesson displace?
5. **Transfer:** What different situation will show that the learner understood the idea rather than memorized the example?

Do not draft until all five have concrete answers.

### Begin with a situation that creates a need to know

Do not open with a block of definitions or a summary of what the lesson will cover. Open with a specific situation in which the learner feels the problem before receiving the abstraction.

A strong opening usually contains:

- a person or organization trying to do something;
- concrete constraints, evidence, numbers, or observations;
- two plausible interpretations or choices; and
- an unresolved question the lesson will help answer.

The opening is not a disposable hook. It is the **anchor case** for the lesson. Return to it as each part of the model is built, and resolve it only after the reader has the tools to reason through it.

For historical material, tell history as a causal explanation. Show the constraint people faced, the practice that emerged in response, what it solved, and the blind spot it created. A famous name or date earns space only when it helps explain that chain.

### Definitions are local support, not the architecture

Define a technical term before the reader must reason with it, but do so at the moment the term becomes useful.

Good sequence:

1. Let the reader encounter the concrete phenomenon.
2. Explain what is happening in ordinary language.
3. Name the concept as a convenient label for what the reader now partly understands.
4. Add precision, limits, and consequences.

Do not write "Before we begin, here are seven terms." Do not organize sections around vocabulary merely because the words are important.

A plain gloss is still preferred: "X is a familiar kind of thing that does the part that matters here." But a gloss is only the first rung. Follow it with mechanism, evidence, and use.

Bold only durable vocabulary the learner will use later. There is no required number of new terms. Most lessons need only a handful. A lesson with more than seven deserves scrutiny; a lesson with five is not automatically good.

### Use examples that do real teaching work

One-off examples are usually too weak. A strong lesson normally uses three layers:

1. **One sustained anchor case.** Give it enough texture to support several passes: context, chronology, evidence, uncertainty, incentives, and consequences.
2. **One contrasting case.** Change an important feature so the reader can see where the rule stops or why a neighboring situation requires a different judgment.
3. **One transfer case or question.** Use a fresh surface context and ask the learner to apply the underlying model.

Examples should expose reasoning, not merely decorate a claim. For any example, the draft should make clear:

- what the novice is likely to notice;
- what the expert notices instead;
- which evidence changes the interpretation;
- what conclusion is justified; and
- what remains uncertain.

When teaching a procedure or analytical skill, include at least one worked example that shows the intermediate judgments, not just the final answer. Then ask the reader to explain why each step was taken or what would change it.

### Build the mechanism in a narrative arc

A useful default lesson arc is:

1. **The problem:** a concrete case creates a genuine question.
2. **The naive model:** show the reasonable first interpretation and where it fails.
3. **The mechanism:** build the causal or analytical model one piece at a time.
4. **Return to the case:** reinterpret the original evidence using the new model.
5. **The contrast:** vary one or two features to reveal the model's boundary.
6. **The decision rule:** state what the learner should now look for or do.
7. **Consolidation:** use a summary card to compress the model without introducing anything new.
8. **Transfer:** ask the learner to reason through a fresh case before showing the answer.

This is a default, not a template that must be visible as eight headings. The prose should read like a coherent essay, not a worksheet assembled from required parts.

### Write for an intelligent adult

Assume curiosity and intelligence, not domain knowledge. Use precise prose, real stakes, and genuine ambiguity. Avoid a chirpy classroom voice, canned encouragement, toy examples, and repeated announcements that the material is "simple."

Richness comes from specificity and consequence, not ornamental prose. Prefer:

- a founder deciding whether to take a meeting with incomplete evidence;
- an investor discovering that a celebrated sourcing channel systematically hides a class of companies;
- a real system whose ranking improved while its opportunity coverage worsened;

over generic claims such as "networks are useful but can be biased."

For an adult professional course, a substantive lesson will often need roughly 1,500–2,500 words. This is not a quota. A short lesson can work when the idea is genuinely small; a long lesson fails if it merely repeats itself. Prefer twelve rich lessons to twenty-seven thin ones.

### Visuals must carry information

The wiki-wide rule that every page should contain a visual does **not** apply mechanically to course lessons. Include a visual only when it makes an important relationship easier to understand than prose can.

Good uses include:

- two processes unfolding at once;
- a quantity changing over time;
- a causal fork;
- a comparison across several repeated dimensions;
- the same case before and after one assumption changes.

A flowchart of section headings is not a teaching visual. A diagram may not introduce an undefined term. Delete any visual whose removal loses no information.

### Analogies need a mapping and a boundary

Use an analogy when it reveals the relational structure of a mechanism. At first contact:

1. identify the familiar situation;
2. map its important parts to the new mechanism;
3. use the mapping to derive a non-obvious consequence; and
4. state where the analogy stops working.

Do not require one analogy per lesson. A weak analogy is worse than direct explanation. Do not stack several images onto the same mechanism unless the later analogy repairs a specific limitation of the first.

### Summary cards

Use this Markdown convention for a visually distinct consolidation card:

```markdown
> [!SUMMARY]
> **The model:** Relationships can improve discovery and access without being evidence that a company is good.
>
> **Use it:** Judge company quality and the path to the founder as separate questions.
>
> **Watch for:** A warm introduction quietly raising the company's apparent quality.
```

Placement and content rules:

- Usually one summary card per lesson, after the teaching and before the transfer exercise.
- It may contain a compact model, decision rule, and failure mode.
- It introduces zero new terms, facts, examples, or caveats.
- It is not a second conclusion and does not repeat the section headings.
- Keep it short enough to scan: normally three short fields or three to five bullets.
- Do not place summary cards back-to-back with other callouts.

`[!SUMMARY]` follows the established GitHub alert pattern and should degrade gracefully to a normal blockquote in unsupported renderers.

### Practice for retrieval and transfer

Questions are part of the teaching, not an audit of whether vocabulary appeared.

Use three kinds of prompt:

1. **Retrieval:** Explain the model without looking back.
2. **Discrimination:** Compare two cases and identify the feature that changes the judgment.
3. **Transfer:** Apply the model in a new context with different surface details.

Do not ask for a term's definition when the real goal is judgment. Do not create distractors from undefined jargon. Do not reveal the answer verbatim in the summary card immediately above the question.

For a static lesson, place the worked answer after the learner has had a genuine chance to commit to a view. Explain why plausible alternatives fail.

### Quiz widget and authoring contract

Render lesson practice with a fenced `quiz` block. Usually place one purposeful block after the summary card; use an earlier checkpoint only when the teaching arc genuinely needs it. The widget presents one question at a time, hides rubrics, and reveals each explanation after the learner answers. Do not add a redundant `## Quiz` or `## Checkpoint` heading.

Use a purposeful mix: multiple choice for crisp discrimination and real misconceptions; free-form for explanation, application, comparison, and derivation. If a multiple-choice answer states the whole insight, convert it to free-form.

````markdown
```quiz
questions:
  - prompt: |
      A warm introduction gets an investor a meeting with a company. What changed most directly?
    options:
      - "The evidence that the company is high quality"
      - "The investor's access to the company"
      - "The company's underlying economics"
    answer: 1
    explanation: |
      The introduction changes the path to the company. It may be useful for discovery and access, but it is not itself evidence of company quality.
  - type: text
    prompt: |
      A conference organizer receives a trusted recommendation for a speaker. Explain what the recommendation does and does not establish.
    rubric: |
      Required: distinguish improved discovery or access from evidence of speaker quality.
      Partial: says the recommendation may be biased but does not separate access from evaluation.
      Reject: treats the recommendation itself as proof of quality.
      Accept any mechanistically correct route to this idea, including framings not used in the lesson.
    explanation: |
      The recommendation can surface a candidate and make contact easier. The organizer still needs separate evidence that the speaker fits the audience and can deliver.
```
````

- `questions` is always a non-empty list, with at most 20 questions.
- A choice question needs `prompt`, `options` containing 2–6 strings, and `answer` as the **0-based** correct-option index.
- A free-form question needs `type: text`, `prompt`, and a hidden `rubric`.
- Either type may include up to five `hints` and should include an `explanation` that teaches the miss.
- Prompts should use YAML block scalars (`prompt: |`). Rewrite hints containing `": "` or beginning with a quote; those forms are easy to parse incorrectly.
- A rubric grades ideas, not phrasing. State required ideas, partial understanding, and genuine misconceptions to reject. Explicitly accept alternate correct reasoning. Keep it short enough to check independently.
- Fact-check explanations against the source, not against the lesson's paraphrase.
- Writes validate every quiz block; `create`, `patch`, and `append` reject malformed blocks, and `lint` reports `invalid-quiz`.

### Course-level coherence

Organize lessons into numerically ordered module folders. But do not fragment the course merely to increase the page count.

Each module should answer one consequential question. Each lesson should advance that answer. Across the course:

- reuse one or two recurring cases so the learner can see the model deepen;
- revisit earlier ideas after some distance rather than treating every lesson as isolated;
- make later lessons require earlier distinctions;
- reserve the capstone for a realistic, messy decision using several parts of the course; and
- make the overview promise capabilities, not a list of topics.

### Citation and truth discipline

Teach from evidence. Cite factual claims and clearly distinguish:

- what a source states;
- what the course infers from it;
- what is a proposed practice; and
- what remains genuinely uncertain.

Do not make a source memorable by overstating it. When evidence is mixed, the ambiguity belongs in the lesson.

### Product-owned progress

Never author completion state in lesson content or metadata. The app owns lesson and quiz progress, including complete/current/locked state and cross-session resume. Your job is to author the learning experience; the app tracks the learner's journey.

### Treat highlights and comments as teaching defect reports

A note asking “what is X?” means the term was used before it became understandable. Move or improve the explanation at first use; do not append a glossary paragraph at the bottom.

A note saying the lesson is “just a bunch of terms,” “too abstract,” or “not teaching” is an architectural failure. Rebuild around a capability, anchor case, mechanism, contrast, and transfer task. Do not repair it by adding more definitions, bullets, or diagrams.

Rewriting highlighted text clears its anchor, which is expected. After addressing a live note, reply with `reply_to_comment`: one or two sentences explaining what changed or directly answering the question. Do not reply again unless the user has responded after the prior agent reply.

Use `list_comments` to find recent threads, optionally narrowed with `path="/wiki/**"`, before revising an active course.

### Pre-publication teaching audit

Before publishing, score each item `0`, `1`, or `2`:

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Meaningful outcome | Covers a topic | Names a capability | Learner must use the capability |
| Anchor case | None or decorative | Concrete but disposable | Rich and revisited throughout |
| Mechanism | Assertions | Partial explanation | Causal/analytical chain with consequences |
| Contrast | None | Another similar example | Boundary or counterexample changes judgment |
| History, if used | Names and dates | Context | Constraint → response → benefit → blind spot |
| Transfer | Recall only | Near copy | New surface context requiring the same model |
| Voice | Glossary/textbook boilerplate | Clear | Precise, adult, memorable, and worth rereading |

Do not publish a lesson with any zero. A lesson scoring below 11/14 needs revision. Passing this rubric does not override factual, citation, frontmatter, or link lint.

### Prompt for drafting a lesson

Use this as the internal authoring prompt:

```text
You are writing a lesson for an intelligent adult with limited prior knowledge of the domain. You are not writing a wiki page, glossary, outline, or exam-prep handout. Your job is to change the learner's mental model so they can reason in a new situation.

First plan privately using a design brief containing:
- the learner's assumed prior knowledge;
- one capability the lesson will create;
- one rich anchor case with concrete evidence, constraints, and a decision;
- the novice's tempting misconception;
- the mechanism that corrects it;
- one contrasting case that exposes a boundary;
- one transfer question using different surface details.

Do not include this brief in the lesson or save it as a course page.

Then write the lesson as a coherent long-form teaching narrative.

Do not begin with definitions. Begin inside the anchor case and create a need for the idea. Define technical vocabulary inline only when it becomes useful. Return to the anchor case after each major piece of the model. Show intermediate judgments and uncertainty. Use history only to explain why a practice emerged and what tradeoff it created. End the teaching with one [!SUMMARY] card containing no new information, then encode retrieval, discrimination, and transfer questions in the `quiz` widget. Put the reasoned answer in each question's `explanation`, where it appears only after the learner commits.

Before finalizing, audit the lesson for: a meaningful outcome, a sustained case, a real mechanism, a boundary case, transfer, adult voice, source fidelity, and any term used before it can be understood. Rewrite until no dimension is missing.
```

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
