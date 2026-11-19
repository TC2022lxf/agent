import { useState } from 'react'
import { AgentHome } from '../components/chat/AgentHome'
import { useApi } from '../state/api-context'
import { useNav } from '../state/nav'
import { useToast } from '../state/toast'

/** Image agent entry: templates sit above the centered chat box. */
export function ImageHome() {
  const api = useApi()
  const toast = useToast()
  const { go } = useNav()
  const [pending, setPending] = useState(false)

  const start = async (text: string, file?: File | null) => {
    setPending(true)
    try {
      const upload = file ? await api.upload(file) : null
      const task = await api.createTask({
        agent_id: 'image', kind: 'image', goal: text.slice(0, 80), upload_id: upload?.upload_id,
      })
      go({ view: 'image', agent: 'image', imageTaskId: task.id, imageSlot: 'image', bootText: text, taskId: null })
    } catch (e) {
      toast(e instanceof Error ? e.message : '创建失败')
      setPending(false)
    }
  }

  return (
    <section className="view is-active">
      <AgentHome mode="image" title="图片 Agent" lede="选一个模板，或直接描述你要的图。圈选在画布里进行。"
        placeholder="描述你要的图片" pending={pending}
        onText={(text) => void start(text)}
        onPdp={() => undefined}
        onImage={(text, file) => void start(text, file)} />
    </section>
  )
}
