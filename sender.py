import asyncio
import json
import os
import threading
from datetime import datetime
import websockets
import pandas as pd
import numpy as np

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.scrolledtext as scrolledtext

# ============ 配色方案 (同步网页端 style.css) ============
COLOR_BG = "#f4f7f6"          # 网页 background-color
COLOR_CARD_BG = "#ffffff"     # 网页 card-bg
COLOR_PRIMARY = "#1e293b"     # 网页 primary-accent (深板岩)
COLOR_BLUE = "#3b82f6"        # 网页 info-blue
COLOR_TEXT_MAIN = "#334155"   # 网页 text-main
COLOR_TEXT_LIGHT = "#94a3b8"  # 网页 text-light
COLOR_BORDER = "#e2e8f0"      # 网页 border-color
COLOR_CONSOLE_BG = "#1e293b"  # 控制台底色 (匹配 primary-accent 保持一致性)

WS_HOST = '0.0.0.0'
WS_PORT = 8080


def parse_csv_actions(filepath):
    """
    完全参照 example_load.py 的 load_test_csv() 逻辑解析 CSV。

    CSV 预期列:
        set_name, sample_id, group, Body_Part, time_step,
        X, Y, Z, GX, GY, GZ, label, source_file, action_id,
        len_WTleft, len_WTwaist, len_FA, len_EA

    返回值: list of dict, 每个 dict 对应一个 sample_id（一个动作）:
        {
            "sample_id": str,            # 样本/动作 ID
            "g_a_feat": [[float]],       # 组A (WTleft+WTwaist) 特征矩阵, shape=(T, 12)
            "g_b_feat": [[float]],       # 组B (FA+EA) 特征矩阵, shape=(T, 12)
            "g_a_lens": [int, int],      # [len_wtleft, len_wtwaist]
            "g_b_lens": [int, int],      # [len_fa, len_ea]
            "label": int                 # 动作类别标签
        }
    """
    if not filepath or not os.path.exists(filepath):
        return []

    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        print(f"[parse_csv_actions] 读取 CSV 失败: {e}")
        return []

    actions = []

    # 按 sample_id 分组（一个 sample_id 代表一个完整的动作）
    for sample_id, group in df.groupby('sample_id'):
        group = group.reset_index(drop=True)

        # ---- 元信息 ----
        label = int(group['label'].iloc[0])
        len_wtleft  = int(group['len_WTleft'].iloc[0])
        len_wtwaist = int(group['len_WTwaist'].iloc[0])
        len_fa      = int(group['len_FA'].iloc[0])
        len_ea      = int(group['len_EA'].iloc[0])

        # ---- 组A: WTleft(0-5通道) + WTwaist(6-11通道) ----
        a_data = group[group['group'] == 'A']
        max_len_a = int(a_data['time_step'].max()) + 1
        g_a_feat = np.zeros((max_len_a, 12), dtype=np.float32)

        for _, row in a_data.iterrows():
            t = int(row['time_step'])
            sensor = row['Body_Part']
            vals = np.array([
                row['X'], row['Y'], row['Z'],
                row['GX'], row['GY'], row['GZ']
            ], dtype=np.float32)
            if sensor == 'WTleft':
                g_a_feat[t, 0:6] = vals
            else:  # WTwaist
                g_a_feat[t, 6:12] = vals

        # ---- 组B: FA(0-5通道) + EA(6-11通道) ----
        b_data = group[group['group'] == 'B']
        max_len_b = int(b_data['time_step'].max()) + 1
        g_b_feat = np.zeros((max_len_b, 12), dtype=np.float32)

        for _, row in b_data.iterrows():
            t = int(row['time_step'])
            sensor = row['Body_Part']
            vals = np.array([
                row['X'], row['Y'], row['Z'],
                row['GX'], row['GY'], row['GZ']
            ], dtype=np.float32)
            if sensor == 'FA':
                g_b_feat[t, 0:6] = vals
            else:  # EA
                g_b_feat[t, 6:12] = vals

        g_a_lens = [len_wtleft, len_wtwaist]
        g_b_lens = [len_fa, len_ea]

        actions.append({
            "sample_id": str(sample_id),
            "g_a_feat": g_a_feat.tolist(),   # numpy → list 用于 JSON 序列化
            "g_b_feat": g_b_feat.tolist(),   # shape (T, 12) 每个元素是 12 个 float
            "g_a_lens": g_a_lens,
            "g_b_lens": g_b_lens,
            "label": label
        })

    return actions


class SenderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("BadmintonSense | 数据发送控制端 (CSV 动作发送模式)")
        self.root.geometry("640x580")
        self.root.configure(bg=COLOR_BG)
        self.root.resizable(False, False)

        # 变量初始化
        self.filepath_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="realtime")
        self.speed_var = tk.DoubleVar(value=1.0)
        self.status_var = tk.StringVar(value="Ready")
        self.progress_val = tk.DoubleVar(value=0.0)
        self.progress_percent = tk.StringVar(value="0.0%")

        self.is_sending = False
        self.is_paused = False

        self._apply_styles()
        self._create_widgets()

        # 启动后台异步服务
        self.loop = asyncio.new_event_loop()
        self.server_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.server_thread.start()

    def _apply_styles(self):
        """配置并应用贴合网页版规范的全局和 Ttk 样式"""
        style = ttk.Style()
        style.theme_use('clam')

        # 全局公共配置
        style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT_MAIN, font=("Microsoft YaHei", 9))
        
        # 进度条样式 (匹配 .action-bar-bg 与 .action-bar-fill)
        style.configure(
            "Web.Horizontal.TProgressbar",
            troughcolor="#f1f5f9",
            bordercolor=COLOR_BORDER,
            background=COLOR_BLUE,
            lightcolor=COLOR_BLUE,
            darkcolor=COLOR_BLUE,
            thickness=14
        )

        # 滑块样式
        style.configure(
            "Web.Horizontal.TScale",
            troughcolor="#f1f5f9",
            bordercolor=COLOR_BORDER,
            background=COLOR_TEXT_LIGHT,
            sliderlength=18
        )

        # 单选框样式
        style.configure("Web.TRadiobutton", background=COLOR_CARD_BG, foreground=COLOR_TEXT_MAIN, font=("Microsoft YaHei", 9))
        style.map("Web.TRadiobutton", 
                  background=[("active", COLOR_CARD_BG)],
                  foreground=[("active", COLOR_BLUE)])

    def _create_card(self, parent, title):
        """快捷创建一个符合网页端风格的白色阴影卡片容器"""
        card = tk.Frame(
            parent, 
            bg=COLOR_CARD_BG, 
            bd=0, 
            highlightbackground=COLOR_BORDER, 
            highlightthickness=1
        )
        # 卡片内部标题
        title_lbl = tk.Label(
            card, 
            text=title, 
            font=("Microsoft YaHei", 10, "bold"), 
            bg=COLOR_CARD_BG, 
            fg=COLOR_PRIMARY, 
            anchor="w"
        )
        title_lbl.pack(fill="x", padx=15, pady=(12, 8))
        return card

    def _create_widgets(self):
        # 1. 顶部 Brand 栏 (同步网页 HTML header 结构)
        header_frame = tk.Frame(self.root, bg=COLOR_BG)
        header_frame.pack(fill="x", padx=20, pady=(15, 10))

        # 品牌字样
        brand_lbl = tk.Label(
            header_frame, 
            text="BadmintonSense", 
            font=("Helvetica", 16, "bold"), 
            bg=COLOR_BG, 
            fg=COLOR_PRIMARY
        )
        brand_lbl.pack(side="left")

        sub_brand_lbl = tk.Label(
            header_frame, 
            text="Motion Analysis", 
            font=("Helvetica", 9), 
            bg=COLOR_BG, 
            fg=COLOR_BLUE
        )
        sub_brand_lbl.pack(side="left", padx=(8, 0), pady=(5, 0))

        # 2. 卡片区域 1: 数据源配置
        card_file = self._create_card(self.root, "数据源配置 (CSV 动作文件)")
        card_file.pack(fill="x", padx=20, pady=6)

        file_inner = tk.Frame(card_file, bg=COLOR_CARD_BG)
        file_inner.pack(fill="x", padx=15, pady=(0, 15))

        self.file_entry = tk.Entry(
            file_inner, 
            textvariable=self.filepath_var, 
            state="readonly", 
            font=("Microsoft YaHei", 9), 
            bd=1, 
            bg="#f8fafc", 
            fg=COLOR_TEXT_MAIN,
            relief="solid",
            highlightthickness=0,
            readonlybackground="#f8fafc"
        )
        self.file_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 10))

        # 扁平化"选择文件"按钮
        btn_select = tk.Button(
            file_inner, 
            text="选择 CSV 数据文件", 
            command=self._select_file,
            font=("Microsoft YaHei", 9, "bold"),
            bg=COLOR_BLUE,
            fg="white",
            activebackground="#1d4ed8",
            activeforeground="white",
            bd=0,
            cursor="hand2",
            padx=12,
            pady=4
        )
        btn_select.pack(side="right")

        # 3. 卡片区域 2: 传输模式设置
        card_ctrl = self._create_card(self.root, "传输模式设置")
        card_ctrl.pack(fill="x", padx=20, pady=6)

        ctrl_inner = tk.Frame(card_ctrl, bg=COLOR_CARD_BG)
        ctrl_inner.pack(fill="x", padx=15, pady=(0, 12))

        # 单选区域
        mode_frame = tk.Frame(ctrl_inner, bg=COLOR_CARD_BG)
        mode_frame.pack(fill="x", pady=(0, 6))

        rb_realtime = ttk.Radiobutton(
            mode_frame, 
            text="逐个动作发送 (动作间有停顿)", 
            value="realtime", 
            variable=self.mode_var, 
            style="Web.TRadiobutton",
            command=self._toggle_speed_slider
        )
        rb_realtime.pack(side="left", padx=(0, 20))

        rb_instant = ttk.Radiobutton(
            mode_frame, 
            text="全部动作高速发送", 
            value="instant", 
            variable=self.mode_var, 
            style="Web.TRadiobutton",
            command=self._toggle_speed_slider
        )
        rb_instant.pack(side="left")

        # 滑块调节区域
        self.slider_frame = tk.Frame(ctrl_inner, bg=COLOR_CARD_BG)
        self.slider_frame.pack(fill="x", pady=6)

        lbl_speed = tk.Label(self.slider_frame, text="发送间隔倍率: ", font=("Microsoft YaHei", 9), bg=COLOR_CARD_BG, fg=COLOR_TEXT_MAIN)
        lbl_speed.pack(side="left", padx=(0, 5))

        self.speed_scale = ttk.Scale(
            self.slider_frame, 
            from_=0.1, 
            to=10.0, 
            variable=self.speed_var, 
            orient="horizontal", 
            style="Web.Horizontal.TScale",
            command=self._update_speed_label
        )
        self.speed_scale.pack(side="left", fill="x", expand=True, padx=10)

        self.speed_lbl = tk.Label(self.slider_frame, text="1.0x", font=("Consolas", 10, "bold"), bg=COLOR_CARD_BG, fg=COLOR_BLUE, width=5)
        self.speed_lbl.pack(side="left")

        # 4. 卡片区域 3: 运行进度与控制
        card_status = self._create_card(self.root, "监控看板与传输进度")
        card_status.pack(fill="x", padx=20, pady=6)

        status_inner = tk.Frame(card_status, bg=COLOR_CARD_BG)
        status_inner.pack(fill="x", padx=15, pady=(0, 15))

        # 第一行状态标识
        lbl_status_title = tk.Label(status_inner, text="系统连接状态: ", font=("Microsoft YaHei", 9), bg=COLOR_CARD_BG, fg=COLOR_TEXT_LIGHT)
        lbl_status_title.pack(side="left")

        self.status_lbl = tk.Label(
            status_inner, 
            textvariable=self.status_var, 
            font=("Microsoft YaHei", 9, "bold"), 
            bg=COLOR_CARD_BG, 
            fg="#10b981"  # 默认就绪状态为翡翠绿
        )
        self.status_lbl.pack(side="left")

        # 进度百分比
        self.pct_lbl = tk.Label(status_inner, textvariable=self.progress_percent, font=("Consolas", 10, "bold"), bg=COLOR_CARD_BG, fg=COLOR_TEXT_MAIN)
        self.pct_lbl.pack(side="right")

        # 第二行：进度条与播放暂停控制
        pb_frame = tk.Frame(status_inner, bg=COLOR_CARD_BG)
        pb_frame.pack(fill="x", pady=(8, 0))

        self.pb = ttk.Progressbar(pb_frame, variable=self.progress_val, maximum=100, style="Web.Horizontal.TProgressbar")
        self.pb.pack(side="left", fill="x", expand=True, padx=(0, 15))

        # 暂停按钮
        self.btn_pause = tk.Button(
            pb_frame, 
            text="暂停", 
            state="disabled", 
            command=self._toggle_pause,
            font=("Microsoft YaHei", 9, "bold"),
            bg=COLOR_PRIMARY,
            fg="white",
            activebackground="#0f172a",
            activeforeground="white",
            bd=0,
            cursor="hand2",
            width=8,
            pady=3
        )
        self.btn_pause.pack(side="right")

        # 5. 底栏: 日志输出区域 (Log Viewer)
        card_log = self._create_card(self.root, "系统运行日志")
        card_log.pack(fill="both", expand=True, padx=20, pady=(6, 15))

        log_inner = tk.Frame(card_log, bg=COLOR_CARD_BG)
        log_inner.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # 高质感暗色集成式控制台代码
        self.log_text = scrolledtext.ScrolledText(
            log_inner, 
            state='disabled', 
            wrap='word', 
            font=("Consolas", 9),
            bg=COLOR_CONSOLE_BG, 
            fg="#e2e8f0",
            insertbackground="#ffffff", # 光标颜色
            bd=0,
            highlightthickness=0
        )
        self.log_text.pack(fill="both", expand=True)

    def log(self, message):
        """线程安全地向集成的控制台输出带格式时间戳的运行日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {message}\n"
        def append():
            self.log_text.configure(state='normal')
            self.log_text.insert(tk.END, full_msg)
            self.log_text.see(tk.END)
            self.log_text.configure(state='disabled')
        self.root.after(0, append)

    def _select_file(self):
        file_path = filedialog.askopenfilename(
            title="选择 BadmintonSense CSV 数据文件",
            filetypes=[("CSV 数据文件", "*.csv"), ("所有文件", "*.*")]
        )
        if file_path:
            self.filepath_var.set(file_path)
            self.log(f"已导入 CSV 动作数据文件: {os.path.basename(file_path)}")

    def _toggle_speed_slider(self):
        if self.mode_var.get() == "instant":
            self.speed_scale.state(["disabled"])
            self.speed_lbl.config(fg=COLOR_TEXT_LIGHT)
        else:
            self.speed_scale.state(["!disabled"])
            self.speed_lbl.config(fg=COLOR_BLUE)

    def _update_speed_label(self, val):
        self.speed_lbl.config(text=f"{float(val):.1f}x")

    def _toggle_pause(self):
        if not self.is_sending:
            return
        
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.btn_pause.config(text="继续", bg=COLOR_BLUE)
            self.log("传输流已主动暂停。")
            self._update_status_ui("传输已暂停", COLOR_BLUE)
        else:
            self.btn_pause.config(text="暂停", bg=COLOR_PRIMARY)
            self.log("传输流已继续推送。")
            self._update_status_ui("正在推送数据中...", "#10b981")

    def _reset_transmission_state(self):
        def do_reset():
            self.is_paused = False
            self.is_sending = False
            self.progress_val.set(0.0)
            self.progress_percent.set("0.0%")
            self.btn_pause.config(text="暂停", bg=COLOR_PRIMARY, state="disabled")
        self.root.after(0, do_reset)

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._start_ws_server())
        self.loop.run_forever()

    async def _start_ws_server(self):
        try:
            await websockets.serve(self._ws_handler, WS_HOST, WS_PORT)
            self.log(f"网络服务已就绪。服务器监听端口: {WS_PORT}")
            self._update_status_ui("Ready", "#10b981")
        except Exception as e:
            self.log(f"绑定端口失败，发生未知异常: {e}")
            self._update_status_ui("Error", "#ef4444")

    def _update_status_ui(self, msg, color=COLOR_BLUE):
        def update():
            self.status_var.set(msg)
            self.status_lbl.config(fg=color)
        self.root.after(0, update)

    def _update_progress_ui(self, current, total):
        def update():
            if total > 0:
                pct = (current / total) * 100
                self.progress_val.set(pct)
                self.progress_percent.set(f"{pct:.1f}%")
            else:
                self.progress_val.set(0)
                self.progress_percent.set("0.0%")
        self.root.after(0, update)

    async def _ws_handler(self, websocket):
        client_addr = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        self.log(f"客户端连接成功：来自网页端 {client_addr}")
        self._update_status_ui("Connected", "#10b981")
        self._update_progress_ui(0, 1)

        filepath = self.filepath_var.get()
        if not filepath:
            self.log("传输中断：未选择有效的 CSV 数据文件。")
            self._update_status_ui("No File", "#ef4444")
            await websocket.send(json.dumps({"error": "No file selected"}))
            self._reset_transmission_state()
            return

        self.log("开始解析 CSV 动作数据（按 sample_id 分组，构建特征矩阵）...")
        actions = parse_csv_actions(filepath)
        if not actions:
            self.log("加载中止：所选 CSV 文件数据格式解析失败或无有效数据。")
            self._update_status_ui("Parse Error", "#ef4444")
            self._reset_transmission_state()
            return

        total_actions = len(actions)
        self.log(f"解析成功：共 {total_actions} 个动作，准备开始推流...")
        self._update_status_ui("Sending", "#10b981")

        # 启动播放控制
        self.root.after(0, lambda: self.btn_pause.config(state="normal"))
        self.is_sending = True
        self.is_paused = False

        sent_count = 0
        mode = self.mode_var.get()

        try:
            for action in actions:
                while self.is_paused:
                    await asyncio.sleep(0.1)

                # 构造发送载荷 — 完全对应 example_load.py 返回的 records 内容
                #
                # 一个 payload 代表一个 sample_id（一个完整动作）：
                #   g_a_feat: 组A (WTleft + WTwaist) 的 12 通道特征矩阵, shape=(T_A, 12)
                #   g_b_feat: 组B (FA + EA) 的 12 通道特征矩阵, shape=(T_B, 12)
                #   g_a_lens: [len_wtleft, len_wtwaist]
                #   g_b_lens: [len_fa, len_ea]
                #   label:    动作类别标签
                #
                payload = {
                    "sample_id": action["sample_id"],
                    "g_a_feat": action["g_a_feat"],   # list of lists, (T_A, 12)
                    "g_b_feat": action["g_b_feat"],   # list of lists, (T_B, 12)
                    "g_a_lens": action["g_a_lens"],   # [len_wtleft, len_wtwaist]
                    "g_b_lens": action["g_b_lens"],   # [len_fa, len_ea]
                    "label":    action["label"]
                }
                await websocket.send(json.dumps(payload))

                sent_count += 1
                self._update_progress_ui(sent_count, total_actions)

                self.log(f"▶ 已发送动作: sample_id={action['sample_id']}, "
                         f"label={action['label']}, "
                         f"g_a_feat.shape=({len(action['g_a_feat'])},12), "
                         f"g_b_feat.shape=({len(action['g_b_feat'])},12)")

                # 模式控制：动作间的间隔（3秒间隔，让前端有足够时间展示结果）
                if mode == "realtime":
                    speed_factor = self.speed_var.get()
                    if speed_factor <= 0:
                        speed_factor = 1.0
                    await asyncio.sleep(3.0 / speed_factor)  # 默认 3 秒
                else:
                    await asyncio.sleep(0.001)  # 高速模式略微喘口气

            self.log(f"所有动作数据完整上传完毕。共发送 {sent_count} 个动作。保持通讯在线...")
            self._update_status_ui("Finished", "#10b981")

        except websockets.exceptions.ConnectionClosed:
            self.log(f"连接意外断开：来自网页端的会话已销毁。控制端已被重置。")
            self._update_status_ui("Ready", "#10b981")
        except Exception as e:
            self.log(f"进程通信时出现致命未知异常: {e}")
            self._update_status_ui("Exception", "#ef4444")
        finally:
            self._reset_transmission_state()


if __name__ == "__main__":
    root = tk.Tk()
    app = SenderGUI(root)
    root.mainloop()
