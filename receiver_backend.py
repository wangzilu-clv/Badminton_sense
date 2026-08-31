"""
receiver_backend.py — 接收端后端（第三阶段：接收数据 + 模型推理 + 推送前端）

架构:
  sender.py (WebSocket 服务端 :8080)
      ↓ WebSocket
  receiver_backend.py (WebSocket 客户端 + 模型推理 + WebSocket 服务端 :8090 + HTTP 静态文件 :8081)
      ├─ 接收原始动作数据 (g_a_feat, g_b_feat, ...)
      ├─ 加载 best_joint_model.pth 做推理
      ├─ 推送推理结果到前端
      └─ 每个动作立即处理，无延时

前端:
  http://<receiver-host>:8081/   ← HTTP 静态文件服务
  ws://<receiver-host>:8090/     ← WS 推送推理结果

用法:
  python receiver_backend.py [--sender-host HOST] [--sender-port PORT]
                             [--frontend-port PORT] [--http-port PORT]

示例:
  python receiver_backend.py                                # 连接本地 sender
  python receiver_backend.py --sender-host 192.168.x.x       # 连接远程 sender
"""

import asyncio
import json
import argparse
import os
import sys
import threading
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

import numpy as np
import torch
import torch.nn as nn
import websockets

# ==================== 路径配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, 'best_joint_model.pth')
NUM_CLASSES = 7
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# 传感器配置（与 predict.py 一致）
group_a = ['WTleft', 'WTwaist']
group_b = ['FA', 'EA']
sensor_cols = ['X', 'Y', 'Z', 'GX', 'GY', 'GZ']

A_INPUT_SIZE = len(group_a) * len(sensor_cols)   # 12
A_BOTTLENECK = 256
B_INPUT_SIZE = len(group_b) * len(sensor_cols)   # 12
B_BOTTLENECK = 128
DROPOUT = 0.4

LABEL_NAMES = {
    1: "正手发球",
    2: "反手发球",
    3: "正手平抽",
    4: "反手平抽",
    5: "正手高远球",
    6: "反手高远球",
    7: "杀球",
}

# 前端 WebSocket 客户端集合
frontend_clients = set()


# =====================================================================
#  模型定义（与 predict.py 完全一致）
# =====================================================================

class Chomp1d(nn.Module):
    def __init__(self, chomp_size):
        super().__init__()
        self.chomp_size = chomp_size

    def forward(self, x):
        return x[:, :, :-self.chomp_size]


class TemporalBlock(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=3, dilation=1, dropout=0.2):
        super().__init__()
        padding = (kernel_size - 1) * dilation

        self.conv1 = nn.Conv1d(in_channels, out_channels, kernel_size,
                               dilation=dilation, padding=padding)
        self.chomp1 = Chomp1d(padding)
        self.bn1 = nn.BatchNorm1d(out_channels)
        self.relu1 = nn.ReLU()
        self.dropout1 = nn.Dropout(dropout)

        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size,
                               dilation=dilation, padding=padding)
        self.chomp2 = Chomp1d(padding)
        self.bn2 = nn.BatchNorm1d(out_channels)
        self.relu2 = nn.ReLU()
        self.dropout2 = nn.Dropout(dropout)

        self.downsample = (nn.Conv1d(in_channels, out_channels, kernel_size=1)
                           if in_channels != out_channels else None)

    def forward(self, x):
        out = self.conv1(x)
        out = self.chomp1(out)
        out = self.bn1(out)
        out = self.relu1(out)
        out = self.dropout1(out)

        out = self.conv2(out)
        out = self.chomp2(out)
        out = self.bn2(out)
        out = self.relu2(out)
        out = self.dropout2(out)

        residual = self.downsample(x) if self.downsample is not None else x
        return self.relu1(out + residual)


