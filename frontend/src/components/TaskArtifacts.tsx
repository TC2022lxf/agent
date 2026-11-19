import { useQuery } from '@tanstack/react-query'
import type { TaskView } from '../api/types'
import { currentVersion, pLabel, problemsOf, slotLabel, vLabel } from '../lib/labels'
import { useApi } from '../state/api-context'
import { useNav } from '../state/nav'
import { keys } from '../state/useTaskData'
import { FileCard, ImageCard, PdpCard } from './chat/ArtifactCards'
import { Tag } from './Tag'

/** The artifact cards of one task (artifact repository and product detail). */
export function TaskArtifacts({ task }: { task: TaskView }) {
  const api = useApi()
  const { openTask, openDrawer } = useNav()
  const arts = useQuery({ queryKey: keys.artifacts(task.id), queryFn: () => api.artifacts(task.id) })
  const open = (d: Parameters<typeof openDrawer>[0]) => { openTask(task.id, task.agent_key); openDrawer(d) }
  if (!arts.data) return <p className="x-ghost">加载中…</p>
  const pdp = arts.data.find((a) => a.kind === 'pdp')
  const pdpCur = currentVersion(pdp)
  const images = arts.data.filter((a) => a.kind === 'image' && a.current_version_id)
  const files = arts.data.filter((a) => a.kind === 'file' && a.current_version_id)
  if (!pdp && images.length === 0 && files.length === 0) return <p className="x-ghost">这个任务还没有成果。</p>
  return (
    <div className="artifact-grid">
      {pdp && pdpCur && (
        <PdpCard label={pLabel(pdpCur.seq)} title="PDP · 标题 · 五点 · 描述 · 主图"
          desc={task.meta.product ? '每个槽位各有版本，PDP 指向它们' : '每个槽位各有版本'}
          tags={<Tag cls="ok">当前</Tag>} onOpen={() => open({ kind: 'pdp' })} />
      )}
      {images.map((a) => {
        const v = currentVersion(a)
        if (!v || !a.slot) return null
        const rejected = a.versions.filter((x) => x.status === 'rejected').at(-1)
        const baseline = v.origin === 'imported' && problemsOf(v).length > 0
        return (
          <ImageCard key={a.artifact_id} thumb={v.content.url} typeLabel={slotLabel(a.slot)} version={vLabel(v.seq)}
            title={`${slotLabel(a.slot)} · ${v.origin === 'imported' ? '导入' : '当前'}`}
            desc={rejected ? `${vLabel(rejected.seq)} 曾被拒绝：${problemsOf(rejected)[0] ?? '未通过规则检查'}` : baseline ? '导入图存在基线问题，待核对' : '规则检查已自动运行'}
            tags={baseline ? <Tag cls="warn">基线问题</Tag> : <Tag cls="ok">当前</Tag>}
            onOpen={() => open({ kind: 'image', slot: a.slot ?? undefined })} />
        )
      })}
      {files.map((a) => {
        const v = currentVersion(a)
        if (!v || !a.slot) return null
        return (
          <FileCard key={a.artifact_id} name={a.slot} version={vLabel(v.seq)}
            title={a.slot} desc={v.content.media === 'html' ? 'HTML 预览' : '文件预览'}
            onOpen={() => open({ kind: 'file', slot: a.slot ?? undefined })} />
        )
      })}
    </div>
  )
}
