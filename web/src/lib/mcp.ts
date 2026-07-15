const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const DEFAULT_MCP_URL = 'http://localhost:8080/mcp'

export const MCP_URL =
  process.env.NEXT_PUBLIC_MCP_URL ||
  (process.env.NEXT_PUBLIC_API_URL ? `${API_URL}/mcp` : DEFAULT_MCP_URL)

export function buildOAuthMcpConfig(): string {
  return JSON.stringify(
    {
      mcpServers: {
        llmwiki: {
          url: MCP_URL,
        },
      },
    },
    null,
    2,
  )
}

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

export function buildApiKeyMcpConfig(apiKey: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        llmwiki: {
          url: MCP_URL,
          headers: {
            Authorization: `Bearer ${apiKey}`,
          },
        },
      },
    },
    null,
    2,
  )
}
