/** Decode JSON-style Unicode escapes that arrive as literal display text. */
export function decodeUnicodeEscapes(value: string): string {
  return value.replace(/\\u([0-9a-fA-F]{4})/g, (_match, codeUnit: string) =>
    String.fromCharCode(Number.parseInt(codeUnit, 16)),
  )
}
