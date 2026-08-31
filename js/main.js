/**
 * BadmintonSense 主逻辑 — 连接接收端后端，展示推理结果
 *
 * 数据流:
 *   sender.py → receiver_backend.py (推理) → WebSocket :8090 → 本前端页面
 */

// ==================== 状态 ====================
const state = {
    socket: null,
    isConnected: false,
    totalActions: 0,
    correctCount: 0,
    wrongCount: 0,
    history: [],
};

const LABEL_NAMES = {
    1: "正手发球",
    2: "反手发球",
    3: "正手平抽",
    4: "反手平抽",
    5: "正手高远球",
    6: "反手高远球",
    7: "杀球",
};

// ==================== 工具函数 ====================

function getEl(id) {
    return document.getElementById(id);
}

function updateStats() {
    getEl('totalActions').innerText = state.totalActions;
    getEl('correctCount').innerText = state.correctCount;
    getEl('wrongCount').innerText = state.wrongCount;
    const accuracy = state.totalActions === 0
        ? 0 : Math.round((state.correctCount / state.totalActions) * 100);
    getEl('accuracy').innerText = accuracy + '%';
}

function setStatus(connected, text) {
    const dot = getEl('statusDot');
    const textEl = getEl('statusText');
    if (connected) {
        dot.className = 'status-dot connected';
        textEl.innerText = text || '已连接';
    } else {
        dot.className = 'status-dot';
        textEl.innerText = text || '未连接';
    }
}

function getActionColor(label) {
    const colors = {
        1: '#3b82f6', 2: '#8b5cf6', 3: '#06b6d4',
        4: '#f59e0b', 5: '#10b981', 6: '#ec4899', 7: '#ef4444',
    };
    return colors[label] || '#64748b';
}

// ==================== 显示推理结果 ====================

function showPrediction(data) {
    const actionNum = state.totalActions;
    const predictedLabel = data.predicted_label;
    const predictedName = data.predicted_label_name || LABEL_NAMES[predictedLabel] || `未知(${predictedLabel})`;
    const confidence = (data.confidence * 100).toFixed(1);
    const actualLabel = data.label;
    const actualName = data.label_name || LABEL_NAMES[actualLabel] || (actualLabel === 'N/A' ? '无' : `未知(${actualLabel})`);
    const isCorrect = data.is_correct;

    getEl('predictionPlaceholder').style.display = 'none';
    getEl('predictionContent').style.display = 'block';

    getEl('actionNum').innerText = actionNum;
    getEl('sampleId').innerText = data.sample_id || 'N/A';

    const predictedColor = getActionColor(predictedLabel);
    getEl('predictedLabelName').innerText = predictedName;
    getEl('predictedLabelName').style.color = predictedColor;

    getEl('actualLabelName').innerText = actualName;
    if (actualLabel !== 'N/A' && actualLabel !== -1) {
        getEl('actualLabelName').style.color = getActionColor(actualLabel);
    } else {
        getEl('actualLabelName').style.color = '#94a3b8';
    }

    const iconEl = getEl('resultIcon');
    if (actualLabel === 'N/A' || actualLabel === -1) {
        iconEl.innerText = '🔍';
        iconEl.style.background = '#f1f5f9';
    } else if (isCorrect) {
        iconEl.innerText = '✅';
        iconEl.style.background = '#d1fae5';
    } else {
        iconEl.innerText = '❌';
        iconEl.style.background = '#fee2e2';
    }

    getEl('confidenceValue').innerText = confidence + '%';
    getEl('confidenceBar').style.width = confidence + '%';
    if (confidence >= 80) {
        getEl('confidenceBar').style.background = '#10b981';
    } else if (confidence >= 60) {
        getEl('confidenceBar').style.background = '#f59e0b';
    } else {
        getEl('confidenceBar').style.background = '#ef4444';
    }
}

// ==================== 推理历史 ====================

