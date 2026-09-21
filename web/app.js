const state = { reports: {} };

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Ошибка запроса ${response.status}`);
  }
  return response.json();
}

function html(target, markup) {
  document.getElementById(target).innerHTML = markup;
}

function kpi(label, value, foot = '', cls = '') {
  return `<div class="kpi">
    <div class="label">${label}</div>
    <div class="value ${cls}">${value}</div>
    ${foot ? `<div class="foot">${foot}</div>` : ''}
  </div>`;
}

function table(columns, rows) {
  const head = columns.map((c) => `<th class="${c.num ? 'num' : ''}">${c.title}</th>`).join('');
  const body = rows.map((row) => `<tr>${columns
    .map((c) => `<td class="${c.num ? 'num' : ''}">${c.render ? c.render(row) : row[c.key] ?? ''}</td>`)
    .join('')}</tr>`).join('');
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function money(value, digits = 2) {
  return `$${Number(value).toFixed(digits)}`;
}

function escape(text) {
  return String(text ?? '').replace(/[&<>]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch]));
}

function statusClass(status) {
  return status === 'alert' ? 'bad' : status === 'warn' ? 'warn' : 'ok';
}

document.getElementById('tabs').addEventListener('click', (event) => {
  const button = event.target.closest('.tab');
  if (!button) return;
  document.querySelectorAll('.tab').forEach((tab) => tab.classList.remove('active'));
  document.querySelectorAll('.panel-group').forEach((panel) => panel.classList.remove('active'));
  button.classList.add('active');
  document.getElementById(`tab-${button.dataset.tab}`).classList.add('active');
});

async function loadHealth() {
  const dot = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  try {
    const health = await api('/api/health');
    dot.className = `dot ${health.ollama ? 'ok' : 'off'}`;
    text.textContent = health.ollama
      ? `${health.model} · ${health.requests_stored} запросов в телеметрии`
      : 'Ollama недоступна';
  } catch (error) {
    dot.className = 'dot off';
    text.textContent = 'сервис недоступен';
  }
}

async function loadOverview() {
  const data = await api('/api/overview');
  const latency = data.latency || {};
  const alertClass = data.alert && data.alert.firing ? 'bad' : 'ok';
  html('overview-cards', [
    kpi('запросов', data.requests),
    kpi('p50', `${Charts.fmt(latency.p50 || 0)} ms`),
    kpi('p95', `${Charts.fmt(latency.p95 || 0)} ms`, '', alertClass),
    kpi('p99', `${Charts.fmt(latency.p99 || 0)} ms`, '', alertClass),
    kpi('стоимость', money(data.total_cost_usd, 4),
      `${data.tokens.input} in / ${data.tokens.output} out`),
    kpi('галлюцинации', data.hallucination_rate === null || data.hallucination_rate === undefined
      ? 'нет данных'
      : `${(data.hallucination_rate * 100).toFixed(1)}%`, 'eval dataset',
      data.hallucination_rate > 0.05 ? 'bad' : 'ok'),
    kpi('дрейф', data.drift_status || 'нет данных', 'baseline vs production',
      statusClass(data.drift_status)),
  ].join(''));

  const stages = data.stages || [];
  if (stages.length) {
    Charts.horizontal(document.getElementById('overview-stages'), {
      labels: stages.map((s) => s.stage),
      values: stages.map((s) => s.avg_ms),
      colors: stages.map((s, index) => (index === 0 ? Charts.COLORS.danger : Charts.COLORS.blue)),
      xLabel: 'среднее время, ms',
    });
  }

  const endpoints = Object.entries(data.by_endpoint || {});
  if (endpoints.length) {
    Charts.grouped(document.getElementById('overview-endpoints'), {
      labels: endpoints.map(([name]) => name),
      series: [
        { name: 'avg', color: Charts.COLORS.accent, values: endpoints.map(([, v]) => v.avg) },
        { name: 'p95', color: Charts.COLORS.warn, values: endpoints.map(([, v]) => v.p95) },
      ],
      yLabel: 'ms',
    });
  }

  const telemetry = await api('/api/telemetry?limit=12');
  html('overview-table', table([
    { title: 'время', render: (r) => r.timestamp.slice(11, 19) },
    { title: 'endpoint', key: 'endpoint' },
    { title: 'язык', key: 'language' },
    { title: 'тема', key: 'topic' },
    { title: 'промпт', render: (r) => escape(r.prompt.slice(0, 70)) },
    { title: 'latency', num: true, render: (r) => Charts.fmt(r.latency_ms) },
    { title: 'in/out', num: true, render: (r) => `${r.input_tokens}/${r.output_tokens}` },
    { title: 'cost', num: true, render: (r) => money(r.cost_usd, 6) },
  ], telemetry.rows));
}

async function loadLatency() {
  const report = await api('/api/report/latency').catch(() => null);
  if (!report) {
    html('latency-cards', '<p class="empty-state">Запустите scripts/run_latency.py</p>');
    return;
  }
  state.reports.latency = report;
  const base = report.baseline;
  html('latency-cards', [
    kpi('запросов', base.count),
    kpi('average', `${Charts.fmt(base.avg)} ms`),
    kpi('p50', `${Charts.fmt(base.p50)} ms`),
    kpi('p95', `${Charts.fmt(base.p95)} ms`),
    kpi('p99', `${Charts.fmt(base.p99)} ms`),
    kpi('min / max', `${Charts.fmt(base.min)} / ${Charts.fmt(base.max)}`, 'ms'),
  ].join(''));

  Charts.histogram(document.getElementById('latency-hist'), {
    edges: report.histogram.edges,
    counts: report.histogram.counts,
    xLabel: 'latency, ms',
    yLabel: 'запросов',
  });

  Charts.horizontal(document.getElementById('latency-stages'), {
    labels: report.stages.map((s) => s.stage),
    values: report.stages.map((s) => s.avg_ms),
    colors: report.stages.map((s) => (s.stage === report.slowest_stage
      ? Charts.COLORS.danger : Charts.COLORS.blue)),
    xLabel: 'среднее время, ms',
  });

  const comparison = report.comparison;
  html('latency-compare', table([
    { title: 'метрика', key: 'metric' },
    { title: 'без медленных', num: true, render: (r) => Charts.fmt(r.before) },
    { title: 'с медленными', num: true, render: (r) => Charts.fmt(r.after) },
    { title: 'дельта', num: true, render: (r) => `${r.delta > 0 ? '+' : ''}${Charts.fmt(r.delta)}` },
    { title: '%', num: true, render: (r) => (r.delta_pct === null ? '' : `${r.delta_pct > 0 ? '+' : ''}${r.delta_pct}%`) },
  ], Object.entries(comparison).map(([metric, value]) => ({ metric: metric.toUpperCase(), ...value }))));

  const alertState = report.alert.state_with_slow;
  html('latency-alert', `
    <div class="note ${alertState.firing ? 'bad' : ''}">
      <strong>${escape(report.alert.rule)}</strong>
    </div>
    <p class="hint">Состояние на базовой выборке:
      <span class="badge ${report.alert.state_baseline.firing ? 'bad' : 'ok'}">
        ${report.alert.state_baseline.firing ? 'firing' : 'ok'}</span>
      &nbsp;с медленными запросами:
      <span class="badge ${alertState.firing ? 'bad' : 'ok'}">
        ${alertState.firing ? 'firing' : 'ok'}</span>
    </p>
    <p class="hint">Самый медленный этап: <span class="mono">${escape(report.slowest_stage)}</span>
      (${report.stages[0].avg_ms} ms, ${(report.stages[0].share * 100).toFixed(1)}% времени).</p>
    <p class="hint">Метрики для прода: ${report.production_metrics.map((m) => `<span class="badge muted">${escape(m)}</span>`).join(' ')}</p>
  `);
}

function renderCalculator(prices) {
  const inputs = ['calc-input', 'calc-output', 'calc-rpd', 'calc-calls'].map((id) => document.getElementById(id));
  const update = () => {
    const [tokensIn, tokensOut, perDay, calls] = inputs.map((input) => Number(input.value) || 0);
    const perCall = (tokensIn / 1e6) * prices.input_per_1m + (tokensOut / 1e6) * prices.output_per_1m;
    const perRequest = perCall * Math.max(calls, 1);
    const inputShare = tokensIn * prices.input_per_1m;
    const outputShare = tokensOut * prices.output_per_1m;
    const share = inputShare + outputShare;
    html('calc-result', [
      kpi('1 запрос', money(perRequest, 6)),
      kpi('1 000 запросов', money(perRequest * 1000, 3)),
      kpi('день', money(perRequest * perDay, 2)),
      kpi('месяц', money(perRequest * perDay * 30, 2)),
      kpi('доля output', share ? `${((outputShare / share) * 100).toFixed(0)}%` : '0%',
        'в стоимости запроса'),
    ].join(''));
  };
  inputs.forEach((input) => input.addEventListener('input', update));
  update();
}

async function loadCost() {
  const report = await api('/api/report/cost').catch(() => null);
  renderCalculator((report && report.prices) || { input_per_1m: 2, output_per_1m: 8 });
  if (!report) {
    html('cost-leak', '<p class="empty-state">Запустите scripts/run_cost.py</p>');
    return;
  }
  state.reports.cost = report;

  const experiment = report.context_experiment;
  if (experiment.length) {
    Charts.line(document.getElementById('cost-context-cost'), {
      x: experiment.map((item) => item.context_size),
      series: [{
        name: 'стоимость 1000 запросов, $',
        color: Charts.COLORS.accent,
        values: experiment.map((item) => item.cost_per_1k_requests),
      }],
      xLabel: 'контекст, токены',
      yLabel: '$ / 1k',
    });
    Charts.line(document.getElementById('cost-context-latency'), {
      x: experiment.map((item) => item.context_size),
      series: [{
        name: 'latency, ms',
        color: Charts.COLORS.blue,
        values: experiment.map((item) => item.avg_latency_ms),
      }],
      xLabel: 'контекст, токены',
      yLabel: 'ms',
    });
  }

  const endpoints = report.endpoints;
  const naive = Object.fromEntries(endpoints.naive.map((item) => [item.endpoint, item.total_cost]));
  Charts.grouped(document.getElementById('cost-endpoints'), {
    labels: endpoints.with_agent_fanout.map((item) => item.endpoint),
    series: [
      {
        name: '1 вызов',
        color: Charts.COLORS.blue,
        values: endpoints.with_agent_fanout.map((item) => naive[item.endpoint]),
      },
      {
        name: 'с фанаутом агента',
        color: Charts.COLORS.danger,
        values: endpoints.with_agent_fanout.map((item) => item.total_cost),
      },
    ],
    yLabel: '$',
  });

  const leak = endpoints.cost_leak;
  html('cost-leak', `
    <div class="note bad">
      <strong>${escape(leak.endpoint)}</strong> забирает ${(leak.share_of_total * 100).toFixed(0)}%
      счёта: ${escape(leak.reason)}.
    </div>
    <p class="hint">Второй источник: ${escape(leak.second_source)}.</p>
    <p class="hint">Итого за период: ${money(endpoints.total_naive)} без учёта фанаута и
      ${money(endpoints.total_with_fanout)} с ним, разница ${money(endpoints.fanout_overhead)}.</p>
    ${table([
      { title: 'endpoint', key: 'endpoint' },
      { title: 'запросов', num: true, render: (r) => r.requests.toLocaleString('ru-RU') },
      { title: 'in/out', num: true, render: (r) => `${r.avg_input}/${r.avg_output}` },
      { title: 'вызовов', num: true, render: (r) => (r.calls_per_request === 1 ? '1' : `${r.calls_low}-${r.calls_high}`) },
      { title: 'стоимость', num: true, render: (r) => money(r.total_cost) },
      { title: 'доля', num: true, render: (r) => `${(r.share * 100).toFixed(1)}%` },
    ], endpoints.with_agent_fanout)}
  `);

  html('cost-optimizations', table([
    { title: 'что делаем', key: 'action' },
    { title: 'эффект', key: 'effect' },
    { title: 'оценка', key: 'estimate' },
  ], report.optimizations));
}

async function loadDrift() {
  const report = await api('/api/report/drift').catch(() => null);
  if (!report) {
    html('drift-cards', '<p class="empty-state">Запустите scripts/run_drift.py</p>');
    return;
  }
  state.reports.drift = report;
  const features = Object.fromEntries(report.drift.features.map((f) => [f.feature, f]));

  html('drift-cards', [
    kpi('статус', report.drift.status, 'baseline vs production', statusClass(report.drift.status)),
    kpi('PSI язык', features.language.psi, features.language.status,
      statusClass(features.language.status)),
    kpi('PSI тема', features.topic.psi, features.topic.status, statusClass(features.topic.status)),
    kpi('длина запроса', `${features.query_length_tokens.production_mean} tok`,
      `${features.query_length_tokens.delta_pct > 0 ? '+' : ''}${features.query_length_tokens.delta_pct}% к baseline`,
      statusClass(features.query_length_tokens.status)),
    kpi('живой трафик', report.live_traffic ? report.live_traffic.status : 'нет данных',
      report.live_traffic ? `${report.live_traffic.sample_size} запросов` : '',
      statusClass(report.live_traffic && report.live_traffic.status)),
  ].join(''));

  ['language', 'topic'].forEach((name) => {
    const feature = features[name];
    const keys = Object.keys({ ...feature.baseline, ...feature.production });
    Charts.grouped(document.getElementById(`drift-${name}`), {
      labels: keys,
      series: [
        { name: 'baseline', color: Charts.COLORS.blue, values: keys.map((k) => (feature.baseline[k] || 0) * 100) },
        { name: 'production', color: Charts.COLORS.warn, values: keys.map((k) => (feature.production[k] || 0) * 100) },
      ],
      yLabel: '% трафика',
    });
  });

  const categorical = report.drift.features.filter((f) => f.type === 'categorical');
  Charts.bars(document.getElementById('drift-psi'), {
    labels: categorical.map((f) => f.feature),
    values: categorical.map((f) => f.psi),
    colors: categorical.map((f) => Charts.COLORS[statusClass(f.status) === 'bad' ? 'danger'
      : statusClass(f.status) === 'warn' ? 'warn' : 'accent']),
    thresholds: [
      { value: report.drift.thresholds.psi_warn, label: 'warn 0.1', color: Charts.COLORS.warn },
      { value: report.drift.thresholds.psi_alert, label: 'alert 0.25', color: Charts.COLORS.danger },
    ],
    yLabel: 'PSI',
  });

  html('drift-thresholds', `<div class="list">${Object.entries(report.thresholds_rationale)
    .map(([key, value]) => `<div class="item"><h3 class="mono">${escape(key)}</h3><p>${escape(value)}</p></div>`)
    .join('')}</div>`);

  const incident = report.incident;
  html('drift-incident', `
    <div class="note warn"><strong>Чтение ситуации.</strong> ${escape(incident.reading)}</div>
    <div class="list">${incident.hypotheses.map((item) => `
      <div class="item">
        <h3>${escape(item.hypothesis)}</h3>
        <p>${escape(item.why)}</p>
        <ul>${item.metrics_to_check.map((m) => `<li>${escape(m)}</li>`).join('')}</ul>
        <p class="mono">подтвердится, если ${escape(item.confirms_if)}</p>
      </div>`).join('')}</div>
    <p class="hint">Что проверяю первым делом: ${incident.priority_checks
      .map((check) => `<span class="badge muted">${escape(check)}</span>`).join(' ')}</p>
  `);
}

async function loadEval() {
  const report = await api('/api/report/eval').catch(() => null);
  if (!report) {
    html('eval-cards', '<p class="empty-state">Запустите scripts/run_eval.py</p>');
    return;
  }
  state.reports.eval = report;
  const summary = report.summary;

  html('eval-cards', [
    kpi('вопросов', summary.total),
    kpi('hallucination rate', `${(summary.hallucination_rate * 100).toFixed(1)}%`, '',
      summary.hallucination_rate > 0.05 ? 'bad' : 'ok'),
    kpi('средний score', summary.avg_score),
    kpi('отказов', `${(summary.abstain_rate * 100).toFixed(1)}%`, 'ответ вида нет данных'),
    kpi('accuracy@0.6', `${(summary.accuracy_at_06 * 100).toFixed(0)}%`, 'score не ниже 0.6'),
    kpi('утверждений', Object.values(summary.claim_counts).reduce((a, b) => a + b, 0),
      `${(summary.claim_shares.SUPPORTED * 100).toFixed(0)}% подтверждено`),
  ].join(''));

  const labels = ['SUPPORTED', 'PARTIALLY_SUPPORTED', 'UNSUPPORTED', 'CONTRADICTED'];
  Charts.bars(document.getElementById('eval-claims'), {
    labels: labels.map((l) => l.replace('PARTIALLY_SUPPORTED', 'PARTIALLY').toLowerCase()),
    values: labels.map((l) => summary.claim_counts[l]),
    colors: [Charts.COLORS.accent, Charts.COLORS.blue, Charts.COLORS.warn, Charts.COLORS.danger],
    yLabel: 'утверждений',
  });

  const types = Object.entries(summary.by_question_type);
  Charts.bars(document.getElementById('eval-types'), {
    labels: types.map(([name]) => name),
    values: types.map(([, value]) => value.hallucination_rate * 100),
    colors: types.map(([, value]) => (value.hallucination_rate >= 0.5 ? Charts.COLORS.danger
      : value.hallucination_rate > 0 ? Charts.COLORS.warn : Charts.COLORS.accent)),
    yLabel: '%',
  });

  html('eval-table', table([
    { title: 'id', key: 'id' },
    { title: 'тип', key: 'question_type' },
    { title: 'вопрос', render: (r) => escape(r.question) },
    { title: 'ответ модели', render: (r) => `<details><summary class="muted">${escape(r.model_answer.slice(0, 60))}…</summary>
        <p>${escape(r.model_answer)}</p>
        <p class="muted">эталон: ${escape(r.reference_answer)}</p>
        <ul>${r.claims.map((c) => `<li><span class="badge ${c.label === 'SUPPORTED' ? 'ok'
          : c.label === 'CONTRADICTED' ? 'bad' : c.label === 'UNSUPPORTED' ? 'warn' : 'muted'}">${c.label}</span>
          ${escape(c.claim)}</li>`).join('')}</ul></details>` },
    { title: 'score', num: true, key: 'score' },
    { title: 'галлюцинация', num: true, render: (r) => `<span class="badge ${r.hallucination ? 'bad' : 'ok'}">${r.hallucination ? 'да' : 'нет'}</span>` },
  ], report.results));

  const incident = report.incident;
  html('eval-incident', `
    <div class="chain">${['change', 'symptom', 'hypothesis', 'metric', 'root cause', 'mitigation']
      .map((step) => `<span>${step}</span>`).join('<i class="muted">→</i>')}</div>
    <div class="list">${incident.investigation.map((item) => `
      <div class="item">
        <h3>${escape(item.change)}</h3>
        <p><strong>симптом:</strong> ${escape(item.symptom)}</p>
        <p><strong>гипотеза:</strong> ${escape(item.hypothesis)}</p>
        <p><strong>что смотрю:</strong> ${escape(item.metric_to_check)}</p>
        <p><strong>причина:</strong> ${escape(item.root_cause)}</p>
        <p><strong>что делаю:</strong> ${escape(item.mitigation)}</p>
      </div>`).join('')}</div>
    <p class="hint">Мониторинг, который поймает это раньше:</p>
    <ul class="hint">${incident.monitoring.map((m) => `<li>${escape(m)}</li>`).join('')}</ul>
  `);
}

async function sendPrompt() {
  const button = document.getElementById('send');
  const prompt = document.getElementById('prompt').value.trim();
  if (!prompt) return;
  const answer = document.getElementById('answer');
  button.disabled = true;
  answer.className = 'answer empty';
  answer.textContent = 'модель думает';
  try {
    const record = await api('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        endpoint: document.getElementById('endpoint').value,
        num_predict: Number(document.getElementById('num-predict').value),
      }),
    });
    answer.className = 'answer';
    answer.textContent = record.response;
    html('answer-metrics', [
      kpi('latency', `${Charts.fmt(record.latency_ms)} ms`),
      kpi('токены', `${record.input_tokens}/${record.output_tokens}`, 'in/out'),
      kpi('стоимость', money(record.cost_usd, 6)),
      kpi('язык', record.language),
      kpi('тема', record.topic),
      kpi('вызовов', record.calls),
    ].join(''));
    const stages = Object.entries(record.stages).sort((a, b) => b[1] - a[1]);
    Charts.horizontal(document.getElementById('answer-stages'), {
      labels: stages.map(([name]) => name),
      values: stages.map(([, value]) => value),
      colors: stages.map((item, index) => (index === 0 ? Charts.COLORS.danger : Charts.COLORS.blue)),
      xLabel: 'ms',
    });
    html('answer-context', record.retrieved.length
      ? `<p class="hint">Контекст: ${record.retrieved
          .map((c) => `<span class="badge muted">${escape(c.id)} · ${escape(c.title)}</span>`).join(' ')}</p>`
      : '');
    loadOverview().catch(() => {});
    loadHealth().catch(() => {});
  } catch (error) {
    answer.className = 'answer empty';
    answer.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

document.getElementById('send').addEventListener('click', sendPrompt);
document.getElementById('prompt').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) sendPrompt();
});

loadHealth();
loadOverview().catch((error) => html('overview-cards', `<p class="empty-state">${error.message}</p>`));
loadLatency();
loadCost();
loadDrift();
loadEval();
