export const privacy = `# Privacy Policy

**LLM Wiki** · Effective date: April 26, 2026

LLM Wiki is operated by Polybius, L.L.C., a Delaware limited liability company ("Polybius," "we," "us," "our"). LLM Wiki is a free, open-source knowledge base service available at llmwiki.app. This policy explains what data we collect, how we use it, and your rights regarding that data.

## What we collect

### Account information
When you sign up, we collect your email address and display name via Supabase Auth. If you sign in with Google OAuth, we receive your name, email, and profile photo from Google. We do not store your Google password.

### Content you upload
Documents, notes, PDFs, and other files you add to your knowledge bases are stored on our infrastructure. This includes the original files, extracted text, and generated wiki pages. This is the core function of the service — we store your content so you and your connected AI tools can access it.

### Processed content
When you upload PDFs or office documents, we process them server-side to extract text. The extracted text is stored alongside the original file.

### Browser extension data
If you use the LLM Wiki Chrome extension, it captures the text content of web pages you explicitly choose to clip. The extension only activates when you click the save button — it does not passively monitor your browsing. Page content is sent directly to our API and stored in your knowledge base.

### Usage data
We collect basic usage analytics: page views, feature usage, and error logs. We do not use third-party tracking scripts or advertising pixels.

## How your content is stored

| Component | Provider | Location | Purpose |
|-----------|----------|----------|---------|
| Database | Supabase (Postgres) | AWS US regions | Account data, documents, wiki pages, metadata |
| File storage | Amazon S3 | US East | Raw uploaded files (PDFs, images) |
| API hosting | Railway | US regions | API and MCP servers |
| Frontend hosting | Netlify | Global CDN | Web application |

All data is encrypted at rest (AES-256) and in transit (TLS 1.2+). Database access is enforced through row-level security (RLS) — each user can only access their own data.

## Third-party services that process your content

| Service | What it sees | Why |
|---------|-------------|-----|
| Supabase | All stored data | Database and authentication provider |
| Amazon S3 | Raw uploaded files | File storage |
| Railway | All data in transit through API | API and MCP server hosting |
| Netlify | Frontend assets, request logs | Web application hosting |
| Anthropic (Claude) | Document content during AI conversations | Wiki generation and knowledge base tools via MCP |

We do not send your content to any service for the purpose of AI model training.

## How AI tools access your content

LLM Wiki connects to AI assistants (such as Claude by Anthropic) via the Model Context Protocol (MCP). When you connect your Claude account:

- Claude can search, read, and write to your knowledge bases using MCP tools
- Your content is sent to Claude through Anthropic's infrastructure as part of your conversations
- This access is governed by your relationship with Anthropic and their privacy policy
- You can disconnect Claude at any time by removing the MCP connector in your Claude settings

We do not control how Anthropic processes content sent through Claude conversations. Refer to Anthropic's privacy policy for details on their data handling.

## What we do NOT do

- We do not sell your data
- We do not serve advertisements
- We do not use your content to train AI models
- We do not share your content with other users (unless you explicitly make a knowledge base public)
- We do not access your content for any purpose other than providing the service, unless required by law

## Public knowledge bases

If you choose to make a knowledge base public, its wiki pages will be visible to anyone on the internet and may be indexed by search engines. Raw source documents in a public knowledge base are not made public — only wiki pages. You can make a knowledge base private again at any time, which removes it from public access.

## Data retention and deletion

Your content is stored as long as you maintain an account. You can delete individual documents, knowledge bases, or your entire account at any time.

When you delete content:
- Documents and wiki pages are removed from the database
- Uploaded files are removed from S3
- Search index entries are removed
- Deletion is permanent — we do not retain backups of deleted content beyond our standard database backup window (7 days)

When you delete your account:
- All knowledge bases, documents, wiki pages, and uploaded files are permanently deleted
- Your authentication credentials are removed from Supabase
- This process is irreversible

To request account deletion, email lucas@llmwiki.app.

## Your rights

You can at any time:
- Export your data (download your documents and wiki pages)
- Delete specific content or your entire account
- Disconnect AI tool access by removing MCP connectors
- Make knowledge bases private or public
- Request information about what data we hold (email lucas@llmwiki.app)

If you are in the EU, you have additional rights under GDPR including the right to data portability, rectification, and erasure. Contact lucas@llmwiki.app to exercise these rights.

## Self-hosting

LLM Wiki is open source (Apache 2.0). If you require full data sovereignty, you can self-host the entire stack on your own infrastructure. When self-hosted, no data passes through our systems. See the GitHub repository for deployment instructions.

## Children

LLM Wiki is not intended for use by anyone under the age of 13. We do not knowingly collect personal information from children under 13.

## Changes to this policy

We may update this policy from time to time. We will notify you of material changes by email or by posting a notice in the application. Continued use of the service after changes constitutes acceptance of the updated policy.

## Contact

For privacy questions or data requests: lucas@llmwiki.app
`
