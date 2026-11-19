/** How a file version is shown. Mirrors DeerFlow: components, iframe, or download. */

export type FileMedia = 'html' | 'markdown' | 'table' | 'iframe' | 'download'
export type FileViewMode = 'preview' | 'code'

const TABLE = new Set(['csv', 'tsv'])
const MARKDOWN = new Set(['md', 'markdown'])
const HTML = new Set(['html', 'htm'])
const IFRAME = new Set([
  'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg',
  'mp3', 'wav', 'mp4', 'webm', 'ogg', 'mov',
])

export function fileExtension(name: string): string {
  const base = name.trim().split(/[/\\]/).pop() ?? ''
  const dot = base.lastIndexOf('.')
  return dot >= 0 ? base.slice(dot + 1).toLowerCase() : ''
}

export function fileMedia(name: string, declared?: string | null): FileMedia {
  if (declared === 'html' || declared === 'markdown' || declared === 'table') return declared
  if (declared === 'iframe' || declared === 'download') return declared
  const ext = fileExtension(name)
  if (HTML.has(ext)) return 'html'
  if (MARKDOWN.has(ext)) return 'markdown'
  if (TABLE.has(ext)) return 'table'
  if (IFRAME.has(ext)) return 'iframe'
  return 'download'
}

/** HTML opens in preview after a successful write. A failed write stays on source. */
export function initialFileMode(media: FileMedia, writeOk: boolean): FileViewMode {
  if (media === 'html') return writeOk ? 'preview' : 'code'
  return 'preview'
}

export function tableDelimiter(name: string): ',' | '\t' {
  return fileExtension(name) === 'tsv' ? '\t' : ','
}

export function parseTable(text: string, delimiter: ',' | '\t'): string[][] {
  return text.replace(/^\uFEFF/, '').split(/\r?\n/).filter((line) => line.length > 0).map((line) => {
    const cells: string[] = []
    let cur = ''
    let quoted = false
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i]
      if (ch === '"') {
        if (quoted && line[i + 1] === '"') { cur += '"'; i += 1 }
        else quoted = !quoted
      } else if (ch === delimiter && !quoted) {
        cells.push(cur)
        cur = ''
      } else cur += ch
    }
    cells.push(cur)
    return cells
  })
}

/** Free text on the general home that should open a file task instead of a PDP. */
export function looksLikeFile(text: string): boolean {
  return /html|markdown|\.md\b|表格|csv|tsv|网页|活动页/i.test(text)
}
