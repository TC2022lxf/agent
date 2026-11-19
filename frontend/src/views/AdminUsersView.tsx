import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { AdminUser, TopupOrder } from '../api/types'
import { useApi } from '../state/api-context'
import { useToast } from '../state/toast'

const yuan = (fen: number) => (fen / 100).toFixed(2)
const when = (iso: string | null) => (iso ? iso.slice(5, 16).replace('T', ' ') : '—')

/** Give or take credits. A reason is mandatory: the audit log is the only explanation later. */
function CreditRow({ user }: { user: AdminUser }) {
  const api = useApi()
  const toast = useToast()
  const qc = useQueryClient()
  const [amount, setAmount] = useState('100')
  const [reason, setReason] = useState('内测发放')
  const grant = useMutation({
    mutationFn: () => api.grantCredits(user.id, Number(amount) || 0, reason),
    onSuccess: async (r) => {
      toast(`已发放，余额 ${r.balance}`)
      await qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
    onError: (e) => toast(e instanceof Error ? e.message : '发放失败'),
  })
  const adjust = useMutation({
    mutationFn: () => api.adjustCredits(user.id, -(Number(amount) || 0), reason),
    onSuccess: async (r) => {
      toast(`已扣减，余额 ${r.balance}`)
      await qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
    onError: (e) => toast(e instanceof Error ? e.message : '扣减失败'),
  })
  return (
    <div className="admin-credit-row">
      <input
        aria-label={`${user.display_name} 数量`}
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        inputMode="numeric"
        style={{ width: 80 }}
      />
      <input
        aria-label={`${user.display_name} 原因`}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="原因（必填）"
        style={{ width: 180 }}
      />
      <button
        type="button"
        className="btn btn-teal btn-sm"
        disabled={grant.isPending || !reason.trim() || !Number(amount)}
        onClick={() => grant.mutate()}
      >
        发放
      </button>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        disabled={adjust.isPending || !reason.trim() || !Number(amount)}
        onClick={() => adjust.mutate()}
      >
        扣减
      </button>
    </div>
  )
}

function UserRow({ user }: { user: AdminUser }) {
  const api = useApi()
  const toast = useToast()
  const qc = useQueryClient()
  const [issued, setIssued] = useState<string | null>(null)
  const toggle = useMutation({
    mutationFn: () => api.setUserStatus(user.id, user.status === 'active' ? 'disabled' : 'active'),
    onSuccess: async (u) => {
      toast(u.status === 'active' ? '已启用' : '已停用（会话已失效）')
      await qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
  })
  const rotate = useMutation({
    mutationFn: () => api.rotateUserKey(user.id),
    onSuccess: (r) => setIssued(r.access_key),
  })
  return (
    <tr>
      <td>{user.display_name}</td>
      <td>{user.role === 'admin' ? '管理员' : '用户'}</td>
      <td>{user.status === 'active' ? '正常' : '已停用'}</td>
      <td className="mono">{user.balance}</td>
      <td className="mono">{when(user.created_at)}</td>
      <td className="mono">{when(user.last_login_at)}</td>
      <td>
        <CreditRow user={user} />
        <div className="admin-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={toggle.isPending}
            onClick={() => toggle.mutate()}
          >
            {user.status === 'active' ? '停用' : '启用'}
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={rotate.isPending}
            onClick={() => rotate.mutate()}
          >
            重置密钥
          </button>
        </div>
        {issued && (
          <p className="admin-issued">
            新密钥（只显示一次）：<code>{issued}</code>
          </p>
        )}
      </td>
    </tr>
  )
}

function InvitePanel() {
  const api = useApi()
  const toast = useToast()
  const qc = useQueryClient()
  const invites = useQuery({ queryKey: ['admin-invites'], queryFn: () => api.adminInvites() })
  const [uses, setUses] = useState('3')
  const [issued, setIssued] = useState<string | null>(null)
  const create = useMutation({
    mutationFn: () => api.createInvite({ max_uses: Number(uses) || 1, days: 30 }),
    onSuccess: async (r) => {
      setIssued(r.code)
      await qc.invalidateQueries({ queryKey: ['admin-invites'] })
    },
  })
  const revoke = useMutation({
    mutationFn: (id: string) => api.revokeInvite(id),
    onSuccess: async () => {
      toast('已撤销')
      await qc.invalidateQueries({ queryKey: ['admin-invites'] })
    },
  })
  return (
    <div className="schema-block">
      <div className="schema-block-head"><span>邀请码</span></div>
      <p className="x-note">内测阶段注册需要邀请码。码只显示一次，库里只有哈希。</p>
      <div className="admin-invite-form">
        <label htmlFor="invite-uses">可用次数</label>
        <input
          id="invite-uses"
          value={uses}
          onChange={(e) => setUses(e.target.value)}
          inputMode="numeric"
          style={{ width: 80 }}
        />
        <button
          type="button"
          className="btn btn-teal btn-sm"
          disabled={create.isPending}
          onClick={() => create.mutate()}
        >
          生成邀请码
        </button>
      </div>
      {issued && (
        <p className="admin-issued">
          新邀请码（只显示一次）：<code data-testid="invite-code">{issued}</code>
        </p>
      )}
      <table className="console-log">
        <thead>
          <tr><th>编号</th><th>已用</th><th>状态</th><th>有效期</th><th /></tr>
        </thead>
        <tbody>
          {invites.data?.map((i) => (
            <tr key={i.id}>
              <td className="mono">{i.id}</td>
              <td>{i.used_count} / {i.max_uses}</td>
              <td>{i.revoked ? '已撤销' : i.used_count >= i.max_uses ? '已用完' : '可用'}</td>
              <td className="mono">{when(i.expires_at)}</td>
              <td>
                {!i.revoked && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => revoke.mutate(i.id)}
                  >
                    撤销
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {invites.data?.length === 0 && <p className="x-ghost">还没有邀请码。</p>}
    </div>
  )
}

function TopupQueue() {
  const api = useApi()
  const toast = useToast()
  const qc = useQueryClient()
  const topups = useQuery({ queryKey: ['admin-topups'], queryFn: () => api.adminTopups() })
  const confirm = useMutation({
    mutationFn: (id: string) => api.confirmTopup(id),
    onSuccess: async (o) => {
      toast(`已确认，${o.user_id} 余额 ${o.balance}`)
      await qc.invalidateQueries({ queryKey: ['admin-topups'] })
      await qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
  })
  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelTopup(id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['admin-topups'] })
    },
  })
  const pending = (topups.data ?? []).filter((t: TopupOrder) => t.status === 'pending')
  return (
    <div className="schema-block">
      <div className="schema-block-head"><span>待确认充值</span></div>
      {pending.length === 0 && <p className="x-ghost">没有待确认的订单。</p>}
      {pending.length > 0 && (
        <table className="console-log">
          <thead><tr><th>订单</th><th>用户</th><th>金额</th><th>积分</th><th /></tr></thead>
          <tbody>
            {pending.map((o) => (
              <tr key={o.id}>
                <td className="mono">{o.id}</td>
                <td className="mono">{o.user_id}</td>
                <td>{yuan(o.amount_cents)} 元</td>
                <td>{o.credits}</td>
                <td>
                  <button type="button" className="btn btn-teal btn-sm"
                    onClick={() => confirm.mutate(o.id)}>确认收款</button>
                  <button type="button" className="btn btn-secondary btn-sm"
                    onClick={() => cancel.mutate(o.id)}>取消</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/** `/admin/users`: who exists, their balance, invites, and pending recharges (docs/architecture/agent-runtime.md). */
export function AdminUsersView() {
  const api = useApi()
  const users = useQuery({ queryKey: ['admin-users'], queryFn: () => api.adminUsers() })
  const audit = useQuery({ queryKey: ['admin-audit'], queryFn: () => api.auditLogs() })

  return (
    <section className="view is-active">
      <div className="panel-body">
        <h1 className="acct-title">用户与积分</h1>
        <p className="x-note">
          发放和调整都必须写原因，写进审计。停用会立刻让该用户的所有会话失效。
          重置密钥会返回新密钥，只显示一次。
        </p>
        <table className="console-log" data-testid="admin-users">
          <thead>
            <tr><th>名字</th><th>角色</th><th>状态</th><th>余额</th><th>注册</th><th>最近登录</th><th>操作</th></tr>
          </thead>
          <tbody>
            {users.data?.map((u) => <UserRow key={u.id} user={u} />)}
          </tbody>
        </table>
        {users.data?.length === 0 && <p className="x-ghost">还没有别的用户。</p>}

        <InvitePanel />
        <TopupQueue />

        <h2 className="x-h2">审计</h2>
        <table className="console-log">
          <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>说明</th></tr></thead>
          <tbody>
            {audit.data?.map((a) => (
              <tr key={a.id}>
                <td className="mono">{when(a.created_at)}</td>
                <td className="mono">{a.actor_id}</td>
                <td>{a.action}</td>
                <td className="mono">{a.target_id}</td>
                <td className="mono">{JSON.stringify(a.detail)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {audit.data?.length === 0 && <p className="x-ghost">还没有审计记录。</p>}
      </div>
    </section>
  )
}