class TCNEncoder(nn.Module):
    def __init__(self, input_size=12, bottleneck=256, dropout=0.2):
        super().__init__()
        self.input_size = input_size
        self.bottleneck = bottleneck

        self.proj = nn.Conv1d(input_size, 32, kernel_size=1)

        self.tcn = nn.Sequential(
            TemporalBlock(32, 32, kernel_size=3, dilation=1, dropout=dropout),
            TemporalBlock(32, 32, kernel_size=3, dilation=2, dropout=dropout),
            TemporalBlock(32, 32, kernel_size=3, dilation=4, dropout=dropout),
            TemporalBlock(32, 64, kernel_size=3, dilation=8, dropout=dropout),
            TemporalBlock(64, 64, kernel_size=3, dilation=16, dropout=dropout),
        )

        self.fc = nn.Linear(64, bottleneck)

    def forward(self, x, lengths):
        x = x.transpose(1, 2)
        x = self.proj(x)
        x = self.tcn(x)

        batch_size, channels, T = x.shape
        device = x.device

        t_valid = lengths
        mask = torch.arange(T, device=device).unsqueeze(0).expand(batch_size, -1)
        mask = (mask < t_valid.unsqueeze(1)).float().unsqueeze(1)

        x = x * mask
        x = x.sum(dim=2) / (t_valid.float().unsqueeze(1) + 1e-8)

        features = self.fc(x)
        return features


class WideCNNEncoder(nn.Module):
    def __init__(self, input_size=12, bottleneck=128):
        super().__init__()
        self.input_size = input_size
        self.bottleneck = bottleneck

        self.cnn = nn.Sequential(
            nn.Conv1d(input_size, 32, kernel_size=15, padding=7),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2),

            nn.Conv1d(32, 48, kernel_size=11, padding=5),
            nn.BatchNorm1d(48),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2),

            nn.Conv1d(48, 64, kernel_size=7, padding=3),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2),
        )

        self.fc = nn.Linear(64, bottleneck)

    def forward(self, x, lengths):
        x = x.transpose(1, 2)
        x = self.cnn(x)

        batch_size, channels, T = x.shape
        device = x.device

        t_valid = torch.div(lengths, 8, rounding_mode='floor')
        mask = torch.arange(T, device=device).unsqueeze(0).expand(batch_size, -1)
        mask = (mask < t_valid.unsqueeze(1)).float().unsqueeze(1)

        x = x * mask
        x = x.sum(dim=2) / (t_valid.float().unsqueeze(1) + 1e-8)

        features = self.fc(x)
        return features


class JointClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder_a = TCNEncoder(
            input_size=A_INPUT_SIZE, bottleneck=A_BOTTLENECK, dropout=0.2
        )
        self.encoder_b = WideCNNEncoder(
            input_size=B_INPUT_SIZE, bottleneck=B_BOTTLENECK
        )
        concat_size = A_BOTTLENECK + B_BOTTLENECK  # 384
        self.classifier = nn.Sequential(
            nn.Linear(concat_size, 256),
            nn.ReLU(),
            nn.Dropout(DROPOUT),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Dropout(DROPOUT * 0.5),
            nn.Linear(128, NUM_CLASSES)
        )

    def forward(self, group_a_feat, group_b_feat, lengths_a, lengths_b):
        feat_a = self.encoder_a(group_a_feat, lengths_a)  # (B, 256)
        feat_b = self.encoder_b(group_b_feat, lengths_b)  # (B, 128)
        concat = torch.cat([feat_a, feat_b], dim=1)       # (B, 384)
        output = self.classifier(concat)                   # (B, 7)
        return output


# =====================================================================
#  日志
# =====================================================================

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# =====================================================================
#  模型加载
# =====================================================================

def load_model(model_path: str) -> JointClassifier:
    log(f"加载模型: {model_path}")
    if not os.path.exists(model_path):
        log(f"错误：模型文件不存在！{model_path}")
        log("请将 best_joint_model.pth 放在项目根目录。")
        sys.exit(1)

    model = JointClassifier().to(DEVICE)
    model.load_state_dict(torch.load(model_path, map_location=DEVICE))
    model.eval()
    log(f"模型加载成功！使用设备: {DEVICE}")
    return model


# =====================================================================
#  推理函数
# =====================================================================

