/* CriptoEstratégia — dashboard (vanilla JS + Chart.js) */
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C = {
  text: css('--text-primary'), text2: css('--text-secondary'), muted: css('--text-muted'),
  grid: css('--grid'), surface: css('--surface-1'), s1: css('--series-1'),
  good: css('--good'), bad: css('--critical'),
};
// paleta categórica (modo escuro), por ordem fixa
const CAT = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
const EXIT_ORDER = ['TP2', 'TP1', 'TRAILING STOP', 'BREAKEVEN', 'FECHO ABAIXO EMA20', 'FECHO ACIMA EMA20', 'EMA9 CRUZOU ABAIXO EMA20', 'EMA9 CRUZOU ACIMA EMA20', 'STOP LOSS', 'TIME STOP', 'ESTAGNAÇÃO', 'LIQUIDAÇÃO', 'MANUAL'];
const WD = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

Chart.defaults.color = C.muted;
Chart.defaults.borderColor = C.grid;
Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.display = false;
Chart.defaults.plugins.tooltip.backgroundColor = '#0b0b0b';
Chart.defaults.plugins.tooltip.borderColor = C.grid;
Chart.defaults.plugins.tooltip.borderWidth = 1;
Chart.defaults.plugins.tooltip.padding = 8;
Chart.defaults.animation = false;

// ── formatação ──
const nf = (v, d = 2) => v == null || isNaN(v) ? '—' : Number(v).toLocaleString('pt-PT', { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (v, d = 2, suf = '') => v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + nf(Math.abs(v), d) + suf;
const cls = v => v > 0 ? 'pos' : v < 0 ? 'neg' : '';
const px = v => { if (v == null) return '—'; const a = Math.abs(v); const d = a >= 1000 ? 2 : a >= 1 ? 4 : a >= 0.01 ? 6 : 8; return nf(v, d); };
const usd = v => nf(v, 2) + ' USDT';
const pnl = (v, d = 4) => `<span class="${cls(v)}">${sgn(v, d)}</span>`;
const pct = (v, d = 2) => `<span class="${cls(v)}">${sgn(v, d, '%')}</span>`;
const dt = ms => ms ? new Date(ms).toLocaleString('pt-PT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';
const dur = m => { if (m == null) return '—'; if (m < 60) return Math.round(m) + 'm'; if (m < 1440) return (m / 60).toFixed(1) + 'h'; return (m / 1440).toFixed(1) + 'd'; };
const sym = s => s ? s.replace(/_?USDT$/, '<span class="muted">/USDT</span>') : '';
const sideTag = s => `<span class="tag ${s === 'LONG' ? 'win' : 'loss'}">${s}</span>`;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const api = p => fetch(p, { cache: 'no-store' }).then(r => r.json());

function table(el, cols, rows, empty = 'Sem dados ainda.') {
  const h = '<thead><tr>' + cols.map(c => `<th class="${c.l ? 'l' : ''}" title="${esc(c.t || '')}">${c.h}</th>`).join('') + '</tr></thead>';
  const b = rows.length ? rows.map(r => '<tr>' + cols.map(c => `<td class="${c.l ? 'l' : ''}">${c.f(r)}</td>`).join('') + '</tr>').join('')
    : `<tr><td class="l muted" colspan="${cols.length}">${empty}</td></tr>`;
  document.getElementById(el).innerHTML = h + '<tbody>' + b + '</tbody>';
}

// ── tabs ──
document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('active', x === b));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.id === 'tab-' + b.dataset.tab));
  refresh();
});
const activeTab = () => document.querySelector('#tabs button.active').dataset.tab;

// ── controlos ──
const post = p => fetch(p, { method: 'POST' }).then(() => setTimeout(refresh, 600));
document.getElementById('btn-pause').onclick = () => post('/api/control/pause');
document.getElementById('btn-resume').onclick = () => post('/api/control/resume');
document.getElementById('btn-closeall').onclick = () => confirm('Fechar TODAS as posições a mercado?') && post('/api/control/closeall');
window.closePos = (id, s) => confirm(`Fechar a posição #${id} (${s}) a mercado?`) && post('/api/control/close/' + id);

