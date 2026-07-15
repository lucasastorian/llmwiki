import { describe, expect, it } from 'vitest'
import {
  buildCodexMcpConfig,
  buildStarterPrompt,
  MCP_URL,
} from './mcp'

describe('MCP connection helpers', () => {
  it('builds a Codex Streamable HTTP OAuth configuration', () => {
    expect(buildCodexMcpConfig()).toBe([
      '[mcp_servers.llmwiki]',
      `url = "${MCP_URL}"`,
      'auth = "oauth"',
    ].join('\n'))
  })

  it('builds a source-optional starter prompt for a named wiki', () => {
    const prompt = buildStarterPrompt('Systems Course')

    expect(prompt).toContain('"Systems Course"')
    expect(prompt).toContain('about [topic]')
    expect(prompt).toContain('otherwise research with your available tools')
  })

  it('uses a generic target when no wiki name is available', () => {
    expect(buildStarterPrompt()).toContain('my LLM Wiki')
  })
})
