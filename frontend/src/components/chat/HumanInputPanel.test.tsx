import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HumanInputPanel } from './HumanInputPanel'
import type { HumanInputRequest } from '../../api/types'

const base: HumanInputRequest = {
  version: 1,
  kind: 'human_input_request',
  source: 'ask_question',
  request_id: 'r1',
  tool_call_id: 't1',
  question: '想朝哪个方向改？',
  input_mode: 'single_choice',
  options: [{ id: 'o0', label: '更克制', value: '更克制' }],
}

describe('HumanInputPanel', () => {
  it('offers reply buttons for a choice question', () => {
    const onPick = vi.fn()
    render(<HumanInputPanel request={base} onPickOption={onPick} />)
    fireEvent.click(screen.getByText('更克制'))
    expect(onPick).toHaveBeenCalledWith('更克制')
  })

  it('offers a file picker when the Agent asked for a picture', () => {
    const onUpload = vi.fn()
    render(
      <HumanInputPanel
        request={{ ...base, source: 'request_upload', input_mode: 'upload', options: [] }}
        onPickOption={vi.fn()}
        onUpload={onUpload}
      />,
    )
    // A text box would be the wrong surface: a picture cannot be described in one.
    expect(screen.queryByRole('textbox')).toBeNull()
    const input = screen.getByLabelText('选择图片') as HTMLInputElement
    const file = new File(['x'], 'product.png', { type: 'image/png' })
    fireEvent.change(input, { target: { files: [file] } })
    expect(onUpload).toHaveBeenCalledWith(file)
  })

  it('falls back to a text box for an open question', () => {
    const onSubmit = vi.fn()
    render(
      <HumanInputPanel
        request={{ ...base, input_mode: 'text', options: [] }}
        onPickOption={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    fireEvent.change(screen.getByLabelText('你的回答'), { target: { value: '金属剃须刀' } })
    fireEvent.submit(screen.getByLabelText('你的回答').closest('form') as HTMLFormElement)
    expect(onSubmit).toHaveBeenCalledWith('金属剃须刀')
  })
})
