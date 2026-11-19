import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TodoList } from './TodoList'

describe('TodoList', () => {
  it('renders each step with its state', () => {
    render(
      <TodoList
        items={[
          { text: '写标题', status: 'done' },
          { text: '生成主图', status: 'in_progress' },
          { text: '检查规则', status: 'pending' },
        ]}
      />,
    )
    expect(screen.getByText('1/3')).toBeInTheDocument()
    expect(screen.getByText('写标题')).toBeInTheDocument()
    expect(screen.getByText('生成主图').closest('li')).toHaveClass('is-in_progress')
    expect(screen.getByText('检查规则').closest('li')).toHaveClass('is-pending')
  })

  it('renders nothing when there is no plan', () => {
    const { container } = render(<TodoList items={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})
