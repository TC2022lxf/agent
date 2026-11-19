import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { STATUS_LABEL, fmtTime } from '../lib/labels'
import { useApi } from '../state/api-context'
import { useNav } from '../state/nav'
import { useToast } from '../state/toast'
import { keys } from '../state/useTaskData'

/**
 * Canvas Agent entry. This is a project list, not a picture preview: pick an existing
 * canvas task or start a blank one, then the workspace (CanvasView) opens.
 * The Image Agent's single-image preview stays on its own page.
 */
export function CanvasHome() {
  const api = useApi()
  const qc = useQueryClient()
  const toast = useToast()
  const { go } = useNav()
  const tasks = useQuery({ queryKey: keys.tasks, queryFn: () => api.listTasks() })
  const templates = useQuery({ queryKey: ['canvas-templates'], queryFn: () => api.canvasTemplates() })
  const [pending, setPending] = useState(false)
  const projects = (tasks.data ?? []).filter((t) => t.kind === 'canvas')

  const open = (id: string) =>
    go({ view: 'canvas', agent: 'canvas', canvasTaskId: id, bootText: null, taskId: null })

  const create = async () => {
    setPending(true)
    try {
      const created = await api.createTask({ agent_id: 'canvas', kind: 'canvas', goal: '未命名画布' })
      await qc.invalidateQueries({ queryKey: keys.tasks })
      open(created.id)
    } catch (e) {
      toast(e instanceof Error ? e.message : '创建失败')
      setPending(false)
    }
  }

  const fromTemplate = async (id: string) => {
    setPending(true)
    try {
      const created = await api.createCanvasFromTemplate(id)
      await qc.invalidateQueries({ queryKey: keys.tasks })
      open(created.id)
    } catch (e) {
      toast(e instanceof Error ? e.message : '打开模板失败')
      setPending(false)
    }
  }

  return (
    <section className="view is-active" data-testid="canvas-home">
      <div className="panel-body canvas-home">
        <h1>画布 Agent</h1>
        <p className="x-note">
          选一个已有画布，从一个带好图的模板开始，或新建一块空白画板。进去之后是整页工作台。
          图片 Agent 里的预览只看一张图，不是这块板。
        </p>
        {(templates.data?.length ?? 0) > 0 && (
          <>
            <h2 className="canvas-home-h">模板</h2>
            <div className="canvas-projects">
              {templates.data!.map((t) => (
                <button key={t.id} type="button" className="canvas-project is-template"
                  disabled={pending} onClick={() => void fromTemplate(t.id)}>
                  <span className="badge badge-version">模板</span>
                  <h3>{t.title}</h3>
                  <p>{t.blurb}</p>
                </button>
              ))}
            </div>
          </>
        )}
        <h2 className="canvas-home-h">我的画布</h2>
        <div className="canvas-projects">
          <button type="button" className="canvas-project is-new" disabled={pending} onClick={() => void create()}>
            <span className="badge badge-version">新建</span>
            <h3>新建画布</h3>
            <p>空白画板。进去之后在底部说一句要画的内容。</p>
          </button>
          {projects.map((t) => (
            <button key={t.id} type="button" className="canvas-project" onClick={() => open(t.id)}>
              <span className="badge badge-version">{t.canvas_version_id ? '已有画面' : '空白'}</span>
              <h3>{t.goal || '未命名画布'}</h3>
              <p>{STATUS_LABEL[t.status] ?? t.status} · {fmtTime(t.created_at)}</p>
            </button>
          ))}
        </div>
        {tasks.isSuccess && projects.length === 0 && (
          <p className="x-ghost">还没有画布项目。新建一块即可开始。</p>
        )}
      </div>
    </section>
  )
}
