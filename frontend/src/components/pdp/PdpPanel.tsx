import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { VersionView } from '../../api/types'
import { pLabel, slotLabel, vLabel } from '../../lib/labels'
import { useApi } from '../../state/api-context'
import { useNav } from '../../state/nav'
import { useRefreshTask, useTaskData } from '../../state/useTaskData'
import { Tag } from '../Tag'
import {
  checkLines, failedCount, limitOf, noteOf, rowOf, slotRows, statusOf, STATUS_TEXT, type SlotRow,
} from './model'

type TabKey = 'preview' | 'check' | 'version' | 'cons'

/** The PDP workbench as a drawer panel (prototype: 预览 / 检查 / 版本 / 约束). Server data only. */
export function PdpPanel({ taskId }: { taskId: string }) {
  const api = useApi()
  const { nav, go } = useNav()
  const refresh = useRefreshTask(taskId)
  const { task, artifacts, feedback, constraints } = useTaskData(taskId)
  const rules = useQuery({ queryKey: ['platform'], queryFn: () => api.platformConstraints() })
  const productId = task.data?.product_id ?? null
  const product = useQuery({
    queryKey: ['product', productId], queryFn: () => api.product(productId as string), enabled: productId !== null,
  })
  const [tab, setTab] = useState<TabKey>('preview')

  const rows = slotRows(artifacts.data ?? [])
  const pdp = artifacts.data?.find((a) => a.kind === 'pdp')
  const any = rows.some((r) => r.versions.length > 0)
  const pending = constraints.data?.pending ?? []

  if (!any) {
    // Only reachable if the drawer was opened some other way; no preview exists without a version.
    return null
  }

  const attrs = Object.entries(product.data?.facts.attributes ?? {}).slice(0, 5)
  const facts = [
    ...(product.data ? [product.data.brand, product.data.marketplace].filter(Boolean) : []),
    ...(product.data?.facts.rating ? [`${product.data.facts.rating.stars}★ · ${product.data.facts.rating.ratings} 评分`] : []),
    ...attrs.map(([k, v]) => `${k}: ${v}`),
  ]

  const select = (slot: string, label: string, versionId?: string) =>
    go({ target: nav.target?.slot === slot ? null : { slot, label, versionId } })

  const tabs: [TabKey, string][] = [
    ['preview', '预览'], ['check', '检查'], ['version', '版本'],
    ['cons', `约束${pending.length ? ` ·${pending.length}` : ''}`],
  ]

  return (
    <div>
      {facts.length > 0 && <div className="x-facts">{facts.map((f) => <Tag key={f}>{f}</Tag>)}</div>}
      <div className="x-tabs-root">
        <div className="x-tabs" role="tablist">
          {tabs.map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={k === tab}
              className={`x-tab${k === tab ? ' is-active' : ''}`} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
        {tab === 'preview' && (
          <Paper rows={rows} selected={nav.target?.slot ?? null} onSelect={select}
            limits={{ title: limitOf(rules.data, 'title_max_chars'), search: limitOf(rules.data, 'search_terms_max_bytes') }} />
        )}
        {tab === 'check' && <CheckTab rows={rows} pdpSeq={pdp?.versions.find((v) => v.id === pdp.current_version_id)?.seq} onSelect={select} />}
        {tab === 'version' && (
          <VersionTab rows={rows} pdp={pdp?.versions ?? []} pdpCurrent={pdp?.current_version_id ?? null}
            feedback={feedback.data ?? []}
            onContinue={async (id) => { await api.makeCurrent(id); await refresh() }} />
        )}
        {tab === 'cons' && <ConsTab taskId={taskId} />}
      </div>
    </div>
  )
}

/* ───────── 预览 ───────── */
function slotTags(row: SlotRow | undefined) {
  if (!row || row.versions.length === 0) return <Tag>未提供</Tag>
  const cur = row.current
  const imported = cur?.origin === 'imported'
  return (
    <>
      <Tag cls={imported ? 'imp' : ''}>{cur ? `${vLabel(cur.seq)}${imported ? ' · 导入' : ''}` : '无当前版本'}</Tag>
      {imported && failedCount(cur) > 0 && <Tag cls="warn">基线问题</Tag>}
    </>
  )
}

function Paper({ rows, selected, onSelect, limits }: {
  rows: SlotRow[]; selected: string | null
  onSelect: (slot: string, label: string, versionId?: string) => void
  limits: { title?: number; search?: number }
}) {
  const sel = (slot: string, label: string) => ({
    className: `x-sel${selected === slot ? ' is-sel' : ''}`,
    'data-xslot': slot,
    role: 'button' as const,
    tabIndex: 0,
    'aria-pressed': selected === slot,
    'aria-label': label,
    onClick: () => onSelect(slot, label, rowOf(rows, slot)?.current?.id),
    onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'Enter') onSelect(slot, label, rowOf(rows, slot)?.current?.id) },
  })
  const main = rowOf(rows, 'main_image')
  const gallery = rowOf(rows, 'secondary_image')
  const title = rowOf(rows, 'title')
  const bullets = rowOf(rows, 'bullets')
  const desc = rowOf(rows, 'description')
  const terms = rowOf(rows, 'search_terms')
  const items = bullets?.current?.content.items ?? []
  const before = bullets?.current?.parent_version_id
    ? bullets.versions.find((v) => v.id === bullets.current?.parent_version_id)?.content.items
    : undefined
  const titleText = title?.current?.content.text

  return (
    <>
      <div className="x-paper">
        {main && (
          <div {...sel('main_image', `主图 · ${main.current ? vLabel(main.current.seq) : ''}`)}>
            <div className="x-tags">{slotTags(main)}</div>
            {main.current?.content.url ? (
              <div className="x-main-frame"><img className="x-fit" src={main.current.content.url} alt="主图" /></div>
            ) : <p className="x-ghost">还没有主图。可以在对话里让 Agent 生成。</p>}
          </div>
        )}
        {gallery && (
          <div {...sel('secondary_image', '副图')}>
            <div className="x-tags">{slotTags(gallery)}</div>
            {(gallery.current?.content.urls ?? []).length > 0 ? (
              <div className="x-thumbs">
                {(gallery.current?.content.urls ?? []).map((u, i) => (
                  <button key={u} type="button" className="x-thumb" data-xslot="secondary_image">
                    <img src={u} alt={`副图 ${i + 1}`} />
                  </button>
                ))}
              </div>
            ) : <p className="x-ghost">没有副图。副图目前只支持导入和展示，编辑后期开放。</p>}
          </div>
        )}
        {title && (
          <div {...sel('title', `标题 · ${title.current ? vLabel(title.current.seq) : ''}`)}>
            <div className="x-tags">{slotTags(title)}</div>
            {titleText ? (
              <>
                <h3 className="x-title">{titleText}</h3>
                <div className="x-meta">{titleText.length}{limits.title ? ` / ${limits.title}` : ''} 字符</div>
              </>
            ) : <p className="x-ghost">还没有标题。</p>}
          </div>
        )}
        {bullets && (
          <div {...sel('bullets', `五点 · ${bullets.current ? vLabel(bullets.current.seq) : ''}`)}>
            <div className="x-tags">{slotTags(bullets)}</div>
            {items.length ? (
              <ul className="x-bullets">
                {items.map((b, i) => (
                  <li key={i} className={before && before[i] !== b ? 'x-changed' : undefined}>
                    {b} <span className="x-len">{b.length} 字符</span>
                  </li>
                ))}
              </ul>
            ) : <p className="x-ghost">还没有五点。</p>}
          </div>
        )}
        {desc && (
          <div {...sel('description', '描述')}>
            <div className="x-tags">{slotTags(desc)}</div>
            {desc.current?.content.text
              ? <p>{desc.current.content.text}</p>
              : <p className="x-ghost">导入时没有提供描述。可以让 Agent 基于商品事实生成。</p>}
          </div>
        )}
      </div>
      {terms && (
        <div {...sel('search_terms', '后台关键词')} className={`x-sel x-kw${selected === 'search_terms' ? ' is-sel' : ''}`}>
          <div className="x-tags">{slotTags(terms)}<Tag>不在购物页展示</Tag></div>
          {terms.current?.content.text
            ? <p>{terms.current.content.text}{limits.search ? <span className="x-len"> {new TextEncoder().encode(terms.current.content.text).length} / {limits.search} 字节</span> : null}</p>
            : <p className="x-ghost">导入时没有提供后台关键词。</p>}
        </div>
      )}
    </>
  )
}

