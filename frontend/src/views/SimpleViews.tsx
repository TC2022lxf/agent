import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { TaskView } from '../api/types'
import { hasAnyVersion, openTargetFor } from '../lib/artifacts'
import { STATUS_LABEL, fmtTime, taskKindLabel } from '../lib/labels'
import { useApi } from '../state/api-context'
import { useNav, type ViewName } from '../state/nav'
import { keys } from '../state/useTaskData'

export function HomeView() {
  const { go } = useNav()
  const jump = (view: ViewName, agent?: string) => () => go({ view, ...(agent ? { agent } : {}) })
  const cards: [string, string, ViewName][] = [
    ['改某一个槽位', '点预览里的主图、标题或某条五点，再说一句话。只会改那个槽位。', 'chat'],
    ['版本、检查与对比', '每次修改都是新版本；规则检查自动运行，没有分数。', 'chat'],
    ['商品与事实', 'Agent 只能使用这里的事实和你补充的事实。', 'products'],
    ['导入已有 Listing', '导入的内容是第一版，再优化，对比里看提升了什么。', 'artifacts'],
    ['Tool 与 Skill（管理员）', '只读：登记元数据和 SKILL.md 预览。', 'tools'],
  ]
  return (
    <section className="view is-active">
      <div className="home-scroll">
        <div className="home-hero">
          <h1>电商 AI · 通用 Agent</h1>
          <p>通用 Agent 汇集所有能力：聊天里直接生成 PDP、编辑图片，成果卡片打开对应工作台。也可以单独进入专用 Agent（PDP、图片、画布）。邀请内测阶段。</p>
          <div className="home-cta">
            <button type="button" className="btn btn-primary" onClick={jump('chat', 'general')}>进入通用 Agent</button>
          </div>
        </div>
        <p className="home-section-title">现在能做什么</p>
        <div className="home-grid">
          {cards.map(([t, d, v]) => (
            <div key={t} className="home-card" role="button" tabIndex={0} style={{ cursor: 'pointer' }}
              onClick={jump(v)} onKeyDown={(e) => { if (e.key === 'Enter') jump(v)() }}>
              <h2>{t}</h2><p>{d}</p>
            </div>
          ))}
          <div className="home-card" style={{ opacity: 0.6 }}><h2>后期：自动化</h2><p>MVP 不做，只保留交互示意。</p></div>
        </div>
      </div>
    </section>
  )
}

export function HistoryView() {
  const api = useApi()
  const { openTask } = useNav()
  const tasks = useQuery({ queryKey: keys.tasks, queryFn: () => api.listTasks() })
  return (
    <section className="view is-active">
      <div className="panel-body">
        <div className="history-list">
          {tasks.data?.length === 0 && <p className="x-ghost">还没有任务。在通用 Agent 里开始一个。</p>}
          {tasks.data?.map((t) => (
            <button key={t.id} type="button" className="history-row" onClick={() => openTask(t.id, t.agent_key)}>
              <div className="history-title">{t.goal || '未命名任务'}</div>
              <div className="history-meta">
                {taskKindLabel(t.kind)} · {STATUS_LABEL[t.status] ?? t.status} · {fmtTime(t.created_at)}
                {t.meta.product ? ` · ${t.meta.product.name}` : ''}
              </div>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}

export function ArtifactsView() {
  const api = useApi()
  const { go, openTask, openDrawer } = useNav()
  const tasks = useQuery({ queryKey: keys.tasks, queryFn: () => api.listTasks() })
  const [kind, setKind] = useState<'all' | 'pdp' | 'image' | 'file' | 'canvas'>('all')
  const shown = (tasks.data ?? []).filter((t) => kind === 'all' || t.kind === kind)

  /** Projects start from an existing artifact. A task with nothing in it has no preview. */
  const open = (t: TaskView) => {
    const target = openTargetFor(t)
    if (target === null) { openTask(t.id, t.agent_key); return }
    if ('view' in target && target.view === 'image') {
      go({ view: 'image', agent: 'image', imageTaskId: t.id, imageSlot: 'image', bootText: null })
      return
    }
    if ('view' in target && target.view === 'canvas') {
      go({ view: 'canvas', agent: 'canvas', canvasTaskId: t.id, bootText: null })
      return
    }
    openTask(t.id, t.agent_key)
    if ('kind' in target) openDrawer(target)
  }

  return (
    <section className="view is-active">
      <div className="panel-body">
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 6px' }}>Artifact</h1>
        <p className="x-note">
          通用 Agent、PDP Agent 和图片 Agent 做过的编辑项目。点开直接看当前版本。
          新的项目在对应 Agent 里开始，这里不重复新建入口。
        </p>
        <div className="artifact-filters">
          {([['all', '全部'], ['pdp', 'PDP'], ['image', '图片'], ['file', '文件'], ['canvas', '画布']] as const).map(([id, label]) => (
            <button key={id} type="button" className={`btn btn-secondary btn-sm${kind === id ? ' is-on' : ''}`} onClick={() => setKind(id)}>{label}</button>
          ))}
        </div>
        {shown.length === 0 && <p className="x-ghost">还没有这类项目。去通用 Agent 或图片 Agent 开始一个。</p>}
        <div className="artifact-projects">
          {shown.map((t) => {
            const empty = !hasAnyVersion(t)
            return (
              <button key={t.id} type="button" className={`artifact-project${empty ? ' is-empty' : ''}`} onClick={() => open(t)}>
                <span className="badge badge-version">{taskKindLabel(t.kind)}</span>
                <h3>{t.goal || '未命名项目'}</h3>
                <p>
                  {t.meta.product?.name ?? '未关联商品'} · {STATUS_LABEL[t.status] ?? t.status} · {fmtTime(t.created_at)}
                  {empty ? ' · 还没有产物' : ''}
                </p>
              </button>
            )
          })}
        </div>
      </div>
    </section>
  )
}

/** Automation is a later capability: nothing runs unattended in this stage. */
export function LaterView() {
  return (
    <section className="view is-active">
      <div className="panel-body">
        <div className="x-banner">
          <b>后期能力，MVP 不做。</b>
          {'定时和事件触发的 Run 没人值守，却会产生真实模型成本。要做，先要有单次预算上限、暂停和对账，再改 docs/03 里 Run.trigger 的取值。'}
        </div>
      </div>
    </section>
  )
}
