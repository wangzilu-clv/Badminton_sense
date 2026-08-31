# BadmintonSense 🏸 — 运动感知推理展示系统

基于 **腕部（WTleft/WTwaist）** 与 **腿部（FA/EA）** 多传感器融合的羽毛球动作识别系统。

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                     数据流总览                           │
├──────────────┐    ┌─────────────────┐    ┌─────────────┤
│  sender.py   │───→│ receiver_backend│───→│  前端页面    │
│ (CSV发送端)  │ WS │.py (推理后端)   │ WS │ (index.html) │
│   :8080      │    │ :8090 + :8081   │    │ 文本结果展示  │
└──────────────┘    └─────────────────┘    └─────────────┘
```

### 三个核心组件

| 组件 | 端口 | 功能 |
|------|------|------|
| **sender.py** (发送端) | WebSocket :8080 | 读取 CSV 数据文件，按 sample_id 分组构建特征矩阵，逐个发送到接收端 |
| **receiver_backend.py** (接收推理端) | WS :8090 + HTTP :8081 | 接收 sender 数据 → 加载 `best_joint_model.pth` 推理 → 推送结果到前端；同时提供 HTTP 静态文件服务 |
| **前端页面** (浏览器) | HTTP :8081 | 展示推理结果（预测动作、置信度、正确率、历史记录） |

## 项目文件结构

```
e:/Badminton_Sense/
├── sender.py                   # 数据发送端 (Tkinter GUI)
├── receiver_backend.py         # 接收推理后端 (WebSocket + 模型推理)
├── best_joint_model.pth        # 预训练模型权重 (7分类)
├── test.csv                    # 测试数据 (可选)
├── index.html                  # 前端页面 (推理结果展示)
├── style.css                   # 前端样式
├── README.md                   # 本文件
└── js/
    ├── main.js                 # 前端主逻辑 (WebSocket连接 + 结果展示)
    ├── parser.js               # 传感器数据解析与滤波引擎
    ├── recognition.js          # 离线/在线动作识别模块
    ├── charts.js               # Chart.js 图表管理组件
    └── history.js              # 历史记录管理 (IndexedDB)
```

## 快速上手（单机）

### 0. 环境准备

```bash
# 安装 Python 依赖
pip install numpy pandas torch websockets
```

### 1. 启动发送端 (sender.py)

```bash
python sender.py
```

- 点击 **"选择 CSV 数据文件"** 按钮，选择 `test.csv` 或其他符合格式的 CSV 文件
- 发送模式选择：
  - **逐个动作发送**：每个动作间有停顿（间隔可调），适合观察实时推理效果
  - **全部动作高速发送**：快速推送所有动作
- 发送间隔倍率滑块：控制动作间停顿延时（默认 1.0x = 3 秒）

### 2. 启动接收推理端 (receiver_backend.py)

```bash
python receiver_backend.py
```

- 自动加载 `best_joint_model.pth` 模型
- 自动连接 sender（默认 `ws://localhost:8080`）
- 提供：
  - **HTTP 静态文件服务**：`http://localhost:8081/`（承载前端页面）
  - **WebSocket 推送服务**：`ws://localhost:8090/`（向前端推送推理结果）

### 3. 打开前端页面

在浏览器中访问：

```
http://localhost:8081/
```

- 点击 **"连接接收端"** 按钮，连接到 `ws://localhost:8090`
- 连接成功后，sender 发送的每个动作都会触发推理并在页面上展示结果

## 双机通信

系统支持将 sender（发送端）和 receiver_backend（接收推理端）部署在**两台不同的电脑**上，通过局域网 WebSocket 通信。这在数据采集设备与推理展示设备分离的场景下非常有用。

### 网络拓扑

```
┌────────── 电脑 A（数据发送端） ──────────┐
│  sender.py                                │
│  WebSocket 服务端 :8080                   │
│  IP: 192.168.1.100 (示例)                 │
└──────────────┬────────────────────────────┘
               │ 局域网 WebSocket 连接
               ▼
┌────────── 电脑 B（推理+展示端） ──────────┐
│  receiver_backend.py                      │
│  ├─ WebSocket 客户端 → 连接电脑 A :8080   │
│  ├─ WebSocket 服务端 :8090 (推送给前端)   │
│  └─ HTTP 静态文件服务 :8081 (前端页面)    │
│  IP: 192.168.1.200 (示例)                 │
└──────────────┬────────────────────────────┘
               │
               ▼
        浏览器访问 http://192.168.1.200:8081/
```

### 操作步骤

#### 电脑 A — 发送端（运行 sender.py）

1. **不指定 host 直接启动**（sender 默认监听 `0.0.0.0:8080`，即局域网所有网卡）：

   ```bash
   python sender.py
   ```

2. 在 GUI 中选择 CSV 数据文件
3. **无需做其他操作**，等待电脑 B 连接即可
4. 确认电脑 A 的局域网 IP（Windows 上用 `ipconfig` 查看）

#### 电脑 B — 接收推理端（运行 receiver_backend.py）

1. **启动时指定电脑 A 的 IP 地址**：

   ```bash
   # 假设电脑 A 的 IP 为 192.168.1.100
   python receiver_backend.py --sender-host 192.168.1.100
   ```

