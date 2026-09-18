/* sb-theme: light */
/**
 * 骨架模板 · KPI 卡片（横向瀑布流，浅色）
 * 浅色模板可放心使用白色系（rgba(255,255,255,x)/#fff）：播放页会自动配白色遮罩（SKILL.md §3.3）。
 */
export default function Screen({ data }) {
  const v = data.values || {};
  const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 }));
  const base = [
    { label: '月度收入', value: '¥' + fmt(v.revenue), delta: '+12.4%', bar: 55 },
    { label: '活跃用户', value: fmt(v.users), delta: '+21.9%', bar: 79 },
    { label: '今日订单', value: fmt(v.orders), delta: '+5.2%', bar: 62 },
    { label: '转化率', value: (v.conversion ?? '—') + '%', delta: '-0.4%', bar: 30 },
  ];
  const items = [...base];
  // ★ 预览填充：真实指标不足 32 个时，重复填充标记为「占位」的卡片，
  //   把画面撑出横向滚动（SmartStage）观感；正式上线模板删除本段即可只显示真实指标。
  const PAD_TO = 32;
  while (items.length < PAD_TO) {
    const src = base[items.length % base.length];
    items.push({
      label: src.label + ' · 占位',
      value: src.value,
      delta: '占位数据',
      bar: 10 + ((items.length * 29) % 75),
    });
  }
  const per = 4;
  const GAP = 15;
  const cols = [];
  for (let i = 0; i < items.length; i += per) cols.push(items.slice(i, i + per));
  const rowH = 'calc((100% - ' + (per - 1) * GAP + 'px) / ' + per + ')';
  const colW = (col) => {
    let w = 170;
    for (const it of col) {
      const est = 170 + (String(it.label).length + String(it.value).length) * 7;
      if (est > w) w = est;
    }
    return Math.min(320, w);
  };
  return (
    <div style={{ width: '100%', height: '100%', boxSizing: 'border-box', padding: '22px 26px', display: 'flex', flexDirection: 'column', background: 'transparent', color: '#181818', fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'stretch', gap: GAP, flex: 1, minHeight: 0 }}>
        {cols.map((col, ci) => (
          <div key={ci} style={{ display: 'flex', flexDirection: 'column', gap: GAP, width: colW(col), flexShrink: 0 }}>
            {col.map((it) => (
              <div key={it.label} style={{ boxSizing: 'border-box', height: rowH, width: '100%', background: 'rgba(255, 255, 255, 0.92)', border: '1px solid #E5E5E7', padding: '12px 16px', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 5, overflow: 'hidden' }}>
                <span style={{ fontSize: 13, color: '#666', lineHeight: 1.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.label}</span>
                <span style={{ fontSize: 34, fontWeight: 650, fontVariantNumeric: 'tabular-nums', lineHeight: 1.15 }}>{it.value}</span>
                <div style={{ height: 4, borderRadius: 99, background: '#F1F1F3', marginTop: 6, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: it.bar + '%', background: '#FA5B35' }} />
                </div>
                <span style={{ fontSize: 11, color: '#0A7C4B' }}>{it.delta}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
