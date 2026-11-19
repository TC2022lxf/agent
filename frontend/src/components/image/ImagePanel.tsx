import type { UtteranceBody } from '../../api/types'
import { ImageWorkbench } from './ImageWorkbench'
import { problemsOf, slotLabel, vLabel } from '../../lib/labels'
import { useNav } from '../../state/nav'
import { useTaskData } from '../../state/useTaskData'
import { Tag } from '../Tag'
import { checkLines } from '../pdp/model'

const PARAM_KEYS = ['operation', 'instruction', 'base_version_id', 'engine', 'prompt'] as const

/**
 * Image workbench as a drawer panel (prototype: x-imghead / x-imgwrap / x-params / 检查).
 * It only shows one slot's versions; editing with circles happens on the image page.
 */
export function ImagePanel({ taskId, slot, reasoning, onFeedback }: {
  taskId: string
  slot: string
  reasoning?: boolean
  onFeedback?: (body: UtteranceBody) => Promise<unknown> | void
}) {
  const { go } = useNav()
  const { artifacts, task } = useTaskData(taskId)
  const art = artifacts.data?.find((a) => a.slot === slot)
  if (!art) return <p className="x-ghost">加载中…</p>
  const cur = art.versions.find((v) => v.id === art.current_version_id)
  if (!cur) return null
  const prev = art.versions.filter((v) => v.id !== cur.id && v.status !== 'rejected').at(-1)
  const rej = art.versions.filter((v) => v.status === 'rejected').at(-1)
  const imported = cur.origin === 'imported'
  const lines = checkLines(cur, art.versions[0])
  const params = PARAM_KEYS.filter((k) => cur.params[k] !== undefined && cur.params[k] !== '')
  const baseSeq = (id: unknown) => art.versions.find((v) => v.id === id)?.seq

  return (
    <div>
      <div className="x-imghead">
        <b>{slotLabel(slot)} · {vLabel(cur.seq)}</b> <Tag cls="ok">当前</Tag>
        {imported && <Tag cls="imp">导入</Tag>}
        {imported && problemsOf(cur).length > 0 && <Tag cls="warn">基线问题</Tag>}
      </div>
      {onFeedback && (
        <ImageWorkbench
          variant="drawer"
          imageUrl={cur.content.url ?? ''}
          alt={`${slotLabel(slot)} ${vLabel(cur.seq)}`}
          versionId={cur.id}
          slot={slot}
          label={`${slotLabel(slot)} · ${vLabel(cur.seq)}`}
          reasoning={reasoning}
          onFeedback={onFeedback}
        />
      )}
      {!onFeedback && (
        <div className="x-imgwrap">
          <div className="x-main-frame"><img className="x-fit" src={cur.content.url} alt={`${slotLabel(slot)} ${vLabel(cur.seq)}`} /></div>
        </div>
      )}
      {params.length > 0 ? (
        <>
          <div className="x-params">
            {params.map((k) => (
              <div key={k}>
                <span>{k}</span>
                <b>{k === 'base_version_id' ? (baseSeq(cur.params[k]) ? vLabel(baseSeq(cur.params[k]) as number) : '—') : String(cur.params[k])}</b>
                {k === 'operation' && prev && <i>← {vLabel(prev.seq)}</i>}
              </div>
            ))}
          </div>
          <p className="x-note">未出现在参数里的字段沿用上一版。第二版起只通过 edit_product_image 修改，不会整张重抽。</p>
        </>
      ) : (
        <p className="x-note">导入的图片没有工具参数。第一次编辑会走 edit_product_image，并以这一版为 base_version_id。</p>
      )}
      {rej && (
        <div className="x-rejbox">
          <b>{vLabel(rej.seq)} 被拒绝</b><br />
          {problemsOf(rej).join('；') || '未通过规则检查'}。预览仍是 {vLabel(cur.seq)}。
          <div className="x-rejprev">
            <span>被拒绝版本（只能在检查里查看）</span>
            <div className="x-main-frame"><img className="x-fit" src={rej.content.url} alt={`${vLabel(rej.seq)} 被拒绝`} /></div>
          </div>
        </div>
      )}
      <div className="x-block">
        <h4>检查</h4>
        {lines.length === 0 ? <p className="x-ghost">这个槽位没有适用的检查。</p> : (
          <ul className="x-checks">
            {lines.map((c) => (
              <li key={c.code} className={`x-check ${c.ok ? 'ok' : 'bad'}`}>
                <span className="x-mark">{c.ok ? '通过' : '未通过'}</span>
                <div>
                  <div className="x-code">{c.code} <span className="x-kind">规则</span>{c.baseline && <Tag cls="warn">基线问题</Tag>}{c.fixed && <Tag cls="ok">已解决</Tag>}</div>
                  <div className="x-msg">{c.message}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="x-focus-row">
        <button type="button" className="btn btn-teal btn-sm"
          onClick={() => go({ view: 'image', imageTaskId: taskId, imageSlot: slot })}>
          聚焦{slotLabel(slot)}
        </button>
        <span className="x-sub">
          在轻画布里圈选局部（Mark），每个圈选成为一条带区域的反馈。
          {task.data?.kind === 'pdp' ? `改动会产生新的 ${slotLabel(slot)} 版本和新的 PDP 版本。` : ''}
        </span>
      </div>
    </div>
  )
}
