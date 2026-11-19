import { useRef } from 'react'
import type { HumanInputRequest } from '../../api/types'
import { humanInputOptionLabels } from '../../lib/humanInput'
import { AnswerOptions } from './AnswerOptions'

/**
 * Shown in the thread when the Run emitted `human_input_request`. Not assistant chat prose —
 * an interaction surface (deer-flow / Manus pattern).
 *
 * Three shapes, because the Agent asks for three different things:
 * - `single_choice`: reply buttons.
 * - `text`: a free-text box.
 * - `upload`: a file picker. A picture the Agent needs cannot be described in a text box, and
 *   the composer already uploads, so the panel only has to hand the file over.
 */
export function HumanInputPanel({
  request,
  disabled,
  onSubmit,
  onPickOption,
  onUpload,
}: {
  request: HumanInputRequest
  disabled?: boolean
  /** Free-text submit when there are no canned options. */
  onSubmit?: (text: string) => void
  onPickOption: (value: string) => void
  /** One file, staged and sent as the next turn (the `request_upload` tool). */
  onUpload?: (file: File) => void
}) {
  const options = humanInputOptionLabels(request)
  const picker = useRef<HTMLInputElement>(null)
  return (
    <div className="human-input-panel" role="region" aria-label="需要你确认" data-testid="human-input-panel">
      <p className="human-input-question">{request.question}</p>
      {request.input_mode === 'upload' ? (
        <div className="human-input-upload">
          <input
            ref={picker}
            type="file"
            accept="image/*"
            hidden
            aria-label="选择图片"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) onUpload?.(f)
              e.target.value = ''
            }}
          />
          <button
            type="button"
            className="btn btn-teal btn-sm"
            disabled={disabled}
            onClick={() => picker.current?.click()}
          >
            上传图片
          </button>
        </div>
      ) : options.length > 0 ? (
        <AnswerOptions options={options} disabled={disabled} onPick={onPickOption} />
      ) : (
        onSubmit && (
          <form
            className="human-input-free"
            onSubmit={(e) => {
              e.preventDefault()
              const fd = new FormData(e.currentTarget)
              const t = String(fd.get('reply') ?? '').trim()
              if (t) onSubmit(t)
            }}
          >
            <input name="reply" type="text" aria-label="你的回答" placeholder="输入后回车发送" disabled={disabled} />
          </form>
        )
      )}
    </div>
  )
}
