import { useState } from 'react'
import { CreateFlow, PdpDialog, ReferenceDialog } from '../home/HomeDialogs'
import { FILE_STARTER, PDP_STARTERS, PROMPT_STARTERS, REFERENCE_STARTERS, type Starter } from '../home/starters'

/** Centered empty agent. General lists what we can make; PDP and image put templates above the box. */
export function AgentHome({ mode, title, lede, placeholder, productLine, pending, onText, onPdp, onFile, onImage }: {
  mode: 'general' | 'pdp' | 'image'
  title: string
  lede: string
  placeholder: string
  productLine?: string
  pending: boolean
  onText: (text: string) => void
  onPdp: (text: string) => void
  onFile?: (text: string) => void
  onImage: (text: string, file: File | null) => void
}) {
  const [text, setText] = useState('')
  const [catalog, setCatalog] = useState(false)
  const [pdpLead, setPdpLead] = useState<string | null>(null)
  const [ref, setRef] = useState<Starter | null>(null)
  const send = () => {
    const t = text.trim()
    if (!t || pending) return
    onText(t)
  }

  return (
    <div className="agent-home">
      <div className="agent-home-inner">
        <h1>{title}</h1>
        <p className="agent-home-lede">{lede}</p>
        {productLine && <p className="x-note">{productLine}</p>}

        {mode === 'general' && (
          <div className="home-bento">
            <button type="button" className="launch-card bento-create" onClick={() => setCatalog(true)}>
              <span className="launch-kicker">创建</span>
              <strong>亚马逊 PDP、商品图</strong>
              <span>文档里做详情页，媒体里做图片</span>
            </button>
            {PROMPT_STARTERS.slice(0, 1).map((s) => (
              <button key={s.id} type="button" className="starter-card bento-img" disabled={pending} onClick={() => onImage(s.prompt, null)}>
                <span className="starter-swatch" style={{ background: s.swatch }} />
                <strong>{s.title}</strong>
                <span>{s.note}</span>
              </button>
            ))}
            {REFERENCE_STARTERS.slice(0, 1).map((s) => (
              <button key={s.id} type="button" className="starter-card bento-img" disabled={pending} onClick={() => setRef(s)}>
                <span className="starter-swatch" style={{ background: s.swatch }} />
                <strong>{s.title}</strong>
                <span>{s.note}</span>
              </button>
            ))}
            {onFile && (
              <button type="button" className="starter-card bento-doc" disabled={pending} onClick={() => onFile(FILE_STARTER)}>
                <strong>活动页</strong>
                <span>HTML 预览</span>
              </button>
            )}
            {PDP_STARTERS.slice(0, 1).map((s) => (
              <button key={s.id} type="button" className="starter-card bento-pdp" disabled={pending} onClick={() => setPdpLead(s.prompt)}>
                <span className="starter-swatch" style={{ background: s.swatch }} />
                <strong>{s.title}</strong>
                <span>{s.note}</span>
              </button>
            ))}
          </div>
        )}

        {mode === 'pdp' && (
          <div className="starter-grid above">
            {PDP_STARTERS.map((s) => (
              <button key={s.id} type="button" className="starter-card" disabled={pending} onClick={() => setPdpLead(s.prompt)}>
                <span className="starter-swatch" style={{ background: s.swatch }} />
                <strong>{s.title}</strong>
                <span>{s.note}</span>
              </button>
            ))}
          </div>
        )}

        {mode === 'image' && (
          <div className="starter-split above">
            <section>
              <h3>纯提示词</h3>
              <p className="x-sub">点一下填入输入框，改完再发送。</p>
              <div className="starter-grid">
                {PROMPT_STARTERS.map((s) => (
                  <button key={s.id} type="button" className="starter-card" disabled={pending} onClick={() => setText(s.prompt)}>
                    <span className="starter-swatch" style={{ background: s.swatch }} />
                    <strong>{s.title}</strong><span>{s.note}</span>
                  </button>
                ))}
              </div>
            </section>
            <section>
              <h3>需要参考图</h3>
              <p className="x-sub">点一下打开弹窗：默认提示词 + 上传参考图。</p>
              <div className="starter-grid">
                {REFERENCE_STARTERS.map((s) => (
                  <button key={s.id} type="button" className="starter-card" disabled={pending} onClick={() => setRef(s)}>
                    <span className="starter-swatch" style={{ background: s.swatch }} />
                    <strong>{s.title}</strong><span>{s.note}</span>
                  </button>
                ))}
              </div>
            </section>
          </div>
        )}
        <div className="gpt-composer">
          {mode === 'general' && (
            <button type="button" className="gpt-plus" aria-label="添加" onClick={() => setCatalog(true)}>+</button>
          )}
          <textarea rows={1} value={text} aria-label="消息输入" placeholder={placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() }
            }} />
          <button type="button" className="gpt-send" aria-label="发送" disabled={pending || !text.trim()} onClick={send}>
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>
        </div>
      </div>

      {catalog && (
        <CreateFlow pending={pending} onClose={() => setCatalog(false)} onPdp={onPdp} onFile={onFile} onImage={onImage} onFill={setText} />
      )}
      {pdpLead && (
        <PdpDialog lead={pdpLead} pending={pending} onClose={() => setPdpLead(null)} onSubmit={onPdp} />
      )}
      {ref && (
        <ReferenceDialog starter={ref} pending={pending} onClose={() => setRef(null)} onBack={() => setRef(null)}
          onTry={(prompt, file) => onImage(prompt, file)} />
      )}
    </div>
  )
}
