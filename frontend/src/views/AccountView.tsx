import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { LedgerRow } from '../api/types'
import { useApi } from '../state/api-context'
import { useAuth } from '../state/auth'
import { useToast } from '../state/toast'
import { keys } from '../state/useTaskData'

const KIND_LABEL: Record<string, string> = {
  grant: '发放', topup: '充值', hold: '冻结', settle: '结算', refund: '退还',
  adjust: '调整', spend: '扣费',
}

const TOPUP_PRESETS = [1000, 3000, 5000, 10000] // fen

function yuan(fen: number): string {
  return (fen / 100).toFixed(2)
}

export function LedgerTable({ rows }: { rows: LedgerRow[] }) {
  if (rows.length === 0) return <p className="x-ghost">还没有积分流水。</p>
  return (
    <table className="console-log" data-testid="ledger">
      <thead>
        <tr><th>时间</th><th>类型</th><th>变动</th><th>余额</th><th>说明</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td className="mono">{r.created_at.slice(5, 16).replace('T', ' ')}</td>
            <td>{KIND_LABEL[r.kind] ?? r.kind}</td>
            <td className={r.delta < 0 ? 'is-minus' : 'is-plus'}>
              {r.delta > 0 ? `+${r.delta}` : r.delta}
            </td>
            <td className="mono">{r.balance_after}</td>
            <td className="mono">{r.note || r.run_id || ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Recharge. No provider is wired: the order is pending until an admin confirms it. */
function TopupForm() {
  const api = useApi()
  const toast = useToast()
  const qc = useQueryClient()
  const pricing = useQuery({ queryKey: ['pricing'], queryFn: () => api.pricing() })
  const [amount, setAmount] = useState(3000)
  const order = useMutation({
    mutationFn: () => api.createTopup(amount),
    onSuccess: async (o) => {
      toast(`已创建充值订单 ${o.id}，待确认`)
      await qc.invalidateQueries({ queryKey: ['topups'] })
    },
    onError: (e) => toast(e instanceof Error ? e.message : '创建订单失败'),
  })
  const min = pricing.data?.min_topup_cents ?? 100
  const max = pricing.data?.max_topup_cents ?? 100_000
  const disabled = pricing.data ? !pricing.data.topup_enabled : false

  return (
    <div className="schema-block">
      <div className="schema-block-head"><span>充值</span></div>
      <p className="x-note">
        1 积分 = 0.01 元。创建订单不会立刻加积分；收到款后由管理员确认，积分进账。
        重复确认同一个订单不会重复加。
      </p>
      <div className="topup-presets">
        {TOPUP_PRESETS.map((fen) => (
          <button
            key={fen}
            type="button"
            className={`btn btn-secondary btn-sm${amount === fen ? ' is-on' : ''}`}
            disabled={disabled || fen < min || fen > max}
            onClick={() => setAmount(fen)}
          >
            {yuan(fen)} 元
          </button>
        ))}
      </div>
      <div className="field">
        <label htmlFor="topup-amount">金额（元）</label>
        <input
          id="topup-amount"
          inputMode="decimal"
          value={yuan(amount)}
          onChange={(e) => setAmount(Math.round(Number(e.target.value || '0') * 100))}
        />
      </div>
      <p className="x-ghost">
        将获得 {amount} 积分。单次 {yuan(min)}–{yuan(max)} 元。
      </p>
      <button
        type="button"
        className="btn btn-teal btn-sm"
        disabled={disabled || order.isPending || amount < min || amount > max}
        onClick={() => order.mutate()}
      >
        {order.isPending ? '提交中…' : '创建充值订单'}
      </button>
      {disabled && <p className="x-ghost">充值暂未开放。</p>}
    </div>
  )
}

/** `/account`: balance, ledger, recharge orders. Replaces the old credits chip in the sidebar. */
export function AccountView() {
  const api = useApi()
  const { user } = useAuth()
  const me = useQuery({ queryKey: keys.me, queryFn: () => api.me() })
  const ledger = useQuery({ queryKey: ['ledger'], queryFn: () => api.ledger() })
  const topups = useQuery({ queryKey: ['topups'], queryFn: () => api.topups() })
  const pricing = useQuery({ queryKey: ['pricing'], queryFn: () => api.pricing() })

  const budgets = pricing.data?.budgets ?? {}
  return (
    <section className="view is-active">
      <div className="panel-body">
        <h1 className="acct-title">账户与积分</h1>
        <div className="acct-balance">
          <div>
            <span className="acct-balance-label">可用积分</span>
            <strong data-testid="balance">{me.data?.credits ?? '—'}</strong>
          </div>
          <div className="acct-balance-side">
            <span>冻结中</span>
            <strong>{me.data?.held ?? 0}</strong>
          </div>
          <div className="acct-balance-side">
            <span>余额（元）</span>
            <strong>{yuan(me.data?.credits ?? 0)}</strong>
          </div>
        </div>
        {user && (
          <dl className="product-detail-meta">
            <div><dt>名字</dt><dd>{user.display_name}</dd></div>
            <div><dt>角色</dt><dd>{user.role === 'admin' ? '管理员' : '用户'}</dd></div>
          </dl>
        )}
        <p className="x-note">
          每次发言会先冻结这次运行的预算，运行结束后只扣实际用量，剩下的自动退回。
          下面是各类任务当前的冻结额度。
        </p>
        <dl className="product-detail-meta">
          {Object.entries(budgets).map(([kind, credits]) => (
            <div key={kind}><dt>{kind}</dt><dd>{credits} 积分（{yuan(credits)} 元）</dd></div>
          ))}
        </dl>

        <TopupForm />

        <h2 className="x-h2">充值订单</h2>
        {topups.data?.length === 0 && <p className="x-ghost">还没有充值订单。</p>}
        {(topups.data?.length ?? 0) > 0 && (
          <table className="console-log">
            <thead><tr><th>订单</th><th>金额</th><th>积分</th><th>状态</th><th>时间</th></tr></thead>
            <tbody>
              {topups.data?.map((o) => (
                <tr key={o.id}>
                  <td className="mono">{o.id}</td>
                  <td>{yuan(o.amount_cents)} 元</td>
                  <td>{o.credits}</td>
                  <td>{o.status === 'paid' ? '已到账' : o.status === 'pending' ? '待确认' : '已取消'}</td>
                  <td className="mono">{o.created_at.slice(5, 16).replace('T', ' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h2 className="x-h2">积分流水</h2>
        <LedgerTable rows={ledger.data ?? []} />
      </div>
    </section>
  )
}
