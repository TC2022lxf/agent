import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type {
  AdminConfig,
  AgentConfig,
  ModelProfileView,
} from '../api/types'
import { useApi } from '../state/api-context'
import { useToast } from '../state/toast'

function AgentEditor({ agent }: { agent: AgentConfig }) {
  const api = useApi()
  const toast = useToast()
  const qc = useQueryClient()
  const [model, setModel] = useState(agent.model)
  const [prompt, setPrompt] = useState(agent.system_prompt)
  useEffect(() => { setModel(agent.model); setPrompt(agent.system_prompt) }, [agent.model, agent.system_prompt])
  const save = useMutation({
    mutationFn: () => api.saveAgentConfig(agent.key, { model, system_prompt: prompt }),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['admin-config'] }); toast('已保存') },
    onError: (e) => toast(e instanceof Error ? e.message : '保存失败'),
  })
  return (
    <div className="console-agent schema-block">
      <div className="schema-block-head"><span>{agent.title}</span><span className="mono">{agent.key}</span></div>
      <div className="field"><label htmlFor={`model-${agent.key}`}>主模型</label>
        <input id={`model-${agent.key}`} value={model} onChange={(e) => setModel(e.target.value)} />
      </div>
      <div className="field"><label htmlFor={`prompt-${agent.key}`}>系统提示词</label>
        <textarea id={`prompt-${agent.key}`} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </div>
      <p className="x-note">可用变量：{agent.variables.join('、')}。下一轮 Run 会读取这份正文。主模型填模型档案的 key。</p>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{agent.preview}</pre>
      <button type="button" className="btn btn-teal btn-sm" disabled={save.isPending} onClick={() => save.mutate()}>保存</button>
    </div>
  )
}

/** One model profile: upstream name, context window, enabled. The window drives compaction. */
function ProfileRow({ profile, isImage }: { profile: ModelProfileView; isImage: boolean }) {
  const api = useApi()
  const toast = useToast()
  const qc = useQueryClient()
  const [upstream, setUpstream] = useState(profile.upstream_model)
  const [window, setWindow] = useState(String(profile.context_window_tokens))
  useEffect(() => {
    setUpstream(profile.upstream_model)
    setWindow(String(profile.context_window_tokens))
  }, [profile.upstream_model, profile.context_window_tokens])
  const save = useMutation({
    mutationFn: () => api.saveModelProfile(profile.key, {
      upstream_model: upstream.trim() || profile.upstream_model,
      context_window_tokens: Number(window) || 0,
    }),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['admin-config'] }); toast('已保存') },
    onError: (e) => toast(e instanceof Error ? e.message : '保存失败'),
  })
  return (
    <tr>
      <td className="mono">{profile.key}{isImage ? ' · 图像' : ''}</td>
      <td><input aria-label={`${profile.key} 上游模型`} value={upstream} onChange={(e) => setUpstream(e.target.value)} style={{ width: 180 }} /></td>
      <td>{profile.kind}</td>
      <td><input aria-label={`${profile.key} 上下文窗口`} value={window} onChange={(e) => setWindow(e.target.value)} style={{ width: 110 }} inputMode="numeric" /></td>
      <td>{profile.enabled ? '启用' : '停用'}</td>
      <td><button type="button" className="btn btn-teal btn-sm" disabled={save.isPending} onClick={() => save.mutate()}>保存</button></td>
    </tr>
  )
}

