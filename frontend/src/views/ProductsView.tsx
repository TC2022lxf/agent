import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { TaskArtifacts } from '../components/TaskArtifacts'
import { useApi } from '../state/api-context'
import { useNav } from '../state/nav'
import { useToast } from '../state/toast'
import { keys } from '../state/useTaskData'

export function ProductsView() {
  const api = useApi()
  const qc = useQueryClient()
  const toast = useToast()
  const { nav, go } = useNav()
  const products = useQuery({ queryKey: keys.products, queryFn: () => api.products() })
  const detail = useQuery({
    queryKey: ['product', nav.productId], enabled: !!nav.productId,
    queryFn: () => api.product(nav.productId as string),
  })
  const samples = useMutation({
    mutationFn: () => api.loadSamples(),
    onSuccess: async (ps) => { await qc.invalidateQueries({ queryKey: keys.products }); toast(`已加载 ${ps.length} 个样例商品`) },
  })

  if (nav.productId) {
    const p = detail.data
    const meta: [string, string][] = p ? [
      ['品牌', p.brand], ['站点', p.marketplace], ['价格', p.facts.price_text ?? '—'],
      ['评分', p.facts.rating ? `${p.facts.rating.stars} · ${p.facts.rating.ratings} 条` : '—'],
      ['类目', p.facts.category_path?.join(' › ') ?? '—'], ['模式', p.mode === 'optimize' ? '导入优化' : '从零生成'],
    ] : []
    return (
      <section className="view is-active">
        <div className="panel-body">
          <button type="button" className="back-link" onClick={() => go({ productId: null })}>← 返回商品列表</button>
          <h1 style={{ fontSize: 20, fontWeight: 600, margin: '0 0 4px' }}>{p?.name ?? '商品详情'}</h1>
          <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--muted)' }}>
            Agent 只能使用这里的事实和你补充的事实。
          </p>
          {p && (
            <>
              <dl className="product-detail-meta">
                {meta.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
              </dl>
              {p.facts.attributes && Object.keys(p.facts.attributes).length > 0 && (
                <>
                  <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 10px' }}>属性事实</h2>
                  <dl className="product-detail-meta">
                    {Object.entries(p.facts.attributes).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
                  </dl>
                </>
              )}
              <div style={{ display: 'flex', gap: 8, margin: '4px 0 18px' }}>
                <button type="button" className="btn btn-teal btn-sm"
                  onClick={() => go({ view: 'chat', agent: 'amazon_pdp', taskId: null, drawer: null, target: null })}>
                  {p.mode === 'optimize' ? '导入优化' : '做一个 PDP'}
                </button>
              </div>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>这个商品的任务</h2>
              {p.tasks?.length === 0 && <p className="x-ghost">还没有任务。</p>}
              {p.tasks?.map((t) => (
                <div key={t.id}><h3 className="x-h2">{t.goal || 'PDP'}</h3><TaskArtifacts task={t} /></div>
              ))}
            </>
          )}
        </div>
      </section>
    )
  }

  return (
    <section className="view is-active">
      <div className="panel-body">
        {products.data?.length === 0 && (
          <div className="x-banner"><b>还没有商品。</b>
            <button type="button" className="x-link" onClick={() => samples.mutate()}>加载样例商品</button>
          </div>
        )}
        <div className="product-grid">
          {products.data?.map((p) => (
            <button key={p.id} type="button" className="product-card" onClick={() => go({ productId: p.id })}>
              <div className="asin">品牌 {p.brand} · {p.marketplace}{p.facts.price_text ? ` · ${p.facts.price_text}` : ''}</div>
              <h3>{p.name}</h3>
              <div className="rc-meta"><span className="badge badge-planned">{p.mode === 'optimize' ? '导入优化' : '从零生成'}</span></div>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}