function addHistory(data) {
    const predictedName = data.predicted_label_name || LABEL_NAMES[data.predicted_label] || `未知(${data.predicted_label})`;
    const actualName = data.label_name || LABEL_NAMES[data.label] || (data.label === 'N/A' ? '无' : `未知(${data.label})`);
    const confidence = (data.confidence * 100).toFixed(1);

    state.history.unshift({
        id: Date.now(),
        actionNum: state.totalActions,
        sampleId: data.sample_id || 'N/A',
        predictedLabel: data.predicted_label,
        predictedName: predictedName,
        actualLabel: data.label,
        actualName: actualName,
        confidence: confidence,
        isCorrect: data.is_correct,
    });

    renderHistory();
}

function renderHistory() {
    const container = getEl('historyList');
    if (state.history.length === 0) {
        container.innerHTML = '<p class="history-empty">暂无推理记录</p>';
        return;
    }

    let html = '';
    state.history.forEach(item => {
        const predictedColor = getActionColor(item.predictedLabel);
        let statusIcon = '';
        if (item.actualLabel === 'N/A' || item.actualLabel === -1) {
            statusIcon = '🔍';
        } else if (item.isCorrect) {
            statusIcon = '✅';
        } else {
            statusIcon = '❌';
        }

        html += `
            <div class="history-item">
                <div class="history-item-header">
                    <span class="history-action-num">#${item.actionNum}</span>
                    <span class="history-sample-id">${item.sampleId}</span>
                    <span class="history-status-icon">${statusIcon}</span>
                </div>
                <div class="history-item-body">
                    <div class="history-predicted">
                        <span class="history-label">预测</span>
                        <span class="history-value" style="color: ${predictedColor};">${item.predictedName}</span>
                    </div>
                    <div class="history-actual">
                        <span class="history-label">真实</span>
                        <span class="history-value">${item.actualName}</span>
                    </div>
                    <div class="history-conf">
                        <span class="history-label">置信度</span>
                        <span class="history-value">${item.confidence}%</span>
                    </div>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

window.clearHistory = function () {
    state.history = [];
    renderHistory();
};

// ==================== WebSocket 连接 ====================

window.toggleReceiverConnection = function () {
    const btn = getEl('connectBtn');

    if (state.isConnected) {
        if (state.socket) {
            state.socket.close();
        }
        return;
    }

    const wsUrl = getEl('wsUrl').value.trim();
    if (!wsUrl) {
        alert('请输入接收端 WebSocket 地址！');
        return;
    }

    btn.innerText = '连接中...';
    btn.disabled = true;
    setStatus(false, '连接中...');

    try {
        state.socket = new WebSocket(wsUrl);

        state.socket.onopen = () => {
            state.isConnected = true;
            btn.innerText = '断开连接';
            btn.className = 'btn btn-outline';
            btn.disabled = false;
            setStatus(true, '已连接');
            getEl('predictionPlaceholder').style.display = 'block';
            getEl('predictionContent').style.display = 'none';
        };

        state.socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'prediction') {
                    state.totalActions++;
                    if (data.is_correct) {
                        state.correctCount++;
                    } else if (data.label !== 'N/A' && data.label !== -1) {
                        state.wrongCount++;
                    }
                    updateStats();

                    showPrediction(data);

                    addHistory(data);
                }

            } catch (e) {
                console.warn('解析消息失败:', e);
            }
        };

        state.socket.onclose = () => {
            state.isConnected = false;
            btn.innerText = '连接接收端';
            btn.className = 'btn btn-primary';
            btn.disabled = false;
            setStatus(false, '连接已断开');
            state.socket = null;
        };

        state.socket.onerror = () => {
            alert('连接失败，请确认接收端服务正在运行。');
            state.isConnected = false;
            btn.innerText = '连接接收端';
            btn.className = 'btn btn-primary';
            btn.disabled = false;
            setStatus(false, '连接失败');
            state.socket = null;
        };

    } catch (e) {
        console.error('创建 WebSocket 失败:', e);
        btn.innerText = '连接接收端';
        btn.className = 'btn btn-primary';
        btn.disabled = false;
        setStatus(false, '连接错误');
    }
};

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', () => {
    updateStats();
});
