/**
 * Chart.js 管理与渲染组件 (Category 轴 + 最邻近匹配 + 四舍五入纯整数输出)
 */

const nodes = ['handL', 'waist', 'legL', 'legR'];
const nodeColors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444'];
const charts = {};

/**
 * 页面初次初始化 4 张空图表
 */
export function initCharts() {
    nodes.forEach((node, i) => {
        const ctx = document.getElementById(`chart-${node}`).getContext('2d');
        charts[node] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: Array(60).fill(''),
                datasets: [{
                    data: Array(60).fill(0),
                    borderColor: nodeColors[i],
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: true,
                    backgroundColor: nodeColors[i] + '15',
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                layout: { padding: { left: 10, right: 10, top: 10, bottom: 15 } },
                plugins: { legend: { display: false } },
                scales: {
                    x: { 
                        display: false,
                        grid: { display: false },
                        ticks: {
                            autoSkip: false, // 关闭原生自动过滤，交由下方后处理生命周期精确管理
                            maxRotation: 0,
                            minRotation: 0,
                            font: { size: 10 },
                            padding: 8,
                            callback: function(val) {
                                // val 是索引 (如 50)
                                const label = this.getLabelForValue(val);
                                if (!label) return '';
                                
                                const sec = parseFloat(label);
                                if (isNaN(sec)) return label;
                                
                                return Math.round(sec).toString();
                            }
                        },
                        afterBuildTicks: function(scale) {
                            const chart = scale.chart;
                            const labels = chart.data.labels;
                            if (!labels || labels.length === 0) return;

                            // 1. 提取所有标签对应的数值，并获取最大秒数
                            let maxTime = 0;
                            const parsedSeconds = labels.map(l => {
                                if (!l) return NaN;
                                const sec = parseFloat(l);
                                if (!isNaN(sec) && sec > maxTime) {
                                    maxTime = sec;
                                }
                                return sec;
                            });

                            // 2. 自适应决定对齐步长
                            let step = 10;
                            if (maxTime <= 5) step = 1;
                            else if (maxTime <= 15) step = 2;
                            else if (maxTime <= 30) step = 5;

                            // 3. 构建期望精确显示的整十数目标值列表 (如 [0, 10, 20, 30, ...])
                            const targetTimes = [];
                            for (let t = 0; t <= maxTime; t += step) {
                                targetTimes.push(t);
                            }

                            // 4. 为每个目标数值在时序数据中搜寻“最邻近数据点”
                            const filteredTicks = [];
                            targetTimes.forEach(target => {
                                let minDiff = Infinity;
                                let bestIdx = -1;

                                for (let idx = 0; idx < parsedSeconds.length; idx++) {
                                    const sec = parsedSeconds[idx];
                                    if (isNaN(sec)) continue;

                                    const diff = Math.abs(sec - target);
                                    if (diff < minDiff) {
                                        minDiff = diff;
                                        bestIdx = idx;
                                    }
                                }

                                // 允许一定的数据偏差（不超过半步长，即10s步长下，5s偏差内的最近点均可接受）
                                if (bestIdx !== -1 && minDiff < (step / 2)) {
                                    filteredTicks.push({
                                        value: bestIdx
                                    });
                                }
                            });

                            // 覆盖默认刻度
                            scale.ticks = filteredTicks;
                        }
                    },
                    y: { 
                        min: 0, max: 1.6,
                        grid: { color: '#f1f5f9' },
                        ticks: { font: { size: 10 }, padding: 8 }
                    }
                },
                animation: false
            }
        });
    });
}

/**
 * 在线模式：以固定 60 帧滑动窗口进行递进更新
 */
export function updateOnlineChart(dataFrame) {
    Object.keys(dataFrame).forEach(node => {
        const val = dataFrame[node];
        if (document.getElementById(`val-${node}`)) {
            document.getElementById(`val-${node}`).innerText = val.toFixed(2) + 'g';
        }
        const chart = charts[node];
        if (chart) {
            chart.data.datasets[0].data.push(val);
            chart.data.datasets[0].data.shift();
            chart.data.labels.push('');
            chart.data.labels.shift();
            chart.update('none');
        }
    });
}

/**
 * 离线模式：在对应图表上绘制全时序序列曲线
 */
export function plotOfflineData(parsedData) {
    nodes.forEach(node => {
        const chart = charts[node];
        if (!chart) return;

        const nodeData = parsedData[node];

        chart.data.labels = nodeData.labels;
        chart.data.datasets[0].data = nodeData.values;

        // 调整图表参数以展示全局静态视图
        chart.options.scales.x.display = true;       // 显示完整的横坐标轴
        chart.options.scales.y.min = undefined;      // 开启自适应 Y 轴缩放
        chart.options.scales.y.max = undefined;
        chart.options.animation = { duration: 1000 }; // 开启首屏过渡动画

        chart.update();

        // 卡片标签更新为显示当前节点的最大峰值
        const maxVal = nodeData.values.length > 0 ? Math.max(...nodeData.values) : 0;
        if (document.getElementById(`val-${node}`)) {
            document.getElementById(`val-${node}`).innerText = `Max: ${maxVal.toFixed(2)}g`;
        }
    });
}

/**
 * 切换回在线状态时还原滑动窗配置
 */
export function resetToOnlineMode() {
    nodes.forEach(node => {
        const chart = charts[node];
        if (!chart) return;

        chart.data.labels = Array(60).fill('');
        chart.data.datasets[0].data = Array(60).fill(0);

        chart.options.scales.x.display = false;
        chart.options.scales.y.min = 0;
        chart.options.scales.y.max = 1.6;
        chart.options.animation = false;

        chart.update('none');
    });
}