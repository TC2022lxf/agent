// One-off helper: copies the prototype CSS (design/…/workbench.html, image-design.html) into
// src/styles so the React app uses the very same visual system as the approved prototype.
// Usage: node scripts/extract-proto-css.mjs
import { readFileSync, writeFileSync } from 'node:fs'

const dir = new URL('../../design/a4dabcc1-9c5d-4405-8afc-715c864d3c95/', import.meta.url)
const styleOf = (file) => {
  const html = readFileSync(new URL(file, dir), 'utf8')
  const a = html.indexOf('<style>') + '<style>'.length
  return html.slice(a, html.indexOf('</style>'))
}

// 1) workbench: used verbatim
writeFileSync(
  new URL('../src/styles/proto.css', import.meta.url),
  '/* Copied from design/…/workbench.html by scripts/extract-proto-css.mjs. Do not restyle here. */\n' +
    styleOf('workbench.html'),
)

// 2) image-design: scoped under .imgpage so it cannot change the other views.
const css = styleOf('image-design.html')
const SHARED = /^(:root|\*|html|body|\.app|\.sr-only|\.sidebar|\.nav-|\.brand-mark|\.sidebar-)/
const out = []
let rest = css
const re = /([^{}]+)\{([^{}]*)\}/g
let m
const keyframes = []
// pull @keyframes out first (nested braces)
rest = rest.replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, (k) => {
  keyframes.push(k)
  return ''
})
while ((m = re.exec(rest))) {
  const selectors = m[1].trim().split(',').map((s) => s.trim()).filter(Boolean)
  const kept = selectors.filter((s) => !SHARED.test(s))
  if (selectors.some((s) => s === ':root')) {
    out.push(`.imgpage {${m[2]}}`)
    continue
  }
  if (!kept.length) continue
  out.push(kept.map((s) => `.imgpage ${s}`).join(',\n') + ` {${m[2]}}`)
}
writeFileSync(
  new URL('../src/styles/image-studio.css', import.meta.url),
  '/* Copied from design/…/image-design.html, scoped to .imgpage. */\n' + out.join('\n') + '\n' + keyframes.join('\n') + '\n',
)
console.log('ok', out.length, 'rules', keyframes.length, 'keyframes')
