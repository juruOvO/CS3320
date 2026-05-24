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

  it('renders overview page content', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('从课程要求到展示原型的全局总览')).toBeInTheDocument()
    })

    expect(screen.getByText('戏曲剧本多维分析平台')).toBeInTheDocument()
    expect(screen.getByText('前后端接口暴露')).toBeInTheDocument()
  })
})
