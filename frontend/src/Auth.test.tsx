import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AdminUser, LedgerRow, TopupOrder } from './api/types'
import { AUTH_ANON, anonApi, fakeApi, renderApp } from './test-utils'

const LEDGER: LedgerRow[] = [
  { id: 3, delta: -20, kind: 'settle', run_id: 'run_1', balance_after: 980, note: '结算：实扣 20', created_at: '2026-10-29T10:00:00Z' },
  { id: 2, delta: -120, kind: 'hold', run_id: 'run_1', balance_after: 1000, note: 'Run 预算冻结', created_at: '2026-10-29T10:00:00Z' },
  { id: 1, delta: 1120, kind: 'grant', run_id: null, balance_after: 1120, note: '注册赠送', created_at: '2026-10-29T09:00:00Z' },
]

const PENDING: TopupOrder[] = [{
  id: 'top_1', user_id: 'u', amount_cents: 3000, amount_yuan: 30, credits: 3000,
  method: 'manual', status: 'pending', note: '', created_at: '2026-10-29T10:00:00Z', paid_at: null,
}]

const USERS: AdminUser[] = [
  { id: 'u1', display_name: '运营小王', role: 'user', status: 'active', invite_id: 'inv1', created_at: '2026-10-01T09:00:00Z', last_login_at: null, balance: 980 },
  { id: 'u2', display_name: 'boss', role: 'admin', status: 'active', invite_id: null, created_at: '2026-09-01T09:00:00Z', last_login_at: '2026-10-29T08:00:00Z', balance: 5000 },
]

describe('sign-in gate', () => {
  it('shows the login form when there is no session', async () => {
    renderApp(anonApi(), {}, { auth: AUTH_ANON })
    expect(await screen.findByRole('heading', { name: '登录' })).toBeTruthy()
    // The workbench is not reachable at all.
    expect(screen.queryByRole('button', { name: '通用 Agent' })).toBeNull()
  })

  it('switches to invite signup and shows the key exactly once', async () => {
    const register = vi.fn(async () => ({
      access_key: 'ek_once_only_value',
      user: { id: 'u', display_name: 'newbie', role: 'user' as const },
    }))
    renderApp(anonApi({ register }), {}, { auth: AUTH_ANON })
    fireEvent.click(await screen.findByRole('button', { name: /我有邀请码/ }))

    fireEvent.change(screen.getByLabelText('名字'), { target: { value: 'newbie' } })
    fireEvent.change(screen.getByLabelText('邀请码'), { target: { value: 'iv_abc' } })
    fireEvent.click(screen.getByRole('button', { name: '注册' }))

    await waitFor(() =>
      expect(register).toHaveBeenCalledWith({ display_name: 'newbie', invite_code: 'iv_abc' }))
    const shown = await screen.findByTestId('issued-key')
    expect(shown.textContent).toBe('ek_once_only_value')
    // Continuing is blocked until the user confirms they saved it.
    const go = screen.getByRole('button', { name: '我已保存，去登录' }) as HTMLButtonElement
    expect(go.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('我已经把密钥保存到安全的地方'))
    await waitFor(() => expect(go.disabled).toBe(false))
  })

  it('shows the server sentence when login fails', async () => {
    const login = vi.fn(async () => {
      throw Object.assign(new Error('名字或访问密钥不正确'), { status: 401, code: 'BAD_CREDENTIALS' })
    })
    renderApp(anonApi({ login }), {}, { auth: AUTH_ANON })
    fireEvent.change(await screen.findByLabelText('名字'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('访问密钥'), { target: { value: 'ek_wrong' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent', '名字或访问密钥不正确',
    )
  })
})

describe('account page', () => {
  it('shows balance, frozen credits and the ledger in time order', async () => {
    renderApp(
      fakeApi({
        me: async () => ({ user_id: 'u', display_name: '运营小王', role: 'user', credits: 980, held: 0 }),
        ledger: async () => LEDGER,
        topups: async () => [],
      }),
      { view: 'account' },
    )
    await waitFor(() =>
      expect(screen.getByTestId('balance').textContent).toBe('980'))
    const rows = within(await screen.findByTestId('ledger')).getAllByRole('row')
    // Header + three entries, newest first.
    expect(rows).toHaveLength(4)
    expect(rows[1]?.textContent).toContain('结算')
    expect(rows[3]?.textContent).toContain('注册赠送')
  })

  it('creates a topup order without claiming the credits arrived', async () => {
    const createTopup = vi.fn(async (cents: number) => ({
      id: 'top_9', user_id: 'u', amount_cents: cents, amount_yuan: cents / 100, credits: cents,
      method: 'manual', status: 'pending' as const, note: '',
      created_at: '2026-10-29T10:00:00Z', paid_at: null,
    }))
    renderApp(fakeApi({ createTopup, ledger: async () => [], topups: async () => [] }), {
      view: 'account',
    })
    fireEvent.click(await screen.findByRole('button', { name: '50.00 元' }))
    fireEvent.click(screen.getByRole('button', { name: '创建充值订单' }))
    await waitFor(() => expect(createTopup).toHaveBeenCalledWith(5000))
    // The money is not shown as arrived: the order is pending until an admin confirms.
    expect(await screen.findByText(/待确认|已创建充值订单/)).toBeTruthy()
  })
})

describe('admin users page', () => {
  it('lists users with balances and posts a grant with a reason', async () => {
    const grantCredits = vi.fn(async () => ({ balance: 1080 }))
    renderApp(
      fakeApi({ adminUsers: async () => USERS, grantCredits, auditLogs: async () => [] }),
      { view: 'admin' },
    )
    expect(await screen.findByText('运营小王')).toBeTruthy()
    const table = screen.getByTestId('admin-users')
    expect(table.textContent).toContain('980')

    const amount = screen.getByLabelText('运营小王 数量')
    fireEvent.change(amount, { target: { value: '100' } })
    const grants = screen.getAllByRole('button', { name: '发放' })
    fireEvent.click(grants[0]!)
    await waitFor(() => expect(grantCredits).toHaveBeenCalledWith('u1', 100, '内测发放'))
  })

  it('confirms a pending recharge from the queue', async () => {
    const paid: TopupOrder = {
      ...PENDING[0]!, status: 'paid', paid_at: '2026-10-29T11:00:00Z', balance: 3980,
    }
    const confirmTopup = vi.fn(async () => paid)
    renderApp(
      fakeApi({
        adminUsers: async () => USERS,
        adminTopups: async () => PENDING,
        confirmTopup,
        auditLogs: async () => [],
      }),
      { view: 'admin' },
    )
    fireEvent.click(await screen.findByRole('button', { name: '确认收款' }))
    await waitFor(() => expect(confirmTopup).toHaveBeenCalledWith('top_1'))
  })
})
