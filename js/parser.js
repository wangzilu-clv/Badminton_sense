/**
 * 离线数据物理文本解析与滤波引擎（相对时间轴版）
 */

/**
 * 将硬件传感器设备标识名称映射到前端绑定的 4 个图形通道
 */
function mapDeviceToNode(deviceName) {
    if (!deviceName) return null;
    const name = deviceName.toUpperCase();

    if (name.includes('D5:5D:08:29:22:8A') || (name.includes('LEFT') && !name.includes('LEG'))) {
        return 'handL';
    }
    if (name.includes('DD:3A:D7:7C:18:F4') || name.includes('WAIST') || name.includes('BODY')) {
        return 'waist';
    }
    if (name.includes('FA:CA:20:22:A6:15')) {
        return 'legL';
    }
    if (name.includes('EA:08:F3:A5:30:50')) {
        return 'legR';
    }
    return null;
}

/* ==================== 信号处理与时间转换辅助函数 ==================== */

function parseTimeToMs(timeStr) {
    if (!timeStr) return null;
    try {
        if (timeStr.includes('T')) {
            return new Date(timeStr).getTime();
        }
        const parts = timeStr.split(':');
        if (parts.length === 3) {
            const hrs = parseInt(parts[0], 10);
            const mins = parseInt(parts[1], 10);
            const secs = parseFloat(parts[2]);
            return ((hrs * 60 + mins) * 60 + secs) * 1000;
        }
    } catch (e) {}
    return null;
}

function estimateFs(timeStrings) {
    if (timeStrings.length < 2) return 50;

    const first = parseTimeToMs(timeStrings[0]);
    const last = parseTimeToMs(timeStrings[timeStrings.length - 1]);

    if (first !== null && last !== null && last > first) {
        const durationSec = (last - first) / 1000;
        return timeStrings.length / durationSec;
    }
    return 50;
}

export function medianFilter3(arr) {
    const len = arr.length;
    if (len === 0) return [];
    const result = new Array(len);
    
    result[0] = arr[0];
    result[len - 1] = arr[len - 1];
    
    for (let i = 1; i < len - 1; i++) {
        const a = arr[i - 1];
        const b = arr[i];
        const c = arr[i + 1];
        if ((a - b) * (c - a) >= 0) {
            result[i] = a;
        } else if ((b - a) * (c - b) >= 0) {
            result[i] = b;
        } else {
            result[i] = c;
        }
    }
    return result;
}

function getSavgolCoeffs(windowSize) {
    const M = (windowSize - 1) / 2;
    const coeffs = [];
    const denom = (2 * M - 1) * (2 * M + 1) * (2 * M + 3);
    for (let i = -M; i <= M; i++) {
        const num = 3 * (3 * M * M + 3 * M - 1 - 5 * i * i);
        coeffs.push(num / denom);
    }
    return coeffs;
}

export function savgolFilter(arr, windowSize) {
    const len = arr.length;
    if (len === 0) return [];
    
    if (windowSize > len) {
        windowSize = len % 2 === 0 ? len - 1 : len;
    }
    if (windowSize < 3) return [...arr];

    const coeffs = getSavgolCoeffs(windowSize);
    const halfWin = (windowSize - 1) / 2;
    const result = new Array(len);

    for (let i = 0; i < len; i++) {
        let val = 0;
        for (let j = -halfWin; j <= halfWin; j++) {
            let idx = i + j;
            if (idx < 0) idx = 0;
            if (idx >= len) idx = len - 1;
            val += arr[idx] * coeffs[j + halfWin];
        }
        result[i] = val;
    }
    return result;
}

export function filterTriaxialToMagnitude(xArr, yArr, zArr, fs) {
    if (xArr.length === 0) return [];
    const win = fs > 15 ? Math.min((Math.floor(fs * 0.1) | 1), 15) : 3;

    const x_f = savgolFilter(medianFilter3(xArr), win);
    const y_f = savgolFilter(medianFilter3(yArr), win);
    const z_f = savgolFilter(medianFilter3(zArr), win);

    const mag_f = [];
    for (let i = 0; i < x_f.length; i++) {
        mag_f.push(Math.sqrt(x_f[i]**2 + y_f[i]**2 + z_f[i]**2));
    }
    return mag_f;
}

/* ==================== 统一解析主接口 ==================== */