def predict_action(model: JointClassifier, action_data: dict) -> dict:
    g_a_feat = np.array(action_data["g_a_feat"], dtype=np.float32)  # (T_A, 12)
    g_b_feat = np.array(action_data["g_b_feat"], dtype=np.float32)  # (T_B, 12)
    seq_len_a = g_a_feat.shape[0]
    seq_len_b = g_b_feat.shape[0]

    g_a_tensor = torch.from_numpy(g_a_feat).unsqueeze(0).to(DEVICE)  # (1, T_A, 12)
    g_b_tensor = torch.from_numpy(g_b_feat).unsqueeze(0).to(DEVICE)  # (1, T_B, 12)
    len_a_tensor = torch.LongTensor([seq_len_a]).to(DEVICE)
    len_b_tensor = torch.LongTensor([seq_len_b]).to(DEVICE)

    with torch.no_grad():
        outputs = model(g_a_tensor, g_b_tensor, len_a_tensor, len_b_tensor)
        probs = torch.softmax(outputs, dim=1)
        confidence, predicted = torch.max(probs, 1)

    predicted_label = int(predicted.item()) + 1
    confidence_val = float(confidence.item())

    result = action_data.copy()
    result["predicted_label"] = predicted_label
    result["confidence"] = round(confidence_val, 4)
    result["predicted_label_name"] = LABEL_NAMES.get(predicted_label, f"Unknown ({predicted_label})")

    true_label = action_data.get("label", -1)
    result["label_name"] = LABEL_NAMES.get(true_label, f"Unknown ({true_label})")

    return result


# =====================================================================
#  打印推理结果
# =====================================================================

def print_prediction(result: dict, action_num: int):
    sample_id = result.get("sample_id", "N/A")
    label = result.get("label", "N/A")
    label_name = result.get("label_name", "N/A")
    predicted = result.get("predicted_label", "N/A")
    predicted_name = result.get("predicted_label_name", "N/A")
    confidence = result.get("confidence", 0.0)
    g_a_shape = [len(result["g_a_feat"]), len(result["g_a_feat"][0])] if result.get("g_a_feat") else [0, 0]
    g_b_shape = [len(result["g_b_feat"]), len(result["g_b_feat"][0])] if result.get("g_b_feat") else [0, 0]

    is_correct = (label == predicted)

    print()
    print("=" * 70)
    print(f"  动作 #{action_num}  |  sample_id: {sample_id}")
    print(f"  {'─' * 66}")
    print(f"  输入数据:")
    print(f"    g_a_feat: ({g_a_shape[0]}, {g_a_shape[1]})  — 组A (WTleft + WTwaist)")
    print(f"    g_b_feat: ({g_b_shape[0]}, {g_b_shape[1]})  — 组B (FA + EA)")
    print(f"  {'─' * 66}")
    print(f"  推理结果:")
    print(f"    ├─ 真实标签:    {label} ({label_name})")
    print(f"    ├─ 预测标签:    {predicted} ({predicted_name})")
    print(f"    ├─ 置信度:      {confidence:.4f} ({confidence*100:.2f}%)")
    if is_correct and label != "N/A":
        print(f"    └─ 结果: ✅ 预测正确！")
    elif label != "N/A":
        print(f"    └─ 结果: ❌ 预测错误")
    else:
        print(f"    └─ 结果: (无真实标签参考)")
    print("=" * 70)


# =====================================================================
#  前端 WebSocket 广播
# =====================================================================

async def frontend_ws_handler(websocket):
    """处理前端 WebSocket 连接"""
    client_addr = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    frontend_clients.add(websocket)
    log(f"前端已连接: {client_addr}  (当前在线: {len(frontend_clients)})")
    try:
        async for _ in websocket:
            pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        frontend_clients.discard(websocket)
        log(f"前端已断开: {client_addr}  (当前在线: {len(frontend_clients)})")


async def broadcast_to_frontend(result: dict):
    """将推理结果推送到所有连接的前端"""
    if not frontend_clients:
        log("没有前端连接，跳过推送")
        return

    # 构造精简的推送消息（不含原始大数组）
    frontend_msg = {
        "type": "prediction",
        "sample_id": result.get("sample_id", "N/A"),
        "label": result.get("label", "N/A"),
        "label_name": result.get("label_name", ""),
        "predicted_label": result.get("predicted_label", "N/A"),
        "predicted_label_name": result.get("predicted_label_name", ""),
        "confidence": result.get("confidence", 0.0),
        "is_correct": result.get("label", "N/A") == result.get("predicted_label", "N/A"),
    }

    message = json.dumps(frontend_msg, ensure_ascii=False)
    await asyncio.gather(
        *[client.send(message) for client in frontend_clients.copy()],
        return_exceptions=True
    )


