/**
 * Composer attachments. A `+` pick can be an image (goes to the image slot) or any file
 * (sent with the next utterance as context). Neither replaces the message text.
 */
export interface StagedFile {
  upload_id: string
  name: string
  mime: string
  size: number
  readable: boolean
  kind: 'image' | 'file'
}

export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Files we can hand to the planner as text; the rest are still listed and downloadable. */
export function isReadableAttachment(a: StagedFile): boolean {
  return a.kind === 'file' && a.readable
}

export function attachmentSummary(files: StagedFile[]): string {
  if (files.length === 0) return ''
  const names = files.map((f) => f.name).join('、')
  return `附上 ${files.length} 个文件：${names}`
}