export function parseSensorData(text) {
    const lines = text.split('\n');
    
    const rawData = {
        handL: { times: [], x: [], y: [], z: [], gx: [], gy: [], gz: [] },
        waist: { times: [], x: [], y: [], z: [], gx: [], gy: [], gz: [] },
        legL:  { times: [], x: [], y: [], z: [], gx: [], gy: [], gz: [] },
        legR:  { times: [], x: [], y: [], z: [], gx: [], gy: [], gz: [] }
    };

    let colIndex = { time: 0, deviceName: 1, ax: 2, ay: 3, az: 4, gx: 5, gy: 6, gz: 7 };

    for (let line of lines) {
        line = line.trim();
        if (!line) continue;

        const parts = line.split('\t');
        if (parts.length < 5) continue;

        if (line.includes('时间') && line.includes('设备名称')) {
            colIndex.time = parts.indexOf('时间');
            colIndex.deviceName = parts.indexOf('设备名称');
            colIndex.ax = parts.indexOf('加速度X(g)');
            colIndex.ay = parts.indexOf('加速度Y(g)');
            colIndex.az = parts.indexOf('加速度Z(g)');
            colIndex.gx = parts.indexOf('角速度X(°/s)');
            colIndex.gy = parts.indexOf('角速度Y(°/s)');
            colIndex.gz = parts.indexOf('角速度Z(°/s)');
            continue;
        }

        if (parts[colIndex.time] === '时间') continue;

        const timeStr = parts[colIndex.time];
        const deviceName = parts[colIndex.deviceName];
        const ax = parseFloat(parts[colIndex.ax]);
        const ay = parseFloat(parts[colIndex.ay]);
        const az = parseFloat(parts[colIndex.az]);
        const gx = parseFloat(parts[colIndex.gx]);
        const gy = parseFloat(parts[colIndex.gy]);
        const gz = parseFloat(parts[colIndex.gz]);

        if (!deviceName || isNaN(ax) || isNaN(ay) || isNaN(az)) {
            continue;
        }

        const nodeKey = mapDeviceToNode(deviceName);
        if (!nodeKey) continue; 

        rawData[nodeKey].times.push(timeStr);
        rawData[nodeKey].x.push(ax);
        rawData[nodeKey].y.push(ay);
        rawData[nodeKey].z.push(az);
        rawData[nodeKey].gx.push(isNaN(gx) ? 0 : gx);
        rawData[nodeKey].gy.push(isNaN(gy) ? 0 : gy);
        rawData[nodeKey].gz.push(isNaN(gz) ? 0 : gz);
    }

    const result = {
        handL: { labels: [], values: [], rawDataRecords: [] },
        waist: { labels: [], values: [], rawDataRecords: [] },
        legL:  { labels: [], values: [], rawDataRecords: [] },
        legR:  { labels: [], values: [], rawDataRecords: [] }
    };

    for (const nodeKey of Object.keys(rawData)) {
        const node = rawData[nodeKey];
        if (node.x.length === 0) continue;

        const fs = estimateFs(node.times);

        const relativeLabels = [];
        const firstMs = parseTimeToMs(node.times[0]);

        for (let i = 0; i < node.times.length; i++) {
            const currentMs = parseTimeToMs(node.times[i]);
            if (firstMs !== null && currentMs !== null) {
                const relativeSec = (currentMs - firstMs) / 1000;
                relativeLabels.push(relativeSec.toFixed(1) + 's');
            } else {
                const relativeSec = i / fs;
                relativeLabels.push(relativeSec.toFixed(1) + 's');
            }
        }
        result[nodeKey].labels = relativeLabels;

        // 1. 独立应用中值 + SG 滤波
        const win = fs > 15 ? Math.min((Math.floor(fs * 0.1) | 1), 15) : 3;
        const x_filtered = savgolFilter(medianFilter3(node.x), win);
        const y_filtered = savgolFilter(medianFilter3(node.y), win);
        const z_filtered = savgolFilter(medianFilter3(node.z), win);

        // 2. 解算滤波合加速度
        const mag_filtered_list = [];
        for (let i = 0; i < x_filtered.length; i++) {
            mag_filtered_list.push(Math.sqrt(x_filtered[i]**2 + y_filtered[i]**2 + z_filtered[i]**2));
        }
        result[nodeKey].values = mag_filtered_list; 

        // 3. 写入有序记录：使用滤波后的合加速度减 1g，并取绝对值
        const records = [];
        for (let i = 0; i < node.x.length; i++) {
            const ax_raw = node.x[i];
            const ay_raw = node.y[i];
            const az_raw = node.z[i];
            const gx = node.gx[i];
            const gy = node.gy[i];
            const gz = node.gz[i];
            
            // 关键点：对滤波后的加速度扣除 1g 偏置，并取绝对值
            const filteredMag = mag_filtered_list[i];
            const dynamicAcc = Math.abs(filteredMag - 1.0); 

            records.push([
                ax_raw,     // 原始 ax
                ay_raw,     // 原始 ay
                az_raw,     // 原始 az
                dynamicAcc, // 使用滤波后三轴合加速度解算（取绝对值）
                gx,         // 原始 gx
                gy,         // 原始 gy
                gz          // 原始 gz
            ]);
        }
        result[nodeKey].rawDataRecords = records;
    }

    return result;
}