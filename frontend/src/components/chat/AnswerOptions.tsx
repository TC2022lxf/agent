/**
 * Replies the Agent offered along with a question, as one-click buttons.
 *
 * Answering a question used to mean retyping the constraint the user had just given
 * ("纯白背景、居中、不要文字" again, plus the missing product). A button sends the text
 * verbatim, so the next Run starts from an answer instead of a restart. The button is a
 * shortcut for typing, not a new interaction: it goes through the same send path.
 */
export function AnswerOptions({ options, onPick, disabled }: {
  options: string[]
  onPick: (text: string) => void
  disabled?: boolean
}) {
  if (options.length === 0) return null
  return (
    <div className="answer-options" role="group" aria-label="可选回复">
      {options.map((text) => (
        <button
          key={text}
          type="button"
          className="answer-option"
          disabled={disabled}
          onClick={() => onPick(text)}
        >
          {text}
        </button>
      ))}
    </div>
  )
}
