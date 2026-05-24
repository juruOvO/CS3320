import ReactECharts from 'echarts-for-react'
import { Surface } from './Surface'

export function ChartPanel({
  title,
  subtitle,
  option,
  height = 320,
}: {
  title: string
  subtitle?: string
  option: Record<string, unknown>
  height?: number
}) {
  return (
    <Surface title={title} subtitle={subtitle} className="overflow-hidden">
      <ReactECharts option={option} style={{ height }} opts={{ renderer: 'canvas' }} />
    </Surface>
  )
}
