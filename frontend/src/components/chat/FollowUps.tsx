/**
 * Suggestions for what to ask next, under a finished answer.
 *
 * Deliberately not `AnswerOptions`: those answer a question the Agent asked, and clicking one
 * continues the same task. These are new requests the user did not have to type. They are a
 * different colour and carry a different label so nobody confuses a suggestion with an
 * obligation to reply (docs/architecture/system.md, docs/architecture/agent-runtime.md).
 */
export function FollowUps({ questions, onPick, disabled }: {
  questions: string[]
  onPick: (text: string) => void
  disabled?: boolean
}) {
  if (questions.length === 0) return null
  return (
    <div className="follow-ups" role="group" aria-label="你接下来可以问">
      <span className="follow-ups-label">接下来可以问</span>
      <div className="follow-ups-row">
        {questions.map((text) => (
          <button
            key={text}
            type="button"
            className="follow-up-chip"
            disabled={disabled}
            onClick={() => onPick(text)}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  )
}
