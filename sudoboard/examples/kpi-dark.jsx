/* sb-theme: dark */
/**
 * 骨架模板 · KPI 卡片（横向瀑布流，深色）
 * 复制到 <proj>/sudoboard/templates/main.jsx 后按数据源命名值改 items。
 * 已遵守 SKILL.md §3 全部契约：透明背景 / 无标题 / 直角 / tabular-nums / 非f开头hex。
 */
export default function Screen({ data }) {
  const v = data.values || {};
  const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 }));
  const base = [
    { label: '账户余额', value: '¥' + fmt(v.balance) },
    { label: '今日收入', value: '¥' + fmt(v.income) },
    { label: '活跃用户', value: fmt(v.users) + ' 人' },
    { label: '今日订单', value: fmt(v.orders) + ' 单' },
  ];
  const items = [...base];
  // ★ 预览填充：真实指标不足 32 个时，重复填充标记为「占位」的卡片，
  //   把画面撑出横向滚动（SmartStage）观感；正式上线模板删除本段即可只显示真实指标。
  const PAD_TO = 32;
  while (items.length < PAD_TO) {
    const src = base[items.length % base.length];
    items.push({ label: src.label + ' · 占位', value: src.value });
  }
  const per = 4; // 每列 4 块当量；内容超屏时播放页自动横向慢速滚动
  const cols = [];
  for (let i = 0; i < items.length; i += per) cols.push(items.slice(i, i + per));
  const GAP = 15;
  const rowH = 'calc((100% - ' + (per - 1) * GAP + 'px) / ' + per + ')';
  const colW = (col) => {
    let w = 150;
    for (const it of col) {
      const est = 150 + (String(it.label).length + String(it.value).length) * 7;
      if (est > w) w = est;
    }
    return Math.min(300, w);
  };
  return (
    <div style={{ width: '100%', height: '100%', boxSizing: 'border-box', padding: '22px 26px', display: 'flex', flexDirection: 'column', background: 'transparent', color: '#e8eaf0', fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'stretch', gap: GAP, flex: 1, minHeight: 0 }}>
        {cols.map((col, ci) => (
          <div key={ci} style={{ display: 'flex', flexDirection: 'column', gap: GAP, width: colW(col), flexShrink: 0 }}>
            {col.map((it) => (
              <div key={it.label} style={{ boxSizing: 'border-box', height: rowH, width: '100%', background: 'rgba(15, 18, 24, 0.85)', border: '1px solid #23262E', padding: '12px 16px', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 6, overflow: 'hidden' }}>
                <span style={{ fontSize: 13, color: '#8f8f8f', letterSpacing: '.06em', lineHeight: 1.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.label}</span>
                <span style={{ fontSize: 34, fontWeight: 600, fontVariantNumeric: 'tabular-nums', lineHeight: 1.15 }}>{it.value}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
