/**
 * BadmintonSense 历史记录管理模块 (基于 IndexedDB)
 */

const DB_NAME = 'BadmintonSenseDB';
const DB_VERSION = 1;
const STORE_NAME = 'history';

/**
 * 初始化 IndexedDB 数据库
 */
export function initDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
            }
        };
        request.onsuccess = (e) => resolve(e.target.result);
        request.onerror = (e) => reject(e.target.error);
    });
}

/**
 * 存储一条新的运动记录
 */
export async function saveRecord(record) {
    const db = await initDB();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.add(record);
        request.onsuccess = () => resolve(request.result);
        request.onerror = (e) => reject(e.target.error);
    });
}

/**
 * 获取所有运动记录 (按时间倒序)
 */
export async function getAllRecords() {
    const db = await initDB();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.getAll();
        request.onsuccess = () => {
            const records = request.result.sort((a, b) => b.id - a.id);
            resolve(records);
        };
        request.onerror = (e) => reject(e.target.error);
    });
}

/**
 * 删除单条运动记录
 */
export async function deleteRecord(id) {
    const db = await initDB();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.delete(id);
        request.onsuccess = () => resolve();
        request.onerror = (e) => reject(e.target.error);
    });
}

/**
 * 渲染主界面的历史记录卡片列表
 */