2. 启动后会自动连接电脑 A 的 sender，控制台会显示：
   ```
   ✓ 已连接到 sender (ws://192.168.1.100:8080)
   ```

3. 此时 receiver_backend 同时在本机提供：
   - **HTTP 静态页面**: `http://192.168.1.200:8081/`
   - **WebSocket 推送**: `ws://192.168.1.200:8090/`

#### 浏览器 — 打开前端页面

- 在电脑 B 上访问：`http://localhost:8081/`
- 或在**任何联网的电脑**上访问：`http://192.168.1.200:8081/`
- 点击 **"连接接收端"**，地址栏保持 `ws://localhost:8090`（如果浏览器和 receiver 在同一台机器）
- 如果在**第三台电脑**上打开页面，则需将 WebSocket 地址改为 `ws://192.168.1.200:8090`

### 防火墙注意事项

两台电脑在同一局域网时，如无法连接，请检查：

- **Windows 防火墙**：确保 Python 被允许通过防火墙，或手动添加入站规则允许端口 `8080`（sender）和 `8090、8081`（receiver）
- **物理网络**：确认两台电脑能互相 ping 通
- **端口占用**：如端口被占用，可用 `--sender-port`、`--frontend-port`、`--http-port` 自定义端口

### 双机通信端口汇总

| 端口 | 方向 | 说明 |
|------|------|------|
| **8080** | 电脑 A → 电脑 B | sender 发送原始传感器数据 |
| **8090** | 电脑 B → 浏览器 | receiver 推送推理结果到前端 |
| **8081** | 电脑 B → 浏览器 | HTTP 静态页面服务 |

### 常见问题

**Q: 电脑 B 提示 "Connection refused"？**
A: 检查电脑 A 的防火墙是否放行了端口 8080。可以在电脑 A 上用 `telnet 192.168.1.100 8080` 测试端口是否可达（Windows 需先启用 Telnet 功能）。

**Q: 页面打开后 WebSocket 连接不上？**
A: 如果浏览器与 receiver 不在同一台机器，需将页面 WebSocket 地址从 `localhost:8090` 改为 receiver 所在机器的实际 IP，如 `ws://192.168.1.200:8090`。

## 识别动作类别 (7类)

| 标签 | 动作名称 | 说明 |
|------|----------|------|
| 1 | **正手发球** | Forehand Serve |
| 2 | **反手发球** | Backhand Serve |
| 3 | **正手平抽** | Forehand Drive |
| 4 | **反手平抽** | Backhand Drive |
| 5 | **正手高远球** | Forehand Clear |
| 6 | **反手高远球** | Backhand Clear |
| 7 | **杀球** | Smash |

## 前端页面功能

- **连接状态指示器**：显示 WebSocket 连接状态
- **统计看板**：已接收动作数、预测正确/错误数、正确率
- **推理结果卡片**：
  - 预测结果（动作名称 + 颜色标识）
  - 真实标签（如果数据中包含 ground truth）
  - 置信度（百分比 + 进度条，颜色分级：绿 ≥ 80%、黄 ≥ 60%、红 < 60%）
  - ✅/❌ 图标指示预测是否正确
- **历史记录列表**：所有推理结果按时间倒序排列，可清空

## CSV 数据格式

CSV 文件需要包含以下列（每行一个时间步的传感器读数）：

| 列名 | 说明 |
|------|------|
| `sample_id` | 样本/动作 ID（同一动作的所有行共享） |
| `group` | 组别：`A`（WTleft/WTwaist）或 `B`（FA/EA） |
| `Body_Part` | 传感器位置：`WTleft`, `WTwaist`, `FA`, `EA` |
| `time_step` | 时间步序号 |
| `X, Y, Z` | 加速度三轴分量 |
| `GX, GY, GZ` | 角速度三轴分量 |
| `label` | 动作类别标签 (1-7) |
| `len_WTleft` | WTleft 传感器序列长度 |
| `len_WTwaist` | WTwaist 传感器序列长度 |
| `len_FA` | FA 传感器序列长度 |
| `len_EA` | EA 传感器序列长度 |

## 传感器对应关系

| 传感器 | 安装位置 | 所属组 | 通道 |
|--------|----------|--------|------|
| WTleft | 左手腕 | A | 0-5 (X, Y, Z, GX, GY, GZ) |
| WTwaist | 腰部 | A | 6-11 (X, Y, Z, GX, GY, GZ) |
| FA | 左腿（前） | B | 0-5 (X, Y, Z, GX, GY, GZ) |
| EA | 右腿（后） | B | 6-11 (X, Y, Z, GX, GY, GZ) |

## 模型架构

双分支联合分类器（Joint Classifier），包含：

- **TCN 编码器**（组 A：WTleft + WTwaist）：时序卷积网络，5 层 TemporalBlock（膨胀率 1,2,4,8,16），输出 256 维特征
- **WideCNN 编码器**（组 B：FA + EA）：宽核 CNN，3 层 Conv1d（核大小 15,11,7）+ 池化，输出 128 维特征
- **分类头**：拼接 384 维特征 → 256 → 128 → 7 分类输出
