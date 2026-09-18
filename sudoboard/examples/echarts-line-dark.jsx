/* sb-theme: dark */
/**
 * 骨架模板 · ECharts 折线 + KPI（横向瀑布流，深色）
 * 数据刷新重绘要点：useEffect 依赖带上模板用到的数据字段（SKILL.md §3.4）。
 */
export default function Screen({ data }) {
  const { useEffect, useRef } = React;
  const v = data.values || {};
  const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 }));
  const trend = Array.isArray(v.trend) ? v.trend : [30, 42, 38, 55, 61, 58, 72, 83, 76, 90];
  const chartRef = useRef(null);
  useEffect(() => {
    const el = chartRef.current;
    if (!el || typeof echarts === 'undefined') return;
    const chart = echarts.init(el);
    chart.setOption({
      backgroundColor: 'transparent', // ★ 透出壁纸
      grid: { left: 8, right: 8, top: 16, bottom: 4, containLabel: true },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: trend.map((_, i) => String(i + 1)), axisLine: { lineStyle: { color: '#3a3f4a' } }, axisLabel: { color: '#8f8f8f' } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#23262E' } }, axisLabel: { color: '#8f8f8f' } },
      series: [{ type: 'line', smooth: true, showSymbol: false, data: trend, lineStyle: { color: '#1EAEDB', width: 2 }, areaStyle: { color: 'rgba(30,174,219,0.12)' } }],
    });
    return () => chart.dispose(); // ★ 长稳必须 dispose
  }, [trend]); // ★ 数据刷新 → 图表重绘
  const per = 4;
  const GAP = 15;
  const cols = [[
    { label: '今日请求量', value: fmt(v.qps), chart: false },
    { label: '趋势（ECharts）', value: '', chart: true },
  ]];
  const rowH = 'calc((100% - ' + (per - 1) * GAP + 'px) / ' + per + ')';
  return (
    <div style={{ width: '100%', height: '100%', boxSizing: 'border-box', padding: '22px 26px', display: 'flex', flexDirection: 'column', background: 'transparent', color: '#e8eaf0', fontFamily: 'ui-sans-serif, system-ui, sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'stretch', gap: GAP, flex: 1, minHeight: 0 }}>
        {cols.map((col, ci) => (
          <div key={ci} style={{ display: 'flex', flexDirection: 'column', gap: GAP, width: 340, flexShrink: 0 }}>
            {col.map((it) => it.chart ? (
              <div key={it.label}>
                <span style={{ fontSize: 11, color: '#8f8f8f', letterSpacing: '.08em' }}>{it.label}</span>
                <div ref={chartRef} style={{ boxSizing: 'border-box', height: rowH, width: '100%', background: 'rgba(15, 18, 24, 0.85)', border: '1px solid #23262E', padding: 8, overflow: 'hidden' }} />
              </div>
            ) : (
              <div key={it.label} style={{ boxSizing: 'border-box', height: rowH, width: '100%', background: 'rgba(15, 18, 24, 0.85)', border: '1px solid #23262E', padding: '12px 16px', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 6, overflow: 'hidden' }}>
                <span style={{ fontSize: 13, color: '#8f8f8f', letterSpacing: '.06em' }}>{it.label}</span>
                <span style={{ fontSize: 34, fontWeight: 600, fontVariantNumeric: 'tabular-nums', lineHeight: 1.15 }}>{it.value}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