/* ───────── 检查 ───────── */
function CheckTab({ rows, pdpSeq, onSelect }: {
  rows: SlotRow[]; pdpSeq: number | undefined
  onSelect: (slot: string, label: string, versionId?: string) => void
}) {
  return (
    <>
      <p className="x-note">规则型检查由 Runtime 在每个新版本后自动运行；这里没有分数。导入的内容不会被拦截，只记录基线问题。</p>
      <div className="x-block">
        <h4>PDP manifest · {pdpSeq ? pLabel(pdpSeq) : '—'}</h4>
        <table className="x-table">
          <thead><tr><th>槽位</th><th>当前版本</th><th>来源</th><th>Run</th><th>检查</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const bad = failedCount(r.current)
              return (
                <tr key={r.slot} className="x-selrow" onClick={() => onSelect(r.slot, r.label, r.current?.id)}>
                  <td>{r.label}</td>
                  <td className="mono">{r.current ? vLabel(r.current.seq) : '—'}</td>
                  <td>{r.current ? (r.current.origin === 'imported' ? '导入' : '生成') : '—'}</td>
                  <td className="mono">{r.current?.run_id?.slice(-6) ?? '—'}</td>
                  <td>
                    {!r.current || r.current.evaluations.length === 0 ? '—'
                      : bad ? <Tag cls="warn">{bad} 项待处理</Tag> : <Tag cls="ok">全部通过</Tag>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {rows.filter((r) => r.current && r.current.evaluations.length > 0).map((r) => (
        <div className="x-block" key={r.slot}>
          <h4>{r.label} <span className="mono">{r.current ? vLabel(r.current.seq) : ''}</span></h4>
          <ul className="x-checks">
            {checkLines(r.current, r.versions[0]).map((c) => (
              <li key={c.code} className={`x-check ${c.ok ? 'ok' : 'bad'}`}>
                <span className="x-mark">{c.ok ? '通过' : '未通过'}</span>
                <div>
                  <div className="x-code">
                    {c.code} <span className="x-kind">规则</span>
                    {c.baseline && <Tag cls="warn">基线问题</Tag>}
                    {c.fixed && <Tag cls="ok">已解决</Tag>}
                  </div>
                  <div className="x-msg">{c.message}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </>
  )
}

/* ───────── 版本 ───────── */
function VersionTab({ rows, pdp, pdpCurrent, feedback, onContinue }: {
  rows: SlotRow[]; pdp: VersionView[]; pdpCurrent: string | null
  feedback: Parameters<typeof noteOf>[1]; onContinue: (versionId: string) => void
}) {
  return (
    <>
      {rows.filter((r) => r.versions.length > 0).map((r) => (
        <div className="x-block" key={r.slot}>
          <h4>{r.label}</h4>
          <ol className="x-tree">
            {r.versions.map((v) => {
              const st = statusOf(v, r.artifact.current_version_id)
              const { note, fb } = noteOf(v, feedback)
              const reason = v.status === 'rejected' ? checkLinesFailed(v) : ''
              return (
                <li key={v.id} className={`x-ver ${st}`}>
                  <span className="x-vdot" />
                  <div className="x-vbody">
                    <div className="x-vhead">
                      <b className="mono">{vLabel(v.seq)}</b>
                      <Tag cls={st === 'current' ? 'ok' : st === 'rejected' ? 'bad' : ''}>{STATUS_TEXT[st]}</Tag>
                      {v.origin === 'imported' && failedCount(v) > 0 && <Tag cls="warn">基线问题</Tag>}
                      <span className="x-who">{v.created_by === 'user' ? '用户' : 'Agent'}{v.run_id ? ` · ${v.run_id.slice(-6)}` : ''}</span>
                    </div>
                    <div className="x-vnote">{note}</div>
                    {fb && <div className="x-fb">反馈：「{fb}」</div>}
                    {reason && <div className="x-reason">{reason}。当前版本没有被替换。</div>}
                    {st === 'superseded' && (
                      <button type="button" className="x-link" onClick={() => onContinue(v.id)}>从这版继续</button>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>
          <Diff row={r} />
        </div>
      ))}
      <div className="x-block">
        <h4>PDP 版本</h4>
        <ol className="x-tree">
          {pdp.map((v) => (
            <li key={v.id} className={`x-ver ${v.id === pdpCurrent ? 'current' : 'superseded'}`}>
              <span className="x-vdot" />
              <div className="x-vbody">
                <div className="x-vhead">
                  <b className="mono">{pLabel(v.seq)}</b>
                  <Tag cls={v.id === pdpCurrent ? 'ok' : ''}>{v.id === pdpCurrent ? '当前' : '已被取代'}</Tag>
                  <span className="x-who">{v.created_by === 'user' ? '用户' : 'Agent'}{v.run_id ? ` · ${v.run_id.slice(-6)}` : ''}</span>
                </div>
                <div className="x-vnote">
                  {Object.entries(v.manifest).map(([s, id]) => {
                    const sv = rows.find((r) => r.slot === s)?.versions.find((x) => x.id === id)
                    return `${slotLabel(s)} ${sv ? vLabel(sv.seq) : ''}`
                  }).join(' · ')}
                </div>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </>
  )
}

const checkLinesFailed = (v: VersionView): string =>
  v.evaluations.filter((e) => !e.passed).flatMap((e) => (e.details.problems as string[] | undefined) ?? [e.evaluator_id]).join('；')

/** Imported baseline -> current: what improved (prototype "对比"). Only text slots with an edit. */
function Diff({ row }: { row: SlotRow }) {
  const first = row.versions[0]
  const cur = row.current
  if (!first || first.origin !== 'imported' || !cur || cur.id === first.id) return null
  const before = first.content.items ?? (first.content.text !== undefined ? [first.content.text] : null)
  const after = cur.content.items ?? (cur.content.text !== undefined ? [cur.content.text] : null)
  if (!before || !after) return null
  const changed = after.map((t, i) => (before[i] !== t ? i : -1)).filter((i) => i >= 0)
  const solved = first.evaluations.filter((e) => !e.passed && cur.evaluations.some((x) => x.evaluator_id === e.evaluator_id && x.passed)).length
  const left = failedCount(cur)
  return (
    <div style={{ marginTop: 10 }}>
      <div className="x-delta">
        <div><b>已解决 {solved}</b><span>相对导入版</span></div>
        <div><b>仍未解决 {left}</b><span>{cur.evaluations.filter((e) => !e.passed).map((e) => e.evaluator_id).join(' · ') || '—'}</span></div>
      </div>
      {changed.map((i) => (
        <div className="x-diff" key={i}>
          <div className="x-diff-l"><span>{vLabel(first.seq)}{after.length > 1 ? ` 第 ${i + 1} 条` : ''}</span>{before[i]}</div>
          <div className="x-diff-r"><span>{vLabel(cur.seq)}{after.length > 1 ? ` 第 ${i + 1} 条` : ''}</span>{after[i]}</div>
        </div>
      ))}
    </div>
  )
}

/* ───────── 约束 ───────── */
function ConsTab({ taskId }: { taskId: string }) {
  const api = useApi()
  const refresh = useRefreshTask(taskId)
  const { constraints } = useTaskData(taskId)
  const rules = useQuery({ queryKey: ['platform'], queryFn: () => api.platformConstraints() })
  const pend = constraints.data?.pending ?? []
  const act = constraints.data?.effective ?? []
  const scope = (rule: Record<string, unknown>) => (typeof rule.slot === 'string' ? `槽位 ${slotLabel(rule.slot)}` : '整个任务')
  const act2 = async (fn: () => Promise<unknown>) => { await fn(); await refresh() }
  return (
    <>
      {pend.length > 0 && (
        <div className="x-block">
          <h4>等待确认</h4>
          {pend.map((c) => (
            <div className="x-con pending" key={c.id}>
              <div><b>{c.text}</b><div className="x-sub">{String(c.rule.type ?? 'note')} · 作用域：{scope(c.rule)}</div></div>
              <div className="x-btns">
                <button type="button" className="btn btn-teal btn-sm" onClick={() => void act2(() => api.confirmConstraint(c.id))}>确认</button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => void act2(() => api.revokeConstraint(c.id))}>忽略</button>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="x-block">
        <h4>我的约束</h4>
        {act.length ? act.map((c) => (
          <div className="x-con" key={c.id}>
            <div><b>{c.text}</b><div className="x-sub">{String(c.rule.type ?? 'note')} · 作用域：{scope(c.rule)}</div></div>
            <button type="button" className="x-link" onClick={() => void act2(() => api.revokeConstraint(c.id))}>撤销</button>
          </div>
        )) : <p className="x-ghost">暂无。在对话里说「标题不要超过 80 个字符」之类的话，会先出现在“等待确认”。</p>}
      </div>
      <div className="x-block">
        <h4>平台约束 · 只读</h4>
        {(rules.data?.items ?? []).map((c) => (
          <div className="x-con" key={c.key}>
            <div><b>{c.summary}</b><div className="x-sub">{c.key} · hard · {slotLabel(c.slot)}</div></div>
            <Tag>平台</Tag>
          </div>
        ))}
        {rules.data && <p className="x-note">约束包 {rules.data.pack_id} {rules.data.version}：{rules.data.note}。用户不能改写平台约束。</p>}
      </div>
    </>
  )
}
