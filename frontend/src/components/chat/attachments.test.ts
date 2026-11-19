import { describe, expect, it } from 'vitest'
import { attachmentSummary, humanSize, isReadableAttachment, type StagedFile } from './attachments'

const file = (over: Partial<StagedFile> = {}): StagedFile => ({
  upload_id: 'files/a/notes.md', name: 'notes.md', mime: 'text/markdown',
  size: 2048, readable: true, kind: 'file', ...over,
})

describe('composer attachments', () => {
  it('formats sizes for the chip row', () => {
    expect(humanSize(512)).toBe('512 B')
    expect(humanSize(2048)).toBe('2 KB')
    expect(humanSize(3 * 1024 * 1024)).toBe('3.0 MB')
  })

  it('treats only decoded text as readable context', () => {
    expect(isReadableAttachment(file())).toBe(true)
    expect(isReadableAttachment(file({ readable: false }))).toBe(false)
    expect(isReadableAttachment(file({ kind: 'image', readable: false }))).toBe(false)
  })

  it('summarises what will be sent', () => {
    expect(attachmentSummary([])).toBe('')
    expect(attachmentSummary([file(), file({ name: 'table.csv' })])).toBe('附上 2 个文件：notes.md、table.csv')
  })
})
