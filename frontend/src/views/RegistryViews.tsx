import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { ToolDetail } from '../api/types'
import { AUDIENCE_LABEL, skillAudience } from '../lib/labels'
import { useApi } from '../state/api-context'
import { useNav } from '../state/nav'
import { useToast } from '../state/toast'

type Schema = ToolDetail['input_schema']

function SchemaTable({ title, schema }: { title: string; schema: Schema }) {
  const props = Object.entries(schema.properties ?? {})
  return (
    <div className="schema-block">
      <div className="schema-block-head"><span>{title}</span></div>
      <table className="x-table" style={{ width: '100%', fontSize: 12 }}>
        <thead><tr><th>字段</th><th>类型</th><th>必填</th><th>说明</th></tr></thead>
        <tbody>
          {props.map(([k, v]) => (
            <tr key={k}>
              <td className="mono">{k}</td><td>{v.type ?? 'any'}</td>
              <td>{schema.required?.includes(k) ? '是' : ''}</td><td>{v.description ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ToolForm({ name, schema }: { name: string; schema: Schema }) {
  const api = useApi()
  const toast = useToast()
  const props = Object.entries(schema.properties ?? {})
  const [values, setValues] = useState<Record<string, string>>({})
  const [out, setOut] = useState('')
  const [pending, setPending] = useState(false)
  const run = async () => {
    const input: Record<string, unknown> = {}
    for (const [key, spec] of props) {
      const raw = values[key] ?? ''
      if (!raw) continue
      if (spec.type === 'integer' || spec.type === 'number') input[key] = Number(raw)
      else if (spec.type === 'string') input[key] = raw
      else {
        try { input[key] = JSON.parse(raw) } catch { toast(`${key} 不是合法 JSON`); return }
      }
    }
    setPending(true)
    try {
      setOut(JSON.stringify(await api.invokeTool(name, input), null, 2))
    } catch (e) {
      toast(e instanceof Error ? e.message : '调用失败')
    } finally {
      setPending(false)
    }
  }
  return (
    <div className="schema-block">
      <div className="schema-block-head"><span>试用</span></div>
      <p className="x-note">直接调用这个 Tool，不经过 Agent 运行时。返回值不会写成 Version。</p>
      {props.map(([key, spec]) => (
        <div className="field" key={key}>
          <label htmlFor={`in-${key}`}>{key}{schema.required?.includes(key) ? ' *' : ''}</label>
          {spec.type === 'string' || spec.type === 'integer' || spec.type === 'number'
            ? <input id={`in-${key}`} value={values[key] ?? ''} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
            : <textarea id={`in-${key}`} rows={3} placeholder="{}" value={values[key] ?? ''} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />}
        </div>
      ))}
      <button type="button" className="btn btn-teal btn-sm" disabled={pending} onClick={() => void run()}>运行</button>
      {out && <pre style={{ whiteSpace: 'pre-wrap' }}>{out}</pre>}
    </div>
  )
}

/** Registry (docs/04). The detail page can run a tool; it does not edit the registration. */
export function ToolsView() {
  const api = useApi()
  const { nav, go } = useNav()
  const list = useQuery({ queryKey: ['tools'], queryFn: () => api.tools() })
  const detail = useQuery({ queryKey: ['tool', nav.toolName], enabled: !!nav.toolName, queryFn: () => api.tool(nav.toolName as string) })

  if (nav.toolName) {
    const t = detail.data
    return (
      <section className="view is-active">
        <div className="panel-body detail-layout">
          <button type="button" className="back-link" onClick={() => go({ toolName: null })}>← 返回工具列表</button>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 16 }}>
            <div>
              <h1 style={{ fontSize: 20, fontWeight: 600, margin: '0 0 4px' }}>{nav.toolName}</h1>
              <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)' }}>{t?.description}</p>
            </div>
            <span className="badge badge-on">已登记</span>
          </div>
          {t && (
            <>
              <dl className="product-detail-meta">
                <div><dt>版本</dt><dd>{t.version}</dd></div>
                <div><dt>副作用</dt><dd>{t.side_effect}</dd></div>
                <div><dt>成本</dt><dd>{t.cost_credits} 积分</dd></div>
                <div><dt>超时</dt><dd>{t.timeout_s}s</dd></div>
                <div><dt>幂等</dt><dd>{t.idempotent ? '是' : '否'}</dd></div>
                <div><dt>可用 Agent</dt><dd>{t.agents.join('、') || '—'}</dd></div>
              </dl>
              <SchemaTable title="输入 schema" schema={t.input_schema} />
              <SchemaTable title="输出 schema" schema={t.output_schema} />
              <ToolForm name={t.name} schema={t.input_schema} />
            </>
          )}
        </div>
      </section>
    )
  }
  return (
    <section className="view is-active">
      <div className="panel-body">
        <div className="x-banner"><b>登记表。</b>点进一个 Tool 可以填参数直接调用。新增 Tool 仍必须带 schema，缺少声明登记失败。</div>
        <div className="card-grid">
          {list.data?.map((t) => (
            <button key={t.name} type="button" className="resource-card" onClick={() => go({ toolName: t.name })}>
              <div className="rc-fn">{t.name}</div>
              <p className="rc-desc">{t.description}</p>
              <div className="rc-meta"><span className="badge badge-on">已登记</span><span className="badge badge-version">{t.version}</span></div>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}

/**
 * Skills (docs/13). Every Skill is visible; editing saves a revision, never the repo file.
 * A stale `revision` comes back as 409 and the editor reloads instead of overwriting.
 */
export function SkillsView() {
  const api = useApi()
  const toast = useToast()
  const qc = useQueryClient()
  const { nav, go } = useNav()
  const [filter, setFilter] = useState<'all' | 'general' | 'pdp' | 'image'>('all')
  const list = useQuery({ queryKey: ['skills'], queryFn: () => api.skills() })
  const detail = useQuery({ queryKey: ['skill', nav.skillId], enabled: !!nav.skillId, queryFn: () => api.skill(nav.skillId as string) })
  const revisions = useQuery({
    queryKey: ['skill-revisions', nav.skillId], enabled: !!nav.skillId,
    queryFn: () => api.skillRevisions(nav.skillId as string),
  })
  const [draft, setDraft] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [conflict, setConflict] = useState<string | null>(null)

  const open = detail.data
  const saved = open?.body ?? ''
  const text = draft ?? saved
  const dirty = draft !== null && draft !== saved

  useEffect(() => {
    setDraft(null)
    setConflict(null)
  }, [nav.skillId])

  const reload = async () => {
    await qc.invalidateQueries({ queryKey: ['skill', nav.skillId] })
    await qc.invalidateQueries({ queryKey: ['skills'] })
    await qc.invalidateQueries({ queryKey: ['skill-revisions', nav.skillId] })
    setDraft(null)
    setConflict(null)
  }

  const save = async () => {
    if (!open || draft === null) return
    setPending(true)
    try {
      const next = await api.saveSkill(open.id, draft, open.revision)
      qc.setQueryData(['skill', open.id], next)
      await qc.invalidateQueries({ queryKey: ['skills'] })
      await qc.invalidateQueries({ queryKey: ['skill-revisions', open.id] })
      setDraft(null)
      setConflict(null)
      toast(`已保存修订 ${next.revision}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : '保存失败'
      if (msg.includes('STALE') || msg.includes('已被改过')) setConflict(msg)
      else toast(msg)
    } finally {
      setPending(false)
    }
  }

  const reset = async () => {
    if (!open) return
    setPending(true)
    try {
      const next = await api.resetSkill(open.id)
      qc.setQueryData(['skill', open.id], next)
      await qc.invalidateQueries({ queryKey: ['skills'] })
      await qc.invalidateQueries({ queryKey: ['skill-revisions', open.id] })
      setDraft(null)
      toast('已恢复仓库正文')
    } catch (e) {
      toast(e instanceof Error ? e.message : '恢复失败')
    } finally {
      setPending(false)
    }
  }

  if (nav.skillId) {
    return (
      <section className="view is-active">
        <div className="skill-detail-page">
          <header className="skill-detail-topbar">
            <button type="button" className="back-link" onClick={() => go({ skillId: null })}>← 返回技能列表</button>
          </header>
          <div className="panel-body skill-detail-body-wrap">
            <div className="x-banner">
              <b>可编辑。</b>保存写入数据库修订，不覆盖仓库里的 skills/{nav.skillId}/SKILL.md。
              别人先改过时保存会失败，需要重新加载，避免互相覆盖。
            </div>
            {open && (
              <>
                <dl className="skill-claude-meta">
                  <div><dt>id</dt><dd>{open.id}</dd></div>
                  <div><dt>归属</dt><dd>{AUDIENCE_LABEL[skillAudience(open.audience)]}</dd></div>
                  <div><dt>说明</dt><dd>{open.description}</dd></div>
                  <div><dt>用到的 Tool</dt><dd>{open.tools.map((t) => <span key={t} className="market-tag">{t}</span>)}</dd></div>
                  <div><dt>修订</dt><dd>{open.revision === 0 ? '仓库版' : `r${open.revision} · ${open.source}`}</dd></div>
                  <div><dt>内容哈希</dt><dd className="mono">{open.hash.slice(0, 12)}</dd></div>
                </dl>
                {conflict && (
                  <div className="x-fail">
                    <b>保存被拒绝</b>
                    <p>{conflict}</p>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => void reload()}>
                      放弃我的改动，加载最新
                    </button>
                  </div>
                )}
                <textarea
                  className="skill-editor"
                  aria-label="Skill 正文"
                  value={text}
                  spellCheck={false}
                  onChange={(e) => setDraft(e.target.value)}
                />
                <div className="skill-editor-actions">
                  <button type="button" className="btn btn-teal btn-sm" disabled={!dirty || pending} onClick={() => void save()}>
                    {pending ? '保存中…' : '保存'}
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm" disabled={draft === null || pending} onClick={() => setDraft(null)}>
                    放弃改动
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm" disabled={pending} onClick={() => void reset()}>
                    恢复仓库正文
                  </button>
                  {dirty && <span className="x-note">未保存 · 基于 r{open.revision}</span>}
                </div>
                {revisions.data && revisions.data.length > 0 && (
                  <div className="schema-block">
                    <div className="schema-block-head"><span>修订历史</span></div>
                    <table className="x-table" style={{ width: '100%', fontSize: 12 }}>
                      <thead><tr><th>修订</th><th>来源</th><th>修改人</th><th>时间</th></tr></thead>
                      <tbody>
                        {revisions.data.map((r) => (
                          <tr key={r.revision}>
                            <td className="mono">r{r.revision}</td><td>{r.source}</td>
                            <td>{r.edited_by}</td><td>{new Date(r.created_at).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </section>
    )
  }

  const shown = (list.data ?? []).filter((s) => filter === 'all' || skillAudience(s.audience) === filter)
  return (
    <section className="view is-active">
      <div className="panel-body">
        <div className="x-banner">
          <b>Skill 可编辑。</b>通用 Agent 能用全部；PDP 和图片 Agent 只能用各自那一类。
        </div>
        <div className="artifact-filters">
          {([['all', '全部'], ['general', '通用'], ['pdp', 'PDP'], ['image', '图片']] as const).map(([id, label]) => (
            <button key={id} type="button" className={`btn btn-secondary btn-sm${filter === id ? ' is-on' : ''}`} onClick={() => setFilter(id)}>{label}</button>
          ))}
        </div>
        <div className="skill-row-list">
          {shown.map((s) => (
            <div key={s.id} className="skill-row" role="button" tabIndex={0}
              onClick={() => go({ skillId: s.id })} onKeyDown={(e) => { if (e.key === 'Enter') go({ skillId: s.id }) }}>
              <div className="skill-row-main">
                <p className="skill-row-title">{s.id}</p>
                <p className="skill-row-desc">{s.description}</p>
              </div>
              <div className="skill-row-meta">
                <span className="badge badge-on">{AUDIENCE_LABEL[skillAudience(s.audience)]}</span>
                {s.revision > 0 && <span className="badge badge-version">r{s.revision}</span>}
                <span className="badge badge-version">{s.tools.length} 个 Tool</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}