// ── gráficos ──
const charts = {};
const timeAxis = {
  type: 'linear', grid: { display: false },
  ticks: { maxTicksLimit: 8, callback: v => new Date(v).toLocaleString('pt-PT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) },
};
const yAxis = (fmt = v => nf(v, 2)) => ({ grid: { color: C.grid }, border: { display: false }, ticks: { callback: fmt } });
function mk(id, cfg) {
  if (!charts[id]) charts[id] = new Chart(document.getElementById(id), cfg);
  return charts[id];
}
function setData(ch, labels, datasets) {
  ch.data.labels = labels;
  datasets.forEach((d, i) => Object.assign(ch.data.datasets[i], d));
  ch.update();
}
const barColors = arr => arr.map(v => v >= 0 ? C.good : C.bad);
function barChart(id, horizontal = false, fmt = v => sgn(v, 2) + ' USDT', axisFmt) {
  return mk(id, {
    type: 'bar',
    data: { labels: [], datasets: [{ data: [], borderRadius: 4, borderSkipped: 'start', maxBarThickness: 26 }] },
    options: {
      indexAxis: horizontal ? 'y' : 'x', responsive: true, maintainAspectRatio: false,
      scales: horizontal ? { x: yAxis(axisFmt), y: { grid: { display: false }, ticks: { autoSkip: false } } } : { x: { grid: { display: false } }, y: yAxis(axisFmt) },
      plugins: { tooltip: { callbacks: { label: c => fmt(c.parsed[horizontal ? 'x' : 'y'], c) } } },
    },
  });
}

function drawEquity(rows, cap0) {
  const pts = rows.map(r => ({ x: r.time, y: r.equity }));
  const ch = mk('ch-equity', {
    type: 'line',
    data: { datasets: [
      { label: 'Equity', data: [], borderColor: C.s1, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0,
        fill: { target: { value: cap0 }, above: 'rgba(57,135,229,0.10)', below: 'rgba(208,59,59,0.10)' } },
      { label: 'Capital inicial', data: [], borderColor: C.muted, borderWidth: 1, borderDash: [4, 4], pointRadius: 0, pointHoverRadius: 0 },
    ] },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      scales: { x: timeAxis, y: yAxis(v => nf(v, 2)) },
      plugins: { legend: { display: true, labels: { boxWidth: 12, boxHeight: 2 } },
        tooltip: { callbacks: { title: i => dt(i[0].parsed.x), label: c => ` ${c.dataset.label}: ${nf(c.parsed.y, 2)} USDT` } } },
    },
  });
  const xs = pts.length ? [pts[0].x, pts[pts.length - 1].x] : [];
  setData(ch, undefined, [{ data: pts }, { data: xs.map(x => ({ x, y: cap0 })) }]);
  const ddc = mk('ch-dd', {
    type: 'line',
    data: { datasets: [{ label: 'Drawdown', data: [], borderColor: C.bad, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
      fill: 'origin', backgroundColor: 'rgba(208,59,59,0.15)', tension: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      scales: { x: timeAxis, y: { ...yAxis(v => nf(v, 1) + '%'), max: 0 } },
      plugins: { tooltip: { callbacks: { title: i => dt(i[0].parsed.x), label: c => ` Drawdown: ${nf(c.parsed.y, 2)}%` } } },
    },
  });
  setData(ddc, undefined, [{ data: rows.map(r => ({ x: r.time, y: -r.drawdown_pct })) }]);
  document.getElementById('eq-hint').textContent = rows.length ? `${rows.length} pontos · pico ${nf(Math.max(...rows.map(r => r.equity)), 2)} USDT` : '';
}

// ── KPIs ──
function kpi(l, v, s = '') { return `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div></div>`; }
function drawKpis(S) {
  document.getElementById('kpis').innerHTML = [
    kpi('Equity', nf(S.equity, 2), `inicial ${nf(S.capital_inicial, 2)} USDT`),
    kpi('PnL total', pnl(S.net_pnl, 2), pct(S.return_pct)),
    kpi('PnL realizado', pnl(S.realized_pnl, 2), `taxas ${nf(S.fees, 4)} · funding ${sgn(S.funding, 4)}`),
    kpi('PnL flutuante', pnl(S.unrealized_pnl, 2), `${S.open_positions}/${S.max_positions} posições`),
    kpi('Margem usada', nf(S.margin_used, 2), `disponível ${nf(S.available, 2)} · alavancagem ${S.leverage}x`),
    kpi('Exposição', nf(S.notional_open, 2), `alavancagem efetiva ${nf(S.effective_leverage, 2)}x`),
    kpi('Win rate', S.win_rate == null ? '—' : nf(S.win_rate, 1) + '%', `${S.wins} ganhos · ${S.losses} perdas`),
    kpi('Profit factor', nf(S.profit_factor, 2), `payoff ${nf(S.payoff, 2)}`),
    kpi('Expectativa', S.expectancy == null ? '—' : pnl(S.expectancy, 4), `média ${sgn(S.avg_r, 2, 'R')} · total ${sgn(S.total_r, 2, 'R')}`),
    kpi('Drawdown atual', nf(-S.drawdown_pct, 2) + '%', `máx. ${nf(-S.max_drawdown_pct, 2)}% (${nf(S.max_drawdown_usdt, 2)} USDT)`),
    kpi('Trades', S.trades, `${S.longs} long · ${S.shorts} short · ${nf(S.trades_per_day, 1)}/dia`),
    kpi('Sharpe / Sortino', `${nf(S.sharpe, 2)} / ${nf(S.sortino, 2)}`, 'anualizado (retornos horários)'),
    kpi('Sequência', S.current_streak > 0 ? `${S.current_streak} ▲` : S.current_streak < 0 ? `${-S.current_streak} ▼` : '—', `máx. ${S.max_win_streak} ganhos · ${S.max_loss_streak} perdas`),
  ].join('');
}

function drawStatsTable(S) {
  const rows = [
    ['Capital inicial', usd(S.capital_inicial)], ['Equity', usd(S.equity)], ['Saldo da carteira', usd(S.balance)], ['Pico de equity', usd(S.peak)],
    ['Alavancagem', S.leverage + 'x (margem isolada)'], ['Margem usada', usd(S.margin_used)], ['Margem disponível', usd(S.available)],
    ['Exposição (notional aberto)', usd(S.notional_open)], ['Alavancagem efetiva', nf(S.effective_leverage, 2) + 'x'],
    ['Funding pago/recebido', pnl(S.funding, 4)], ['ROE médio por trade', pct(S.avg_roe)], ['Liquidações', S.liquidations],
    ['Trades long / short', `${S.longs} / ${S.shorts}`],
    ['PnL líquido', pnl(S.net_pnl, 4) + ' USDT'], ['Retorno', pct(S.return_pct)],
    ['PnL realizado', pnl(S.realized_pnl, 4)], ['PnL flutuante', pnl(S.unrealized_pnl, 4)],
    ['Lucro bruto', usd(S.gross_profit)], ['Prejuízo bruto', usd(S.gross_loss)],
    ['Trades fechados', S.trades], ['Ganhos / perdas', `${S.wins} / ${S.losses}`],
    ['Win rate', S.win_rate == null ? '—' : nf(S.win_rate, 1) + '%'], ['% trades que atingiram TP1', S.tp1_rate == null ? '—' : nf(S.tp1_rate, 1) + '%'],
    ['Profit factor', nf(S.profit_factor, 2)], ['Payoff (ganho médio / perda média)', nf(S.payoff, 2)],
    ['Ganho médio', pnl(S.avg_win, 4)], ['Perda média', pnl(S.avg_loss, 4)],
    ['Expectativa por trade', pnl(S.expectancy, 4)], ['R médio por trade', sgn(S.avg_r, 3, 'R')], ['R total', sgn(S.total_r, 2, 'R')],
    ['Melhor trade', pnl(S.best_trade, 4)], ['Pior trade', pnl(S.worst_trade, 4)],
    ['Máx. ganhos seguidos', S.max_win_streak], ['Máx. perdas seguidas', S.max_loss_streak],
    ['Duração média', dur(S.avg_duration_min)], ['Duração média (ganhos)', dur(S.avg_win_duration_min)], ['Duração média (perdas)', dur(S.avg_loss_duration_min)],
    ['MFE médio (máx. a favor)', pct(S.avg_mfe_pct)], ['MAE médio (máx. contra)', pct(S.avg_mae_pct)],
    ['Drawdown máximo', nf(-S.max_drawdown_pct, 2) + '% · ' + usd(S.max_drawdown_usdt)], ['Drawdown atual', nf(-S.drawdown_pct, 2) + '%'],
    ['Recovery factor', nf(S.recovery_factor, 2)], ['Sharpe (anual.)', nf(S.sharpe, 2)], ['Sortino (anual.)', nf(S.sortino, 2)],
    ['Exposição atual', nf(S.exposure_pct, 1) + '%'], ['Volume negociado', usd(S.volume_traded)], ['Taxas pagas', usd(S.fees)],
    ['Trades por dia', nf(S.trades_per_day, 2)], ['Dias em execução', nf(S.days_running, 2)],
  ];
  document.getElementById('stats-table').innerHTML = rows.map(([a, b]) => `<div>${a}</div><div>${b}</div>`).join('');
}

// ── posições ──
function slTpBar(p) {
  // posição do preço entre o SL (esquerda) e o próximo alvo (direita) — funciona para long e short
  const lo = p.sl, hi = p.tp1_hit ? p.tp2 : p.tp1;
  const f = Math.max(0, Math.min(1, (p.price - lo) / (hi - lo)));
  const e = Math.max(0, Math.min(1, (p.entry_price - lo) / (hi - lo)));
  const col = (p.side === 'LONG' ? p.price >= p.entry_price : p.price <= p.entry_price) ? C.good : C.bad;
  const a = Math.min(f, e), w = Math.abs(f - e);
  return `<div class="bar" title="SL ${px(lo)} → ${p.tp1_hit ? 'TP2' : 'TP1'} ${px(hi)}"><b style="left:${a * 100}%;width:${w * 100}%;background:${col}"></b><i style="left:calc(${f * 100}% - 1px)"></i></div>`;
}
function drawPositions(P) {
  document.getElementById('pos-count').textContent = P.length;
  const full = [
    { h: '#', l: 1, f: p => p.id }, { h: 'Contrato', l: 1, f: p => sym(p.symbol) }, { h: 'Lado', l: 1, f: p => sideTag(p.side) + ` <span class="muted">${p.leverage}x</span>` },
    { h: 'Entrada', f: p => dt(p.entry_time) }, { h: 'Idade', f: p => dur(p.age_min) },
    { h: 'Preço entrada', f: p => px(p.entry_price) }, { h: 'Preço atual', f: p => px(p.price), t: 'Long: bid · Short: ask (preço real de fecho)' },
    { h: 'Contratos', f: p => nf(p.contracts_open ?? p.contracts, 0) }, { h: 'Notional', f: p => nf(p.value, 2) }, { h: 'Margem', f: p => nf(p.margin_open, 2) },
    { h: 'PnL flutuante', f: p => pnl(p.unrealized_pnl, 4) }, { h: 'ROE', f: p => pct(p.roe_pct), t: 'Retorno sobre a margem (com alavancagem)' },
    { h: 'Realizado', f: p => pnl(p.realized_pnl, 4), t: 'TP1 parcial + funding' }, { h: 'R atual', f: p => `<span class="${cls(p.r_now)}">${sgn(p.r_now, 2, 'R')}</span>` },
    { h: 'SL', f: p => px(p.sl) + (p.sl !== p.initial_sl ? ' <span class="tag">movido</span>' : '') }, { h: 'TP1', f: p => px(p.tp1) + (p.tp1_hit ? ' <span class="tag win">feito</span>' : '') },
    { h: 'TP2', f: p => px(p.tp2) }, { h: 'SL ↔ alvo', f: slTpBar, t: 'Barra entre o stop atual e o próximo alvo; o traço é o preço atual' },
    { h: 'Liquidação', f: p => px(p.liq_price) + ` <span class="muted">(${nf(p.dist_liq_pct, 1)}%)</span>` },
    { h: 'Funding', f: p => pnl(p.funding_total, 4) }, { h: 'Risco (1R)', f: p => nf(p.risk_usdt, 4) }, { h: 'Score', f: p => nf(p.score, 1) },
    { h: 'BTC', f: p => p.market_regime || '' }, { h: 'Motivo', l: 1, f: p => `<span class="muted">${esc(p.entry_reason)}</span>` },
    { h: '', f: p => `<button onclick="closePos(${p.id}, '${p.symbol}')">Fechar</button>` },
  ];
  table('t-pos', full, P, 'Sem posições abertas. O bot procura entradas a cada vela de 1m fechada.');
  table('t-pos-mini', [full[1], full[2], full[6], full[10], full[11], full[13], full[17]], P, 'Sem posições abertas.');
}

function drawScan(st) {
  const s = st.last_scan;
  if (!s) { document.getElementById('scan').innerHTML = '<span class="muted">À espera do primeiro scan…</span>'; return; }
  const tot = Object.values(s.rejections || {}).reduce((a, b) => a + b, 0) || 1;
  document.getElementById('scan').innerHTML =
    `<div class="scan-grid">${kpi('Hora', dt(s.time))}${kpi('Pares avaliados', s.evaluated)}${kpi('Sinais', s.signals, `${s.taken} entradas`)}` +
    `${kpi('Regime BTC (15m)', s.btc_regime, s.btc_close ? `preço ${px(s.btc_close)} · EMA50 ${px(s.btc_ema50)}` : '')}</div>` +
    `<h2 style="margin:6px 0">Porque é que os pares foram rejeitados</h2>` +
    Object.entries(s.rejections || {}).map(([k, v]) => `<div class="rej"><span>${esc(k)}</span><div class="track"><b style="width:${v / tot * 100}%"></b></div><span>${v}</span></div>`).join('');
}

function drawStatus(st) {
  const p = [];
  p.push(`<span class="pill ok">${esc(st.source)} · ${st.leverage}x · ${st.shorts ? 'long + short' : 'só long'}</span>`);
  p.push(st.last_error ? `<span class="pill bad" title="${esc(st.last_error)}">Erro: ${esc(st.last_error.slice(0, 60))}</span>` : `<span class="pill ok">A correr</span>`);
  if (st.kill) p.push('<span class="pill bad">Kill switch ativo</span>');
  else if (st.paused) p.push('<span class="pill warn">Em pausa</span>');
  if (st.daily_block) p.push('<span class="pill warn">Limite de perda diária</span>');
  p.push(`<span class="pill">${dt(st.now)}</span>`);
  p.push(`<span class="pill">Universo: ${st.universe_size} contratos</span>`);
  document.getElementById('status').innerHTML = p.join('');
}

// ── análise ──
function drawAnalysis(d) {
  const S = d.summary;
  drawStatsTable(S);
  const intTick = v => Number.isInteger(v) ? v : '';
  const rc = barChart('ch-r', false, (v) => `${v} trades`, intTick);
  const rcols = d.r_hist.map((b, i) => i < 4 ? C.bad : C.good);
  setData(rc, d.r_hist.map(b => b.label), [{ data: d.r_hist.map(b => b.count), backgroundColor: rcols }]);

  const ex = [...d.by_exit].sort((a, b) => (EXIT_ORDER.indexOf(a.reason) + 99) % 99 - (EXIT_ORDER.indexOf(b.reason) + 99) % 99);
  const ec = barChart('ch-exit', true, (v, c) => `${v} trades · PnL ${sgn(ex[c.dataIndex].pnl, 4)} USDT`, intTick);
  setData(ec, ex.map(e => e.reason), [{ data: ex.map(e => e.count), backgroundColor: ex.map(e => e.pnl >= 0 ? C.good : C.bad) }]);

  const top = d.by_symbol.length > 20 ? [...d.by_symbol.slice(0, 10), ...d.by_symbol.slice(-10)] : d.by_symbol;
  const sc = barChart('ch-sym', true);
  setData(sc, top.map(s => s.symbol.replace(/_?USDT$/, '')), [{ data: top.map(s => s.pnl), backgroundColor: barColors(top.map(s => s.pnl)) }]);

  const hc = barChart('ch-hour', false, (v, c) => `${sgn(v, 4)} USDT · ${d.by_hour[c.dataIndex].trades} trades`);
  setData(hc, d.by_hour.map(h => h.hour + 'h'), [{ data: d.by_hour.map(h => h.pnl), backgroundColor: barColors(d.by_hour.map(h => h.pnl)) }]);
  const wd = [1, 2, 3, 4, 5, 6, 0].map(i => d.by_weekday[i]);
  const wc = barChart('ch-wday', false, (v, c) => `${sgn(v, 4)} USDT · ${wd[c.dataIndex].trades} trades`);
  setData(wc, wd.map(w => WD[w.day]), [{ data: wd.map(w => w.pnl), backgroundColor: barColors(wd.map(w => w.pnl)) }]);

  table('t-side', [
    { h: 'Lado', l: 1, f: s => sideTag(s.side) }, { h: 'Trades', f: s => s.trades }, { h: 'Win rate', f: s => nf(s.win_rate, 1) + '%' },
    { h: 'PnL', f: s => pnl(s.pnl, 4) }, { h: 'R total', f: s => `<span class="${cls(s.r)}">${sgn(s.r, 2, 'R')}</span>` },
    { h: 'R médio', f: s => sgn(s.r / s.trades, 3, 'R') },
  ], d.by_side);
  table('t-sym', [
    { h: 'Contrato', l: 1, f: s => sym(s.symbol) }, { h: 'Trades', f: s => s.trades }, { h: 'Win rate', f: s => nf(s.win_rate, 1) + '%' },
    { h: 'PnL', f: s => pnl(s.pnl, 4) }, { h: 'R total', f: s => `<span class="${cls(s.r)}">${sgn(s.r, 2, 'R')}</span>` },
  ], d.by_symbol);
}

function drawDaily(d) {
  const ch = barChart('ch-daily');
  setData(ch, d.daily.map(x => x.day.slice(5)), [{ data: d.daily.map(x => x.pnl), backgroundColor: barColors(d.daily.map(x => x.pnl)) }]);
}

// ── histórico ──
let tradesCache = [];
function drawTrades() {
  const q = document.getElementById('f-sym').value.trim().toUpperCase();
  const r = document.getElementById('f-res').value;
  const rows = tradesCache.filter(t => (!q || t.symbol.includes(q)) && (!r || (r === 'w' ? t.pnl > 0 : t.pnl <= 0)));
  table('t-trades', [
    { h: '#', l: 1, f: t => t.id }, { h: 'Contrato', l: 1, f: t => sym(t.symbol) }, { h: 'Lado', l: 1, f: t => sideTag(t.side) + ` <span class="muted">${t.leverage}x</span>` },
    { h: 'Entrada', f: t => dt(t.entry_time) }, { h: 'Saída', f: t => dt(t.exit_time) },
    { h: 'Duração', f: t => dur(t.duration_min) }, { h: 'Preço entrada', f: t => px(t.entry_price) }, { h: 'Preço saída (médio)', f: t => px(t.exit_price) },
    { h: 'Notional', f: t => nf(t.notional, 2) }, { h: 'Margem', f: t => nf(t.margin, 2) }, { h: 'PnL', f: t => pnl(t.pnl, 4) },
    { h: '%', f: t => pct(t.pnl_pct), t: 'Sobre o notional' }, { h: 'ROE', f: t => pct(t.roe_pct), t: 'Sobre a margem' },
    { h: 'R', f: t => `<span class="${cls(t.r_multiple)}">${sgn(t.r_multiple, 2, 'R')}</span>` },
    { h: 'Saída', l: 1, f: t => `<span class="tag ${t.pnl > 0 ? 'win' : 'loss'}">${esc(t.exit_reason)}</span>` },
    { h: 'TP1', f: t => t.tp1_hit ? '✓' : '' }, { h: 'MFE', f: t => pct(t.mfe_pct), t: 'Máximo a favor' }, { h: 'MAE', f: t => pct(t.mae_pct), t: 'Máximo contra' },
    { h: 'Taxas', f: t => nf(t.fees_total, 4) }, { h: 'Funding', f: t => pnl(t.funding_total, 4) }, { h: 'Score', f: t => nf(t.score, 1) }, { h: 'BTC', f: t => t.market_regime || '' },
    { h: 'Motivo entrada', l: 1, f: t => `<span class="muted">${esc(t.entry_reason)}</span>` },
  ], rows, 'Ainda não há trades fechados.');
}
document.getElementById('f-sym').oninput = drawTrades;
document.getElementById('f-res').onchange = drawTrades;

// ── ciclo de atualização ──
let busy = false;
async function refresh() {
  if (busy) return; busy = true;
  try {
    const tab = activeTab();
    const [st, stats, pos] = await Promise.all([api('/api/status'), api('/api/stats'), api('/api/positions')]);
    drawStatus(st); drawPositions(pos);
    if (tab === 'overview') {
      drawKpis(stats.summary); drawScan(st); drawDaily(stats);
      drawEquity(await api('/api/equity'), stats.summary.capital_inicial);
    } else if (tab === 'analysis') drawAnalysis(stats);
    else if (tab === 'history') {
      const [tr, fl] = await Promise.all([api('/api/trades?limit=2000'), api('/api/fills?limit=500')]);
      tradesCache = tr; drawTrades();
      table('t-fills', [
        { h: '#', l: 1, f: f => f.id }, { h: 'Trade', l: 1, f: f => '#' + f.trade_id }, { h: 'Hora', f: f => dt(f.time) }, { h: 'Moeda', l: 1, f: f => sym(f.symbol) },
        { h: 'Ordem', l: 1, f: f => `<span class="tag ${f.kind === 'ENTRADA' ? 'entry' : f.pnl > 0 ? 'win' : 'loss'}">${f.action === 'BUY' ? 'COMPRA' : f.action === 'SELL' ? 'VENDA' : 'FUNDING'}</span>` },
        { h: 'Tipo', l: 1, f: f => esc(f.kind) }, { h: 'Preço', f: f => px(f.price) }, { h: 'Qtd', f: f => nf(f.qty, 4) }, { h: 'Valor', f: f => nf(f.notional, 2) },
        { h: 'Taxa', f: f => nf(f.fee, 4) }, { h: 'PnL', f: f => f.kind === 'ENTRADA' ? '' : pnl(f.pnl, 4) }, { h: 'Saldo depois', f: f => nf(f.balance_after, 2) },
      ], fl);
    } else if (tab === 'universe') {
      const u = await api('/api/universe');
      document.getElementById('uni-hint').textContent = u.length ? 'Atualizado ' + dt(u[0].updated_at) : '';
      const open = new Set(pos.map(p => p.symbol));
      table('t-uni', [
        { h: '#', l: 1, f: r => r.rank }, { h: 'Contrato', l: 1, f: r => sym(r.symbol) + (open.has(r.symbol) ? ' <span class="tag entry">em posição</span>' : '') },
        { h: 'Score', f: r => nf(r.score, 1) }, { h: 'Volume 24h (USDT)', f: r => nf(r.quote_volume / 1e6, 2) + 'M' },
        { h: 'Volatilidade 24h', f: r => nf(r.volatility_pct, 2) + '%', t: '(máximo − mínimo) / mínimo' }, { h: 'Variação 24h', f: r => pct(r.change_pct) },
        { h: 'Spread', f: r => r.spread_pct == null ? '—' : nf(r.spread_pct, 3) + '%', t: 'Diferença entre o melhor preço de venda (ask) e de compra (bid)' },
        { h: 'Funding', f: r => pct((r.funding_rate || 0) * 100, 4), t: 'Taxa de funding atual (positivo: longs pagam aos shorts)' },
        { h: 'Taxas taker/maker', f: r => `${nf((r.taker_fee || 0) * 100, 3)}% / ${nf((r.maker_fee || 0) * 100, 3)}%` },
        { h: 'Preço', f: r => px(r.last_price) },
      ], u, 'A carregar universo…');
    } else if (tab === 'signals') {
      const s = await api('/api/signals?limit=500');
      table('t-sig', [
        { h: 'Hora', l: 1, f: r => dt(r.time) }, { h: 'Contrato', l: 1, f: r => sym(r.symbol) }, { h: 'Lado', l: 1, f: r => r.side ? sideTag(r.side) : '' }, { h: 'Preço', f: r => px(r.price) }, { h: 'Score', f: r => nf(r.score, 1) },
        { h: 'Decisão', l: 1, f: r => `<span class="tag ${r.decision === 'ENTRADA' ? 'entry' : ''}">${r.decision}</span>` },
        { h: 'Detalhe', l: 1, f: r => `<span class="muted">${esc(r.detail)}</span>` },
      ], s, 'Ainda não houve sinais que passassem todos os filtros.');
    } else if (tab === 'log') {
      const e = await api('/api/events?limit=500');
      table('t-log', [
        { h: 'Hora', l: 1, f: r => dt(r.time) }, { h: 'Nível', l: 1, f: r => `<span class="tag ${r.level === 'ERRO' || r.level === 'ALERTA' ? 'loss' : r.level === 'TRADE' ? 'entry' : ''}">${r.level}</span>` },
        { h: 'Mensagem', l: 1, f: r => esc(r.message) },
      ], e);
    } else if (tab === 'strategy') {
      const c = await api('/api/config');
      document.getElementById('cfg').innerHTML = Object.entries(c).map(([k, v]) => `<div>${k}</div><div>${esc(Array.isArray(v) ? v.join(', ') : v)}</div>`).join('');
    }
  } catch (e) {
    document.getElementById('status').innerHTML = `<span class="pill bad">Sem ligação ao bot: ${esc(e.message)}</span>`;
  } finally { busy = false; }
}
refresh();
setInterval(refresh, 5000);
