// Лёгкие SVG-графики, чтобы дашборд работал без внешних библиотек
const Charts = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  // Палитра chart-1..chart-5 из shadcn/ui, тёмная тема
  const COLORS = {
    accent: '#2eb88a',
    blue: '#2662d9',
    warn: '#e88c30',
    danger: '#ef4444',
    violet: '#af57db',
    line: '#27272a',
    muted: '#a1a1aa',
  };
  const W = 640, H = 280;
  const PAD = { top: 18, right: 18, bottom: 44, left: 56 };

  function el(name, attrs = {}, text) {
    const node = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function frame(target) {
    target.innerHTML = '';
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'xMidYMid meet' });
    target.appendChild(svg);
    return svg;
  }

  function niceMax(value) {
    if (value <= 0) return 1;
    const power = Math.pow(10, Math.floor(Math.log10(value)));
    const scaled = value / power;
    const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
    return step * power;
  }

  function fmt(value) {
    const abs = Math.abs(value);
    if (abs >= 1000000) return (value / 1000000).toFixed(1) + 'M';
    if (abs >= 1000) return (value / 1000).toFixed(abs >= 10000 ? 0 : 1) + 'k';
    if (abs >= 10) return value.toFixed(0);
    if (abs >= 1) return value.toFixed(1);
    if (abs === 0) return '0';
    return value.toFixed(abs < 0.01 ? 4 : 2);
  }

  function axes(svg, max, labels, options = {}) {
    const plotW = W - PAD.left - PAD.right;
    const plotH = H - PAD.top - PAD.bottom;
    const ticks = 4;
    for (let i = 0; i <= ticks; i += 1) {
      const y = PAD.top + plotH - (plotH * i) / ticks;
      svg.appendChild(el('line', {
        x1: PAD.left, x2: W - PAD.right, y1: y, y2: y,
        stroke: COLORS.line, 'stroke-width': 1,
      }));
      svg.appendChild(el('text', {
        x: PAD.left - 10, y: y + 4, fill: COLORS.muted, 'font-size': 10,
        'text-anchor': 'end', 'font-family': 'ui-monospace, monospace',
      }, fmt((max * i) / ticks)));
    }
    if (options.yLabel) {
      svg.appendChild(el('text', {
        x: 12, y: PAD.top + plotH / 2, fill: COLORS.muted, 'font-size': 10,
        'text-anchor': 'middle', transform: `rotate(-90 12 ${PAD.top + plotH / 2})`,
      }, options.yLabel));
    }
    if (options.xLabel) {
      svg.appendChild(el('text', {
        x: PAD.left + plotW / 2, y: H - 6, fill: COLORS.muted,
        'font-size': 10, 'text-anchor': 'middle',
      }, options.xLabel));
    }
    if (labels) {
      const step = plotW / labels.length;
      labels.forEach((label, index) => {
        svg.appendChild(el('text', {
          x: PAD.left + step * (index + 0.5), y: H - PAD.bottom + 18,
          fill: COLORS.muted, 'font-size': 10, 'text-anchor': 'middle',
        }, label));
      });
    }
    return { plotW, plotH };
  }

  function bars(target, { labels, values, colors, yLabel, xLabel, thresholds }) {
    const svg = frame(target);
    const max = niceMax(Math.max(...values, ...(thresholds || []).map((t) => t.value), 0.0001));
    const { plotW, plotH } = axes(svg, max, labels, { yLabel, xLabel });
    const step = plotW / labels.length;
    values.forEach((value, index) => {
      const height = Math.max(1, (value / max) * plotH);
      const width = Math.min(46, step * 0.55);
      svg.appendChild(el('rect', {
        x: PAD.left + step * (index + 0.5) - width / 2,
        y: PAD.top + plotH - height,
        width, height, rx: 3,
        fill: (colors && colors[index]) || COLORS.accent,
      }));
      svg.appendChild(el('text', {
        x: PAD.left + step * (index + 0.5), y: PAD.top + plotH - height - 6,
        fill: COLORS.muted, 'font-size': 10, 'text-anchor': 'middle',
        'font-family': 'ui-monospace, monospace',
      }, fmt(value)));
    });
    (thresholds || []).forEach((threshold) => {
      const y = PAD.top + plotH - (threshold.value / max) * plotH;
      svg.appendChild(el('line', {
        x1: PAD.left, x2: W - PAD.right, y1: y, y2: y,
        stroke: threshold.color || COLORS.warn, 'stroke-width': 1, 'stroke-dasharray': '5 4',
      }));
      svg.appendChild(el('text', {
        x: W - PAD.right, y: y - 5, fill: threshold.color || COLORS.warn,
        'font-size': 9, 'text-anchor': 'end',
      }, threshold.label));
    });
  }

  function grouped(target, { labels, series, yLabel, xLabel }) {
    const svg = frame(target);
    const max = niceMax(Math.max(...series.flatMap((s) => s.values), 0.0001));
    const { plotW, plotH } = axes(svg, max, labels, { yLabel, xLabel });
    const step = plotW / labels.length;
    const width = Math.min(30, (step * 0.62) / series.length);
    series.forEach((serie, serieIndex) => {
      serie.values.forEach((value, index) => {
        const height = Math.max(1, (value / max) * plotH);
        const offset = (serieIndex - (series.length - 1) / 2) * (width + 4);
        svg.appendChild(el('rect', {
          x: PAD.left + step * (index + 0.5) + offset - width / 2,
          y: PAD.top + plotH - height,
          width, height, rx: 3, fill: serie.color,
        }));
      });
    });
    legend(svg, series);
  }

  function legend(svg, series) {
    let x = PAD.left;
    series.forEach((serie) => {
      svg.appendChild(el('rect', { x, y: 4, width: 9, height: 9, rx: 2, fill: serie.color }));
      const text = el('text', {
        x: x + 14, y: 12, fill: COLORS.muted, 'font-size': 10,
      }, serie.name);
      svg.appendChild(text);
      x += 22 + serie.name.length * 6;
    });
  }

  function line(target, { x, series, yLabel, xLabel }) {
    const svg = frame(target);
    const max = niceMax(Math.max(...series.flatMap((s) => s.values), 0.0001));
    const { plotW, plotH } = axes(svg, max, x.map(String), { yLabel, xLabel });
    const step = plotW / x.length;
    series.forEach((serie) => {
      const points = serie.values.map((value, index) => [
        PAD.left + step * (index + 0.5),
        PAD.top + plotH - (value / max) * plotH,
      ]);
      svg.appendChild(el('polyline', {
        points: points.map((p) => p.join(',')).join(' '),
        fill: 'none', stroke: serie.color, 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round',
      }));
      points.forEach(([px, py], index) => {
        svg.appendChild(el('circle', { cx: px, cy: py, r: 3.5, fill: serie.color }));
        svg.appendChild(el('text', {
          x: px, y: py - 9, fill: COLORS.muted, 'font-size': 9, 'text-anchor': 'middle',
          'font-family': 'ui-monospace, monospace',
        }, fmt(serie.values[index])));
      });
    });
    if (series.length > 1) legend(svg, series);
  }

  function histogram(target, { edges, counts, xLabel, yLabel }) {
    const svg = frame(target);
    const max = niceMax(Math.max(...counts, 1));
    const { plotW, plotH } = axes(svg, max, null, { xLabel, yLabel });
    const width = plotW / counts.length;
    counts.forEach((count, index) => {
      const height = (count / max) * plotH;
      svg.appendChild(el('rect', {
        x: PAD.left + width * index + 1,
        y: PAD.top + plotH - height,
        width: Math.max(1, width - 2), height: Math.max(count ? 2 : 0, height),
        fill: COLORS.accent, rx: 2,
      }));
    });
    const tickCount = Math.min(6, edges.length);
    for (let i = 0; i < tickCount; i += 1) {
      const index = Math.round((i * (edges.length - 1)) / (tickCount - 1));
      svg.appendChild(el('text', {
        x: PAD.left + (plotW * index) / (edges.length - 1),
        y: H - PAD.bottom + 18, fill: COLORS.muted, 'font-size': 10,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace',
      }, fmt(edges[index])));
    }
  }

  function horizontal(target, { labels, values, colors, xLabel }) {
    const svg = frame(target);
    const max = niceMax(Math.max(...values, 0.0001));
    const left = PAD.left + 26;
    const plotW = W - left - PAD.right - 40;
    const plotH = H - PAD.top - PAD.bottom;
    const step = plotH / labels.length;
    labels.forEach((label, index) => {
      const y = PAD.top + step * index + step * 0.2;
      const height = step * 0.55;
      const width = Math.max(2, (values[index] / max) * plotW);
      svg.appendChild(el('text', {
        x: left - 8, y: y + height / 2 + 4, fill: COLORS.muted,
        'font-size': 10, 'text-anchor': 'end',
      }, label));
      svg.appendChild(el('rect', {
        x: left, y, width, height, rx: 3,
        fill: (colors && colors[index]) || COLORS.blue,
      }));
      svg.appendChild(el('text', {
        x: left + width + 8, y: y + height / 2 + 4, fill: COLORS.muted,
        'font-size': 10, 'font-family': 'ui-monospace, monospace',
      }, fmt(values[index])));
    });
    if (xLabel) {
      svg.appendChild(el('text', {
        x: left + plotW / 2, y: H - 8, fill: COLORS.muted,
        'font-size': 10, 'text-anchor': 'middle',
      }, xLabel));
    }
  }

  return { bars, grouped, line, histogram, horizontal, COLORS, fmt };
})();
