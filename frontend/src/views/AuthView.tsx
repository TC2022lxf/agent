import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { useApi } from '../state/api-context'
import { useAuth } from '../state/auth'

type Mode = 'login' | 'register'

/**
 * Sign in or sign up (docs/architecture/data-and-contracts.md section 2).
 *
 * Registration needs an invite code because the product is in invite-only beta. The access
 * key is shown exactly once and cannot be recovered: only its hash is stored, and support
 * can only issue a new one. That is why this screen refuses to continue until the user says
 * they saved it.
 */
export function AuthView() {
  const api = useApi()
  const { refresh, status } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [name, setName] = useState('')
  const [invite, setInvite] = useState('')
  const [key, setKey] = useState('')
  const [issuedKey, setIssuedKey] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const login = useMutation({
    mutationFn: () => api.login({ display_name: name.trim(), access_key: key.trim() }),
    onSuccess: () => refresh(),
  })
  const register = useMutation({
    mutationFn: () => api.register({ display_name: name.trim(), invite_code: invite.trim() }),
    onSuccess: (r) => setIssuedKey(r.access_key),
  })

  const error = (login.error ?? register.error) as ApiError | null
  const pending = login.isPending || register.isPending

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (mode === 'login') login.mutate()
    else register.mutate()
  }

  if (issuedKey) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <h1>账号已创建</h1>
          <p className="auth-lede">
            这是你的访问密钥。它只显示这一次，数据库里只保存哈希，我们无法找回。
            请先复制保存，再用它登录。
          </p>
          <pre className="auth-key" data-testid="issued-key">{issuedKey}</pre>
          <div className="auth-row">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => navigator.clipboard?.writeText(issuedKey)}
            >
              复制
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!saved}
              onClick={() => {
                setKey(issuedKey)
                setMode('login')
                setIssuedKey(null)
              }}
            >
              我已保存，去登录
            </button>
          </div>
          <label className="auth-check">
            <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
            我已经把密钥保存到安全的地方
          </label>
        </div>
      </div>
    )
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark" aria-hidden="true">AI</span>
          <span>电商 AI</span>
        </div>
        <h1>{mode === 'login' ? '登录' : '用邀请码注册'}</h1>
        <p className="auth-lede">
          {mode === 'login'
            ? '用名字和访问密钥登录。密钥丢失只能由管理员重置。'
            : '内测阶段需要邀请码。注册后会给你一个访问密钥，只显示一次。'}
        </p>

        <form onSubmit={submit} className="auth-form">
          <div className="field">
            <label htmlFor="auth-name">名字</label>
            <input
              id="auth-name"
              autoComplete="username"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              minLength={2}
              maxLength={40}
            />
          </div>
          {mode === 'login' ? (
            <div className="field">
              <label htmlFor="auth-key">访问密钥</label>
              <input
                id="auth-key"
                type="password"
                autoComplete="current-password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                required
                placeholder="ek_…"
              />
            </div>
          ) : (
            <div className="field">
              <label htmlFor="auth-invite">邀请码</label>
              <input
                id="auth-invite"
                value={invite}
                onChange={(e) => setInvite(e.target.value)}
                required
                placeholder="iv_…"
              />
            </div>
          )}

          {error && (
            <p className="auth-error" role="alert">
              {error.status === 402
                ? '积分不足，请联系管理员充值。'
                : error.message || '操作失败，请重试'}
            </p>
          )}

          <button type="submit" className="btn btn-primary auth-submit" disabled={pending}>
            {pending ? '处理中…' : mode === 'login' ? '登录' : '注册'}
          </button>
        </form>

        <button
          type="button"
          className="auth-switch"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            login.reset()
            register.reset()
          }}
        >
          {mode === 'login' ? '我有邀请码，去注册' : '已有账号，去登录'}
        </button>

        {status?.dev_identity && (
          <p className="auth-dev">
            当前是开发模式：没有会话时，后端接受请求头里的身份（<code>X-User-Id</code>），
            脚本和测试用它。生产环境把 <code>AUTH_MODE</code> 设为 <code>session</code>
            关掉它。
          </p>
        )}
      </div>
    </div>
  )
}