# =====================================================================
#  处理 sender 消息
# =====================================================================

async def handle_sender_message(model: JointClassifier, message: str, action_count: int):
    """解析 sender 消息，执行推理，推送前端，延时 3 秒"""
    try:
        data = json.loads(message)
    except json.JSONDecodeError as e:
        log(f"JSON 解析失败: {e}")
        return action_count

    if "error" in data:
        log(f"收到 sender 错误: {data['error']}")
        return action_count

    if "g_a_feat" in data and "g_b_feat" in data:
        action_count += 1

        # 1. 推理
        t_start = datetime.now()
        result = predict_action(model, data)
        elapsed = (datetime.now() - t_start).total_seconds()

        # 2. 打印结果到控制台
        print_prediction(result, action_count)
        log(f"推理耗时: {elapsed*1000:.1f}ms")

        # 3. 推送结果到前端
        await broadcast_to_frontend(result)

    return action_count


# =====================================================================
#  连接 sender
# =====================================================================

async def connect_to_sender(model: JointClassifier, sender_host: str, sender_port: int):
    """连接到 sender，接收数据并推理"""
    uri = f"ws://{sender_host}:{sender_port}"
    log(f"正在连接 sender: {uri}")

    while True:
        try:
            async with websockets.connect(uri) as websocket:
                log(f"✓ 已连接到 sender ({uri})")
                action_count = 0

                async for message in websocket:
                    action_count = await handle_sender_message(model, message, action_count)

        except (ConnectionRefusedError, OSError) as e:
            log(f"连接 sender 失败: {e}")
            log("将在 5 秒后重试...")
            await asyncio.sleep(5)

        except websockets.exceptions.ConnectionClosed:
            log(f"与 sender 的连接已断开")
            log("将在 5 秒后重试...")
            await asyncio.sleep(5)


# =====================================================================
#  HTTP 静态文件服务
# =====================================================================

def start_http_server(http_port: int):
    """在后台线程启动 HTTP 静态文件服务器"""
    class StaticHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=BASE_DIR, **kwargs)

        def log_message(self, format, *args):
            pass  # 抑制 HTTP 日志

    server = HTTPServer(('0.0.0.0', http_port), StaticHandler)
    log(f"HTTP 静态文件服务已启动: http://0.0.0.0:{http_port}/")
    server.serve_forever()


# =====================================================================
#  程序入口
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="BadmintonSense 接收端后端 — 数据接收 + 模型推理 + 前端推送")
    parser.add_argument("--sender-host", default="10.208.80.5",
                        help="sender 的 WebSocket 地址 (默认: localhost)")
    parser.add_argument("--sender-port", type=int, default=8080,
                        help="sender 的 WebSocket 端口 (默认: 8080)")
    parser.add_argument("--frontend-port", type=int, default=8090,
                        help="前端 WebSocket 推送端口 (默认: 8090)")
    parser.add_argument("--http-port", type=int, default=8081,
                        help="前端 HTTP 静态文件端口 (默认: 8081)")
    args = parser.parse_args()

    print("=" * 70)
    print("  BadmintonSense 接收端后端 v3.0")
    print("  功能: 接收数据 + 模型推理 + 前端推送")
    print(f"  设备: {DEVICE}")
    print(f"  Sender:     ws://{args.sender_host}:{args.sender_port}")
    print(f"  前端 WS:    ws://0.0.0.0:{args.frontend_port}")
    print(f"  前端 HTTP:  http://0.0.0.0:{args.http_port}")
    print("=" * 70)

    # 加载模型
    model = load_model(MODEL_PATH)

    # 启动 HTTP 静态文件服务（后台线程）
    http_thread = threading.Thread(
        target=start_http_server,
        args=(args.http_port,),
        daemon=True
    )
    http_thread.start()

    async def main_async():
        # 启动前端 WebSocket 服务端
        frontend_server = await websockets.serve(
            frontend_ws_handler,
            '0.0.0.0',
            args.frontend_port
        )
        log(f"前端 WebSocket 服务已启动: ws://0.0.0.0:{args.frontend_port}")

        # 连接 sender 并开始处理
        await connect_to_sender(model, args.sender_host, args.sender_port)

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        log("\n⏹ 程序已停止")


if __name__ == "__main__":
    main()