/** Compaction thresholds. Read by the next Run; a fraction of the bound model's window. */
function RuntimeForm({ runtime }: { runtime: NonNullable<AdminConfig['runtime']> }) {
  const api = useApi()
  const toast = useToast()
  const qc = useQueryClient()
  const [fraction, setFraction] = useState(String(runtime.summary_fraction))
  const [keep, setKeep] = useState(String(runtime.summary_keep))
  const [calls, setCalls] = useState(String(runtime.max_tool_calls))
  useEffect(() => {
    setFraction(String(runtime.summary_fraction))
    setKeep(String(runtime.summary_keep))
    setCalls(String(runtime.max_tool_calls))
  }, [runtime.summary_fraction, runtime.summary_keep, runtime.max_tool_calls])
  const save = useMutation({
    mutationFn: () => api.saveRuntime({
      summary_fraction: Number(fraction),
      summary_keep: Number(keep),
      max_tool_calls: Number(calls),
    }),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['admin-config'] }); toast('已保存') },
    onError: (e) => toast(e instanceof Error ? e.message : '保存失败'),
  })
  return (
    <div className="console-agent schema-block">
      <div className="schema-block-head"><span>运行时</span></div>
      <div className="field"><label htmlFor="rt-fraction">摘要阈值（占模型窗口的比例）</label>
        <input id="rt-fraction" value={fraction} onChange={(e) => setFraction(e.target.value)} inputMode="decimal" />
      </div>
      <div className="field"><label htmlFor="rt-keep">保留最近多少轮原文</label>
        <input id="rt-keep" value={keep} onChange={(e) => setKeep(e.target.value)} inputMode="numeric" />
      </div>
      <div className="field"><label htmlFor="rt-calls">单轮工具调用上限</label>
        <input id="rt-calls" value={calls} onChange={(e) => setCalls(e.target.value)} inputMode="numeric" />
      </div>
      <p className="x-note">
        阈值按每个模型档案自己的上下文窗口计算，换模型即换阈值。达到比例后，较早的回合被压缩成摘要，
        最近若干轮原文保留。摘要调用失败不阻断本轮。
      </p>
      <button type="button" className="btn btn-teal btn-sm" disabled={save.isPending} onClick={() => save.mutate()}>保存</button>
    </div>
  )
}

/** Admin console: process settings (read-only), agent prompt/model, and call logs. */
export function ConsoleView() {
  const api = useApi()
  const config = useQuery({ queryKey: ['admin-config'], queryFn: () => api.adminConfig() })
  const logs = useQuery({ queryKey: ['admin-logs'], queryFn: () => api.adminLogs() })
  return (
    <section className="view is-active">
      <div className="panel-body">
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 8px' }}>控制台</h1>
        {config.data && <div className="x-banner">{config.data.note}</div>}
        <div className="console-grid">
          <dl className="product-detail-meta">
            {config.data?.env.map((row) => (
              <div key={row.key}><dt>{row.key}</dt><dd>{row.value}{row.editable ? '' : ' · 在 .env 里改'}</dd></div>
            ))}
          </dl>
          {config.data?.agents.map((a) => <AgentEditor key={a.key} agent={a} />)}
          {(config.data?.profiles ?? []).length > 0 && (
            <>
              <h2 className="x-h2">模型档案</h2>
              <p className="x-note">上下文窗口决定何时压缩对话。换绑一个模型时，把它的真实窗口改对，摘要才会在预期的时候发生。</p>
              <table className="console-log">
                <thead><tr><th>key</th><th>上游</th><th>类型</th><th>窗口（token）</th><th>状态</th><th /></tr></thead>
                <tbody>
                  {config.data?.profiles?.map((p) => (
                    <ProfileRow key={p.key} profile={p} isImage={config.data?.image_profile === p.key} />
                  ))}
                </tbody>
              </table>
            </>
          )}
          {config.data?.runtime && <RuntimeForm runtime={config.data.runtime} />}
          <h2 className="x-h2">调用日志</h2>
          <table className="console-log">
            <thead><tr><th>Tool</th><th>状态</th><th>耗时</th><th>积分</th><th>Run</th></tr></thead>
            <tbody>
              {logs.data?.tool_calls.map((row) => (
                <tr key={row.id}><td>{row.tool}</td><td>{row.status}</td><td>{row.duration_ms}ms</td><td>{row.cost}</td><td className="mono">{row.run_id}</td></tr>
              ))}
              {logs.data?.llm_calls.map((row) => (
                <tr key={`l${row.id}`}><td>llm · {row.alias}</td><td>{row.status}</td><td>{row.duration_ms}ms</td><td></td><td className="mono">{row.run_id ?? ''}</td></tr>
              ))}
            </tbody>
          </table>
          {logs.data && logs.data.tool_calls.length === 0 && logs.data.llm_calls.length === 0 && <p className="x-ghost">还没有调用。</p>}
        </div>
      </div>
    </section>
  )
}
