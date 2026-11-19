import type { TodoItem } from '../../api/types'

/**
 * The Agent's visible plan (`write_todos`).
 *
 * This exists for the reader, not the model: a canvas of five screens used to show one step
 * line at a time with no indication of what was still coming, so a long turn looked stuck.
 * The newest list replaces the previous one — a checklist is a state, not a log.
 */
export function TodoList({ items }: { items: TodoItem[] }) {
  if (items.length === 0) return null
  const done = items.filter((i) => i.status === 'done').length
  return (
    <div className="todo-list" role="region" aria-label="执行计划">
      <div className="todo-head">
        <span>执行计划</span>
        <span className="todo-count">{done}/{items.length}</span>
      </div>
      <ol>
        {items.map((item, n) => (
          <li key={`${n}-${item.text}`} className={`todo-item is-${item.status}`}>
            <span className="todo-mark" aria-hidden="true">
              {item.status === 'done' ? '✓' : item.status === 'in_progress' ? '•' : '○'}
            </span>
            <span>{item.text}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
