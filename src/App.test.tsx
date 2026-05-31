import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="chart" />,
}))

describe('App prototype', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/')
  })

  it('renders dashboard page content', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('任务切换')).toBeInTheDocument()
    })

    expect(screen.getByText('戏曲文本分析看板')).toBeInTheDocument()
    expect(screen.getByText('样本分布图')).toBeInTheDocument()
  })
})
