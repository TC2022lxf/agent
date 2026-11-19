import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useApi } from '../state/api-context'
import { isAdmin, useAuth } from '../state/auth'
import { useNav, type NavState, type ViewName } from '../state/nav'
import { useToast } from '../state/toast'
import { keys, useTaskData } from '../state/useTaskData'
import { Icon } from './icons'

function Item({ active, later, icon, onClick, children }: {
  active: boolean; later?: boolean; icon: Parameters<typeof Icon>[0]['name']; onClick: () => void; children: ReactNode
}) {
  return (
    <button type="button" className={`nav-item${active ? ' is-active' : ''}${later ? ' is-later' : ''}`} onClick={onClick}>
      <Icon name={icon} /> {children}
    </button>
  )
}

/** Prototype sidebar: explicit entries per agent (docs/architecture/system.md), recent sessions, footer. */
export function Sidebar() {
  const api = useApi()
  const toast = useToast()
  const { nav, go, openTask, openDrawer } = useNav()
  const { user, logout } = useAuth()
  const tasks = useQuery({ queryKey: keys.tasks, queryFn: () => api.listTasks() })
  const me = useQuery({ queryKey: keys.me, queryFn: () => api.me() })
  const { task, timeline, artifacts } = useTaskData(nav.taskId)

  const is = (view: ViewName, agent?: string) => nav.view === view && (agent === undefined || nav.agent === agent)
  const to = (patch: Partial<NavState>) => () => go({ productId: null, toolName: null, skillId: null, ...patch })
  const newChat = (agent: string) => to({ view: 'chat', agent, taskId: null, drawer: null, target: null })
  const lastSteps = timeline.data?.at(-1)?.steps.map((s) => s.tool).join(' → ')

  const exportSnapshot = () => {
    if (!task.data) { toast('先打开一个任务'); return }
    const blob = new Blob([JSON.stringify({ task: task.data, timeline: timeline.data, artifacts: artifacts.data }, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `task-${task.data.id}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <nav className="sidebar" aria-label="主导航">
      <div className="sidebar-brand">
        <button type="button" className="sidebar-brand-btn" aria-label="Home 主页" onClick={to({ view: 'home' })}>
          <span className="brand-mark" aria-hidden="true">AI</span><span>电商 AI</span>
        </button>
        <div className="sidebar-icon-actions">
          <button type="button" className="sidebar-icon-btn" title="新建会话" aria-label="新建会话" onClick={newChat(nav.view === 'chat' ? nav.agent : 'general')}><Icon name="plus" size={18} /></button>
          <button type="button" className="sidebar-icon-btn" title="主页" aria-label="主页" onClick={to({ view: 'home' })}><Icon name="home" size={18} /></button>
        </div>
      </div>
      <div className="sidebar-nav-scroll">
        <div className="nav-group">
          <div className="nav-group-label">通用</div>
          <Item active={is('chat', 'general')} icon="chat" onClick={newChat('general')}>通用 Agent</Item>
        </div>
        <div className="nav-group">
          <div className="nav-group-label">专用 Agent</div>
          <Item active={is('chat', 'amazon_pdp')} icon="pdp" onClick={newChat('amazon_pdp')}>PDP Agent</Item>
          <Item active={is('image')} icon="image" onClick={() => go({ view: 'image', agent: 'image', imageTaskId: null, imageSlot: null, taskId: null, bootText: null, drawer: null })}>图片 Agent</Item>
          <Item active={is('canvas')} icon="canvas" onClick={() => go({ view: 'canvas', agent: 'canvas', canvasTaskId: null, taskId: null, bootText: null, drawer: null })}>画布 Agent</Item>
        </div>
        <div className="nav-group">
          <div className="nav-group-label">任务</div>
          <Item active={is('history')} icon="history" onClick={to({ view: 'history' })}>任务列表</Item>
          <Item active={is('artifacts')} icon="artifacts" onClick={to({ view: 'artifacts' })}>Artifact</Item>
        </div>
        <div className="nav-group">
          <div className="nav-group-label">商品</div>
          <Item active={is('products')} icon="products" onClick={to({ view: 'products' })}>商品与事实</Item>
        </div>
        {isAdmin(user) && (
          <div className="nav-group">
            <div className="nav-group-label">管理员</div>
            <Item active={is('admin')} icon="products" onClick={to({ view: 'admin' })}>用户与积分</Item>
            <Item active={is('tools')} icon="tools" onClick={to({ view: 'tools' })}>Tool 登记</Item>
            <Item active={is('skills')} icon="skills" onClick={to({ view: 'skills' })}>Skill 登记</Item>
            <Item active={is('console')} icon="console" onClick={to({ view: 'console' })}>控制台</Item>
          </div>
        )}
        <div className="nav-group">
          <div className="nav-group-label">后期</div>
          <Item active={is('automation')} later icon="history" onClick={to({ view: 'automation' })}>自动化<span className="x-later-tag">后期</span></Item>
        </div>
      </div>
      <div className="sidebar-recent">
        <div className="sidebar-recent-label">最近</div>
        <div>
          {tasks.data?.slice(0, 8).map((t) => (
            <button key={t.id} type="button" className={`session-row${(t.id === nav.taskId && nav.view === 'chat') || (t.id === nav.imageTaskId && nav.view === 'image') || (t.id === nav.canvasTaskId && nav.view === 'canvas') ? ' is-active' : ''}`}
              onClick={() => t.kind === 'image'
                ? go({ view: 'image', agent: 'image', imageTaskId: t.id, imageSlot: 'image', bootText: null })
                : t.kind === 'canvas'
                  ? go({ view: 'canvas', agent: 'canvas', canvasTaskId: t.id, bootText: null })
                  : openTask(t.id, t.agent_key)}>{t.goal || '未命名任务'}</button>
          ))}
        </div>
      </div>
      <div className="sidebar-footer">
        <div className="select-wrap">
          <select aria-label="当前 Artifact" value="" disabled={!nav.taskId}
            onChange={(e) => {
              const v = e.target.value
              if (v === 'pdp') openDrawer({ kind: 'pdp' })
              else if (v.startsWith('file:')) openDrawer({ kind: 'file', slot: v.slice(5) })
              else if (v) openDrawer({ kind: 'image', slot: v })
              go({ view: 'chat' })
            }}>
            <option value="">当前任务成果</option>
            {task.data?.pdp_version_id && <option value="pdp">PDP · 当前版本</option>}
            {artifacts.data?.filter((a) => a.kind === 'file' && a.slot && a.current_version_id).map((a) => (
              <option key={a.artifact_id} value={`file:${a.slot}`}>{a.slot} · 预览</option>
            ))}
            {artifacts.data?.filter((a) => a.kind === 'image' && a.slot && a.current_version_id).map((a) => (
              <option key={a.artifact_id} value={a.slot as string}>{a.slot === 'main_image' ? '主图' : a.slot === 'image' ? '图片' : '副图'} · 当前版本</option>
            ))}
          </select>
        </div>
        <div className="sidebar-footer-actions">
          <button type="button" className="btn btn-secondary" onClick={exportSnapshot}>导出快照</button>
          <button type="button" className="btn btn-secondary" onClick={() => go({ view: 'account' })}>
            积分 {me.data?.credits ?? '—'}
          </button>
        </div>
        <div className="sidebar-account">
          <span className="sidebar-account-name" title={user?.display_name ?? ''}>
            {user?.display_name ?? ''}
            {isAdmin(user) && <span className="x-later-tag">Admin</span>}
          </span>
          <button type="button" className="sidebar-logout" onClick={() => void logout()}>退出</button>
        </div>
        <p className="session-trace-mini">tools: {lastSteps || '—'}</p>
      </div>
    </nav>
  )
}
