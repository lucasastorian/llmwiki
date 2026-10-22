// The MCP server is its own deployment — its URL is never derivable from the API URL.
const DEFAULT_MCP_URL = 'http://localhost:8080/mcp'

export const MCP_URL = process.env.NEXT_PUBLIC_MCP_URL || DEFAULT_MCP_URL

export function buildCodexMcpConfig(): string {
  return [
    '[mcp_servers.llmwiki]',
    `url = "${MCP_URL}"`,
    'auth = "oauth"',
  ].join('\n')
}

export function buildStarterPrompt(wikiName?: string): string {
  const target = wikiName?.trim() ? ` "${wikiName.trim()}"` : ' my LLM Wiki'
  return [
    'Call the LLM Wiki guide first.',
    `Then create or update${target} about [topic].`,
    'Use my existing sources when relevant; otherwise research with your available tools.',
    'Build a clear structure I can read, annotate, and refine.',
  ].join(' ')
}
