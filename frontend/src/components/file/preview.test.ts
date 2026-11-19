import { describe, expect, it } from 'vitest'
import { fileMedia, initialFileMode, looksLikeFile, parseTable } from './preview'

describe('file preview routing', () => {
  it('sends html, markdown and tables to components', () => {
    expect(fileMedia('page.html')).toBe('html')
    expect(fileMedia('notes.md')).toBe('markdown')
    expect(fileMedia('table.csv')).toBe('table')
    expect(fileMedia('table.tsv')).toBe('table')
  })

  it('sends pdf, images and media to an iframe and everything else to download', () => {
    expect(fileMedia('spec.pdf')).toBe('iframe')
    expect(fileMedia('hero.png')).toBe('iframe')
    expect(fileMedia('clip.mp4')).toBe('iframe')
    expect(fileMedia('voice.mp3')).toBe('iframe')
    expect(fileMedia('notes.txt')).toBe('download')
    expect(fileMedia('data.json')).toBe('download')
  })

  it('opens html in preview only after a successful write', () => {
    expect(initialFileMode('html', true)).toBe('preview')
    expect(initialFileMode('html', false)).toBe('code')
    expect(initialFileMode('markdown', true)).toBe('preview')
  })

  it('parses a csv row', () => {
    expect(parseTable('item,note\n1,"a,b"\n', ',')).toEqual([['item', 'note'], ['1', 'a,b']])
  })

  it('recognises a file request in the general composer', () => {
    expect(looksLikeFile('写一个商品营销活动倒计时 HTML 页面')).toBe(true)
    expect(looksLikeFile('输出剃须刀参数对比表格')).toBe(true)
    expect(looksLikeFile('给这把剃须刀做一套 PDP')).toBe(false)
  })
})
