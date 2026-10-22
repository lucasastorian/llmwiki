# Real-page parser corpus

`pages.json.gz` holds 16 frozen HTML snapshots of public pages as a deterministic gzip (mtime 0) of a JSON list of
`{id, url, sha256, html}`. `sha256` is the SHA-256 of the UTF-8 HTML; `tests/support/real_pages.py` refuses to load a
page whose HTML no longer matches it. Snapshots are never refetched or regenerated.

**Source.** Two anonymous server-side fetches (`<host>/capture-1`, `<host>/capture-2`) of eight public sites taken on
2026-09-21: linear.app, notion.com, stripe.com, vercel.com, figma.com, nextjs.org/docs, respan.ai and an
en.wikipedia.org list article.

**Goldens.** `goldens.json.gz` maps each id to `{markdown, plaintext, markdown_sha256}` from the production web-clip
call `Parser(html, url=url, content_only=True).parse()`. Tests compare against it exactly and never write it. After an
intended parser change, regenerate and review the printed per-page diff before committing:

```bash
PYTHONPATH=api python -m tests.support.regenerate_real_page_goldens
```

`web/src/lib/highlights/realPages.parity.test.ts` renders every golden `markdown` through TipTap and requires the
canonical plaintext to equal the golden `plaintext`.

**Adding a page.** Only public pages, fetched without cookies, and scrubbed of anything visitor-specific (client IP,
session or visitor ids) — pages often embed these. Append `{"id", "url", "sha256": sha256_text(html), "html"}` to `load_pages()`
and write it back with `save_pages()` (both in `tests/support/real_pages.py`), record the source and capture date
here, then regenerate the goldens.
