// lightweight-charts K线渲染 —— 深色主题 + A股红涨绿跌 + MA均线 + 成交量
// 百度源 K线带 ma5/ma10/ma20;新浪降级时无 MA,自动跳过均线
function renderKline() {
    const container = document.getElementById('kline-chart');
    if (!container || typeof LightweightCharts === 'undefined') return;
    if (!klineData || klineData.length === 0) {
        container.innerHTML = '<p class="dim" style="padding:40px; text-align:center;">无K线数据(数据源未返回或代码错误)</p>';
        return;
    }

    // 检测是否分钟级(日期含空格)→ timeVisible 显示时分
    const isIntraday = klineData.some(k => k.date && k.date.includes(' '));

    const chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: 480,
        layout: {
            background: { color: '#161b22' },
            textColor: '#c9d1d9',
            fontSize: 13,
        },
        grid: {
            vertLines: { color: '#21262d' },
            horzLines: { color: '#21262d' },
        },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#30363d' },
        timeScale: {
            borderColor: '#30363d',
            timeVisible: isIntraday,   // 分钟级显示时分,日/周K只显示日期
            secondsVisible: false,
            textColor: '#f0f6fc',      // 日期/时间轴文字(更亮,深底上清晰)
            fontSize: 13,              // 加大,避免挤成一团看不清
            rightOffset: 4,            // 右侧留白,末尾不被截断
        },
    });

    // A股红涨绿跌
    const UP = '#f85149', DOWN = '#3fb950';
    const candleSeries = chart.addCandlestickSeries({
        upColor: UP, downColor: DOWN,
        borderUpColor: UP, borderDownColor: DOWN,
        wickUpColor: UP, wickDownColor: DOWN,
    });
    // time 格式自适应:含空格(如 "2026-06-30 14:15:00")是分钟级→转 timestamp(秒);
    // 纯日期(如 "2026-06-30")直接用。lightweight-charts 要求 time 唯一且排序。
    function toTime(dateStr) {
        if (!dateStr) return 0;
        if (dateStr.includes(' ')) {
            // 分钟级:转秒级 timestamp
            return Math.floor(new Date(dateStr.replace(/-/g, '/')).getTime() / 1000);
        }
        return dateStr;  // 日/周K:字符串日期
    }
    candleSeries.setData(klineData.map(k => ({
        time: toTime(k.date),
        open: k.open, high: k.high, low: k.low, close: k.close,
    })));

    // 成交量(副图,占底部 20%)
    const volSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'vol',
    });
    volSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volSeries.setData(klineData.map(k => ({
        time: toTime(k.date),
        value: k.volume || 0,
        color: (k.close || 0) >= (k.open || 0) ? 'rgba(248,81,73,0.5)' : 'rgba(63,185,80,0.5)',
    })));

    // MA 均线(仅当 K线带 ma5/ma10/ma20 时,即百度源)
    const maSeries = {};
    const maColors = { ma5: '#58a6ff', ma10: '#d29922', ma20: '#bc8cff' };
    const hasMA = klineData.some(k => k.ma5 !== undefined && k.ma5 !== null);
    if (hasMA) {
        ['ma5', 'ma10', 'ma20'].forEach(key => {
            const s = chart.addLineSeries({ color: maColors[key], lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
            s.setData(klineData.filter(k => k[key] !== undefined && k[key] !== null).map(k => ({ time: toTime(k.date), value: k[key] })));
            maSeries[key] = s;
        });
    }

    chart.timeScale().fitContent();

    // 切换控件
    const toggleMa = document.getElementById('toggle-ma');
    const toggleVol = document.getElementById('toggle-vol');
    if (toggleMa) {
        toggleMa.disabled = !hasMA;
        if (!hasMA) toggleMa.parentElement.style.opacity = '0.4';
        toggleMa.addEventListener('change', () => {
            Object.values(maSeries).forEach(s => s.applyOptions({ visible: toggleMa.checked }));
        });
    }
    if (toggleVol) {
        toggleVol.addEventListener('change', () => {
            volSeries.applyOptions({ visible: toggleVol.checked });
        });
    }

    // 响应窗口缩放
    new ResizeObserver(() => {
        chart.applyOptions({ width: container.clientWidth });
    }).observe(container);
}
document.addEventListener('DOMContentLoaded', renderKline);