export async function renderHistoryList() {
    const container = document.getElementById('history-list');
    if (!container) return;

    try {
        const records = await getAllRecords();
        if (records.length === 0) {
            container.innerHTML = `<p style="color: #64748b; text-align: center; padding: 20px 0; margin: 0;">暂无本地历史记录</p>`;
            return;
        }

        let html = '';
        records.forEach(rec => {
            html += `
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 15px; border-bottom: 1px solid #f1f5f9; background: #fff; border-radius: 6px; margin-bottom: 8px; box-shadow: 0 1px 2px rgba(0,0,0,0.02);">
                    <div>
                        <div style="font-size: 13px; font-weight: 600; color: #1e293b;">会话时间：${rec.dateTime}</div>
                        <div style="font-size: 11px; color: #64748b; margin-top: 4px;">
                            挥拍: <strong style="color:#3b82f6;">${rec.totalSwings}次</strong> | 
                            峰值: <strong style="color:#ef4444;">${rec.peakAcc}</strong> | 
                            时长: <strong>${rec.duration}</strong> | 
                            类型: <strong>${rec.status}</strong>
                        </div>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button onclick="viewHistoryDetail(${rec.id})" style="padding: 5px 10px; font-size: 11px; cursor: pointer; background: #3b82f6; color: #fff; border: none; border-radius: 4px;">查看详情</button>
                        <button onclick="deleteHistoryItem(${rec.id})" style="padding: 5px 10px; font-size: 11px; cursor: pointer; background: transparent; color: #ef4444; border: 1px solid #ef4444; border-radius: 4px;">删除</button>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    } catch (err) {
        console.error("更新历史记录 UI 失败:", err);
    }
}

/**
 * 显示单条历史记录详情
 */
export function showHistoryDetail(record) {
    const modal = document.getElementById('historyDetailModal');
    if (!modal) return;

    document.getElementById('history-detail-title').innerText = `历史运动记录 (${record.dateTime})`;

    const actionNames = {
        'fh-serve': '正手发球 (FH Serve)',
        'bh-serve': '反手发球 (BH Serve)',
        'fh-clear': '正手高远球 (FH Clear)',
        'bh-clear': '反手高远球 (BH Clear)',
        'fh-drive': '正手抽球 (FH Drive)',
        'bh-drive': '反手抽球 (BH Drive)',
        'smash': '杀球 (Smash)'
    };

    const totalCount = parseInt(record.totalSwings, 10) || 0;
    let breakdownHtml = '';
    Object.keys(record.actionStats).forEach(key => {
        const count = record.actionStats[key];
        const pct = totalCount === 0 ? 0 : (count / totalCount * 100);
        const color = key === 'smash' ? '#ef4444' : '#3b82f6';
        breakdownHtml += `
            <div style="background: #f8fafc; padding: 10px 14px; border-radius: 8px; border: 1px solid #e2e8f0;">
                <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: 600; margin-bottom: 4px;">
                    <span>${actionNames[key] || key}</span>
                    <span style="color: ${color}">${count} 次 (${pct.toFixed(1)}%)</span>
                </div>
                <div style="background: #e2e8f0; height: 6px; border-radius: 3px; overflow: hidden;">
                    <div style="height: 100%; width: ${pct}%; background-color: ${color};"></div>
                </div>
            </div>
        `;
    });

    const body = document.getElementById('history-detail-body');
    body.innerHTML = `
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 25px;">
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; text-align: center;">
                <div style="font-size: 11px; color: #64748b; font-weight: 600;">挥拍总数</div>
                <div style="font-size: 20px; font-weight: 700; color: #3b82f6; margin-top: 4px;">${record.totalSwings}</div>
            </div>
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; text-align: center;">
                <div style="font-size: 11px; color: #64748b; font-weight: 600;">峰值加速度</div>
                <div style="font-size: 20px; font-weight: 700; color: #ef4444; margin-top: 4px;">${record.peakAcc}</div>
            </div>
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; text-align: center;">
                <div style="font-size: 11px; color: #64748b; font-weight: 600;">时长 / 类型</div>
                <div style="font-size: 14px; font-weight: 700; color: #1e293b; margin-top: 8px;">${record.duration} (${record.status})</div>
            </div>
        </div>

        <div style="margin-bottom: 25px;">
            <h4 style="margin: 0 0 12px 0; font-size: 14px; border-left: 4px solid #3b82f6; padding-left: 8px; color: #1e293b; font-weight: 700;">动作分布 (AI Classification)</h4>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                ${breakdownHtml}
            </div>
        </div>

        <div>
            <h4 style="margin: 0 0 12px 0; font-size: 14px; border-left: 4px solid #3b82f6; padding-left: 8px; color: #1e293b; font-weight: 700;">合加速度时序折线图快照</h4>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; background: #fff; text-align: center;">
                    <div style="font-size: 11px; color: #475569; margin-bottom: 6px; font-weight: 600;">左手腕 (Left Hand)</div>
                    <img src="${record.images.handL}" style="width: 100%; height: 110px; object-fit: contain; background: #fafafa;" />
                </div>
                <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; background: #fff; text-align: center;">
                    <div style="font-size: 11px; color: #475569; margin-bottom: 6px; font-weight: 600;">腰部重心 (Waist)</div>
                    <img src="${record.images.waist}" style="width: 100%; height: 110px; object-fit: contain; background: #fafafa;" />
                </div>
                <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; background: #fff; text-align: center;">
                    <div style="font-size: 11px; color: #475569; margin-bottom: 6px; font-weight: 600;">左腿 (Left Leg)</div>
                    <img src="${record.images.legL}" style="width: 100%; height: 110px; object-fit: contain; background: #fafafa;" />
                </div>
                <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; background: #fff; text-align: center;">
                    <div style="font-size: 11px; color: #475569; margin-bottom: 6px; font-weight: 600;">右腿 (Right Leg)</div>
                    <img src="${record.images.legR}" style="width: 100%; height: 110px; object-fit: contain; background: #fafafa;" />
                </div>
            </div>
        </div>
    `;

    modal.style.display = 'flex';
}

/* ==================== 绑定 HTML 按钮点击事件的全局接口 ==================== */

window.viewHistoryDetail = async function(id) {
    try {
        const records = await getAllRecords();
        const record = records.find(r => r.id === id);
        if (record) {
            showHistoryDetail(record);
        }
    } catch (e) {
        console.error("无法打开历史详情:", e);
    }
};

window.deleteHistoryItem = async function(id) {
    if (confirm("确定要删除这条历史记录吗？")) {
        try {
            await deleteRecord(id);
            await renderHistoryList();
        } catch (e) {
            alert("删除失败: " + e.message);
        }
    }
};

window.closeHistoryDetail = function() {
    const modal = document.getElementById('historyDetailModal');
    if (modal) modal.style.display = 'none';
};

window.clearAllHistory = async function() {
    if (confirm("警告：确定要清空本地保存的所有运动历史记录吗？此操作无法撤销。")) {
        try {
            const db = await initDB();
            const transaction = db.transaction(STORE_NAME, 'readwrite');
            const store = transaction.objectStore(STORE_NAME);
            const request = store.clear();
            request.onsuccess = async () => {
                await renderHistoryList();
                alert("历史记录已清空。");
            };
        } catch (e) {
            alert("清空失败: " + e.message);
        }
    }
};