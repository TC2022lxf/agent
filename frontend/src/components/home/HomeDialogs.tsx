import { useEffect, useState, type ReactNode } from 'react'
import {
  FILE_STARTER, PDP_STARTERS, PROMPT_STARTERS, RATIOS, REFERENCE_STARTERS,
  type Ratio, type Starter, pdpBrief, withRatio,
} from './starters'

function Modal({ title, wide, onClose, children, extra }: {
  title: string
  wide?: boolean
  onClose: () => void
  extra?: ReactNode
  children: ReactNode
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-root is-open" role="presentation" onMouseDown={onClose}>
      <div className={`modal-dialog${wide ? ' is-expanded' : ''}`} role="dialog" aria-modal="true" aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}>
        <header className="modal-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h2 className="modal-title" style={{ margin: 0 }}>{title}</h2>
          <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{extra}
            <button type="button" className="btn btn-ghost btn-sm" aria-label="关闭" onClick={onClose}>×</button>
          </span>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

function Thumb({ starter, onClick }: { starter: Starter; onClick: () => void }) {
  return (
    <button type="button" className="starter-card" onClick={onClick}>
      <span className="starter-swatch" style={{ background: starter.swatch }} />
      <strong>{starter.title}</strong>
      <span>{starter.note}</span>
    </button>
  )
}

/** 文档 / 媒体, then the image board or the PDP brief. */
export function CreateFlow({ pending, onClose, onPdp, onFile, onImage, onFill }: {
  pending: boolean
  onClose: () => void
  onPdp: (text: string) => void
  onFile?: (text: string) => void
  onImage: (text: string, file: File | null) => void
  /** Pure-prompt templates drop into the composer instead of generating at once. */
  onFill?: (text: string) => void
}) {
  const [step, setStep] = useState<'catalog' | 'images' | 'pdp' | 'ref'>('catalog')
  const [ref, setRef] = useState<Starter | null>(null)
  const [pdpLead, setPdpLead] = useState(PDP_STARTERS[0]?.prompt ?? '')

  if (step === 'ref' && ref) {
    return (
      <ReferenceDialog starter={ref} pending={pending} onClose={onClose}
        onBack={() => setStep('images')}
        onTry={(text, file) => onImage(text, file)} />
    )
  }
  if (step === 'pdp') {
    return (
      <PdpDialog lead={pdpLead} pending={pending} onClose={onClose} onBack={() => setStep('catalog')} onSubmit={onPdp} />
    )
  }
  if (step === 'images') {
    return (
      <Modal title="商品图" wide onClose={onClose}>
        <div className="starter-split">
          <section>
            <h3>纯提示词</h3>
            <p className="x-sub">点一下填入输入框，改完再发送。</p>
            <div className="starter-grid">
              {PROMPT_STARTERS.map((s) => (
                <Thumb key={s.id} starter={s} onClick={() => {
                  if (onFill) { onFill(s.prompt); onClose() } else onImage(s.prompt, null)
                }} />
              ))}
            </div>
          </section>
          <section>
            <h3>需要参考图</h3>
            <p className="x-sub">打开弹窗：默认提示词 + 上传参考图。</p>
            <div className="starter-grid">
              {REFERENCE_STARTERS.map((s) => (
                <Thumb key={s.id} starter={s} onClick={() => { setRef(s); setStep('ref') }} />
              ))}
            </div>
          </section>
        </div>
      </Modal>
    )
  }
  return (
    <Modal title="创建" wide onClose={onClose}>
      <p className="catalog-label">文档</p>
      <button type="button" className="catalog-card" onClick={() => { setPdpLead(PDP_STARTERS[0]?.prompt ?? ''); setStep('pdp') }}>
        <span className="catalog-thumb doc">PDP</span>
        <span><strong>亚马逊 PDP 详情</strong><small>标题、五点、描述和主图</small></span>
      </button>
      {onFile && (
        <button type="button" className="catalog-card" onClick={() => onFile(FILE_STARTER)}>
          <span className="catalog-thumb doc">HTML</span>
          <span><strong>网页、笔记、表格</strong><small>HTML 默认预览，写入失败才看源码</small></span>
        </button>
      )}
      <p className="catalog-label">媒体</p>
      <button type="button" className="catalog-card" onClick={() => setStep('images')}>
        <span className="catalog-thumb pic" />
        <span><strong>图片</strong><small>主图、场景图、特写</small></span>
      </button>
    </Modal>
  )
}

export function PdpDialog({ lead, pending, onClose, onBack, onSubmit }: {
  lead: string
  pending: boolean
  onClose: () => void
  onBack?: () => void
  onSubmit: (text: string) => void
}) {
  const [name, setName] = useState('')
  const [brand, setBrand] = useState('')
  const [points, setPoints] = useState('')
  const [site, setSite] = useState('amazon.com')
  return (
    <Modal title="亚马逊 PDP" onClose={onClose}>
      <p className="x-note">{lead}</p>
      <div className="field"><label htmlFor="pdp-name">商品名称</label>
        <input id="pdp-name" value={name} placeholder="例如：迷你电动剃须刀" onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field"><label htmlFor="pdp-brand">品牌</label>
        <input id="pdp-brand" value={brand} onChange={(e) => setBrand(e.target.value)} />
      </div>
      <div className="field"><label htmlFor="pdp-points">卖点和人群</label>
        <textarea id="pdp-points" rows={3} value={points} placeholder="谁在用、解决什么问题、不能编造的事实" onChange={(e) => setPoints(e.target.value)} />
      </div>
      <div className="field"><label htmlFor="pdp-site">站点</label>
        <input id="pdp-site" value={site} onChange={(e) => setSite(e.target.value)} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        {onBack && <button type="button" className="btn btn-secondary btn-sm" onClick={onBack}>返回</button>}
        <button type="button" className="btn btn-teal btn-sm" disabled={pending || !name.trim()}
          onClick={() => onSubmit(pdpBrief({ name: name.trim(), brand: brand.trim(), points: points.trim(), site: site.trim() }, lead))}>
          开始做
        </button>
      </div>
    </Modal>
  )
}

export function ReferenceDialog({ starter, pending, onClose, onBack, onTry }: {
  starter: Starter
  pending: boolean
  onClose: () => void
  onBack: () => void
  onTry: (text: string, file: File) => void
}) {
  const [prompt, setPrompt] = useState(starter.prompt)
  const [ratio, setRatio] = useState<Ratio>('自动')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])
  const pick = (f: File | null) => {
    setFile(f)
    setPreview((old) => {
      if (old) URL.revokeObjectURL(old)
      return f ? URL.createObjectURL(f) : null
    })
  }
  return (
    <Modal title={starter.title} wide onClose={onClose}
      extra={<button type="button" className="btn btn-ghost btn-sm" onClick={onBack}>返回</button>}>
      <div className="ref-dialog">
        <div className="ref-preview">
          {preview ? (
            <>
              <img src={preview} alt="参考图预览" />
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => pick(null)}>移除</button>
            </>
          ) : (
            <label className="ref-drop">
              <span>拖入或点击上传参考图</span>
              <span className="x-sub">商品图、场景图都可以；模型保留这张图里的商品外观。</span>
              <input type="file" accept="image/*" aria-label="上传参考图" hidden
                onChange={(e) => { pick(e.target.files?.[0] ?? null); e.target.value = '' }} />
            </label>
          )}
        </div>
        <div className="ref-side">
          <div className="field">
            <label htmlFor="ref-prompt">提示词</label>
            <textarea id="ref-prompt" aria-label="图片提示词" rows={5} value={prompt}
              onChange={(e) => setPrompt(e.target.value)} />
          </div>
          <div className="ref-row"><span>宽高比例</span>
            <select aria-label="宽高比例" value={ratio} onChange={(e) => setRatio(e.target.value as Ratio)}>
              {RATIOS.map((r) => <option key={r}>{r}</option>)}
            </select>
          </div>
          <p className="x-sub">{starter.note}</p>
          <div className="ref-actions">
            <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>取消</button>
            <button type="button" className="btn btn-teal" disabled={pending || !file || !prompt.trim()}
              onClick={() => file && onTry(withRatio(prompt.trim(), ratio), file)}>
              {pending ? '生成中…' : '生成图片'}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  )
}
