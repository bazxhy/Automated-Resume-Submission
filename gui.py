"""
BOSS直聘自动投递 — 桌面GUI (tkinter)
上传简历 → 解析关键词 → 设置筛选 → 一键投递
"""

from __future__ import annotations

import sys
import os
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# 确保能找到同目录的模块
sys.path.insert(0, str(Path(__file__).parent))

from utils import load_config, get_logger
from resume_parser import ResumeParser


class ResumeGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("BOSS直聘 自动投递")
        self.root.geometry("700x750")
        self.root.resizable(True, True)

        self.resume_data = None
        self.resume_path = tk.StringVar(value="请选择简历文件...")
        self.city = tk.StringVar(value="杭州")
        self.experience = tk.StringVar(value="应届生")
        self.keywords = tk.StringVar(value="嵌入式, 单片机, ARM, Linux, STM32, RTOS, C/C++")
        self.min_score = tk.IntVar(value=70)
        self.daily_limit = tk.IntVar(value=50)
        self.running = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # ==================== UI 构建 ====================

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # ---- 1. 简历上传 ----
        group1 = ttk.LabelFrame(main, text="1. 上传简历", padding=10)
        group1.pack(fill=tk.X, pady=5)

        row1 = ttk.Frame(group1)
        row1.pack(fill=tk.X)
        ttk.Entry(row1, textvariable=self.resume_path, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row1, text="选择文件", command=self._pick_resume).pack(side=tk.LEFT, padx=5)
        ttk.Button(row1, text="解析简历", command=self._parse_resume).pack(side=tk.LEFT)

        # 解析结果
        self.resume_info = tk.Text(group1, height=8, state=tk.DISABLED, font=("微软雅黑", 9))
        self.resume_info.pack(fill=tk.X, pady=5)

        # ---- 2. 搜索设置 ----
        group2 = ttk.LabelFrame(main, text="2. 搜索设置", padding=10)
        group2.pack(fill=tk.X, pady=5)

        g2 = ttk.Frame(group2)
        g2.pack(fill=tk.X)
        ttk.Label(g2, text="城市:").pack(side=tk.LEFT)
        ttk.Combobox(g2, textvariable=self.city, width=12,
                     values=["北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "苏州"]).pack(side=tk.LEFT, padx=5)
        ttk.Label(g2, text="经验:").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Combobox(g2, textvariable=self.experience, width=10,
                     values=["应届生", "在校生", "经验不限", "1年以内", "1-3年", "3-5年"]).pack(side=tk.LEFT, padx=5)
        ttk.Label(g2, text="每日上限:").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Spinbox(g2, textvariable=self.daily_limit, width=5, from_=1, to=200).pack(side=tk.LEFT, padx=5)

        g2b = ttk.Frame(group2)
        g2b.pack(fill=tk.X, pady=5)
        ttk.Label(g2b, text="搜索关键词(逗号分隔):").pack(side=tk.LEFT)
        ttk.Entry(g2b, textvariable=self.keywords).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # ---- 3. 筛选设置 ----
        group3 = ttk.LabelFrame(main, text="3. 筛选设置", padding=10)
        group3.pack(fill=tk.X, pady=5)

        g3 = ttk.Frame(group3)
        g3.pack(fill=tk.X)
        ttk.Label(g3, text="最低匹配分:").pack(side=tk.LEFT)
        ttk.Spinbox(g3, textvariable=self.min_score, width=5, from_=0, to=100).pack(side=tk.LEFT, padx=5)
        ttk.Label(g3, text="(0-100，建议70)").pack(side=tk.LEFT)

        # ---- 4. 控制 ----
        group4 = ttk.Frame(main)
        group4.pack(fill=tk.X, pady=10)

        self.start_btn = ttk.Button(group4, text="🚀 开始投递", command=self._start, width=20)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(group4, text="⏹ 停止", command=self._stop, state=tk.DISABLED, width=10)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.progress = ttk.Progressbar(group4, mode="indeterminate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # ---- 5. 运行日志 ----
        group5 = ttk.LabelFrame(main, text="运行日志", padding=5)
        group5.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_area = tk.Text(group5, state=tk.DISABLED, font=("Consolas", 9), wrap=tk.WORD)
        scroll = ttk.Scrollbar(group5, command=self.log_area.yview)
        self.log_area.configure(yscrollcommand=scroll.set)
        self.log_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 状态栏
        self.status = ttk.Label(main, text="就绪 - 请先上传并解析简历", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(fill=tk.X)

    # ==================== 功能 ====================

    def _pick_resume(self):
        path = filedialog.askopenfilename(
            title="选择简历文件",
            filetypes=[("简历文件", "*.pdf *.docx *.txt"), ("所有文件", "*.*")]
        )
        if path:
            self.resume_path.set(path)
            self._parse_resume()

    def _parse_resume(self):
        path = self.resume_path.get()
        if not path or not os.path.isfile(path):
            return
        try:
            parser = ResumeParser(path)
            self.resume_data = parser.parse()
            info = self.resume_info
            info.configure(state=tk.NORMAL)
            info.delete(1.0, tk.END)
            info.insert(tk.END, f"姓名: {self.resume_data.name or '未识别'}\n")
            info.insert(tk.END, f"电话: {self.resume_data.phone or '未识别'}  邮箱: {self.resume_data.email or '未识别'}\n")
            info.insert(tk.END, f"技能({len(self.resume_data.skills)}): {', '.join(self.resume_data.skills[:20])}\n")
            info.insert(tk.END, f"工作经历: {len(self.resume_data.work_experiences)} 段\n")
            info.insert(tk.END, f"教育: {len(self.resume_data.education)} 段\n")
            info.insert(tk.END, f"\n💡 请检查上方技能列表，必要时调整搜索关键词")
            info.configure(state=tk.DISABLED)

            # 自动填充关键词：从简历技能中提取嵌入式相关
            embedded_skills = [s for s in self.resume_data.skills
                               if any(k in s.lower() for k in ("嵌入", "arm", "stm", "rtos", "linux", "驱动", "单片", "c", "c++", "fpga", "dsp", "物联网"))]
            if embedded_skills:
                self.keywords.set(", ".join(embedded_skills[:8]))

            self.status.configure(text=f"简历解析完成: {self.resume_data.name or '未知'} | {len(self.resume_data.skills)}项技能")
        except Exception as e:
            messagebox.showerror("解析失败", str(e))

    # ==================== 投递控制 ====================

    def _start(self):
        if self.running:
            return
        if not self.resume_data:
            messagebox.showwarning("提示", "请先上传并解析简历")
            return

        self.running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.progress.start(10)
        self.status.configure(text="正在初始化...")

        # 生成配置
        keywords = [k.strip() for k in self.keywords.get().split(",") if k.strip()]
        if not keywords:
            keywords = ["嵌入式"]

        cfg = {
            "browser": {"headless": False, "data_dir": "./browser_data", "window_size": [1280, 800], "slow_mo": 500},
            "login": {"method": "qr", "cookie_file": "./cookies.json", "wait_seconds": 60},
            "resume": {"file_path": self.resume_path.get(), "encoding": "utf-8"},
            "search": {
                "keywords": keywords,
                "city": self.city.get(),
                "experience": self.experience.get(),
                "salary": "",
                "page_limit": 5,
                "jobs_per_page": 15,
            },
            "filter": {
                "exclude_titles": ["实习", "兼职", "外包", "外派", "劳务", "培训", "急聘"],
                "exclude_companies": ["人力资源", "劳务派遣", "外包服务"],
                "min_match_score": self.min_score.get(),
                "skip_kpi": True,
                "skip_kpi_score": 60,
            },
            "risk_check": {
                "mode": "rule",
                "api": {"provider": "", "token": ""},
                "risk_keywords": ["裁员", "欠薪", "纠纷", "失信", "倒闭", "跑路"],
            },
            "submit": {
                "greeting": "您好，看了岗位介绍觉得挺适合的，方便聊聊吗？",
                "daily_limit": self.daily_limit.get(),
                "interval": {"min": 8, "max": 20},
            },
            "output": {
                "log_file": "./submit_log.csv",
                "record_file": "./apply_record.json",
                "log_level": "INFO",
            },
        }

        # 写临时配置
        # 写临时配置到 exe 目录
        from utils import project_root
        cfg_path = str(project_root() / "config_gui.yaml")
        import yaml
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

        # 在后台线程运行
        thread = threading.Thread(target=self._run_boss, args=(cfg_path,), daemon=True)
        thread.start()

    def _run_boss(self, cfg_path: str):
        """后台线程：直接运行投递逻辑"""
        import io
        import logging

        # GUI 无控制台 → 登录弹窗等确认
        import builtins
        original_input = builtins.input
        def _gui_input(prompt=""):
            self._append_log(prompt.strip())
            messagebox.showinfo("登录", "请在浏览器中扫码登录 BOSS直聘\n\n登录成功后点击确定")
            return ""
        builtins.input = _gui_input

        # 重定向 stdout 到 GUI
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        gui_out = _GuiWriter(self._append_log)
        sys.stdout = gui_out
        sys.stderr = gui_out

        # 重新设置各模块的 logger，使用新的 handler
        from utils import setup_logger, get_logger
        for name in ["app", "jobs", "risk", "matcher", "submit", "recorder", "resume", "login"]:
            logger = logging.getLogger(name)
            logger.handlers.clear()
            h = logging.StreamHandler(gui_out)
            h.setLevel(logging.INFO)
            h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-7s | %(message)s", datefmt="%H:%M:%S"))
            logger.addHandler(h)
            logger.setLevel(logging.INFO)

        try:
            from main import AutoBossApp
            app = AutoBossApp(config_path=cfg_path)
            app.run()
            self.root.after(0, self._on_done, "✅ 投递完成")
        except Exception as e:
            import traceback
            self.root.after(0, self._append_log, traceback.format_exc())
            self.root.after(0, self._on_done, f"❌ 异常: {e}")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            builtins.input = original_input

    def _stop(self):
        self.running = False
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.progress.stop()
        self.status.configure(text="已停止")
        self._append_log("用户手动停止\n")

    def _on_done(self, msg: str):
        self.running = False
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.progress.stop()
        self.status.configure(text=msg)

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno("确认", "程序正在运行中，确定退出吗？"):
                return
        self.root.destroy()

    def _append_log(self, text: str):
        self.log_area.configure(state=tk.NORMAL)
        self.log_area.insert(tk.END, text + "\n")
        self.log_area.see(tk.END)
        self.log_area.configure(state=tk.DISABLED)


class _GuiWriter:
    """将 stdout/stderr 输出重定向到 GUI 日志区"""
    def __init__(self, callback):
        self.callback = callback
        self.buf = ""

    def write(self, text):
        if not text or not text.strip():
            return
        self.buf += text
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            line = line.strip()
            if line:
                # tkinter 在主线程安全
                try:
                    import tkinter as tk
                    root = None
                    # 寻找 root
                    try:
                        root = tk._default_root
                    except Exception:
                        pass
                    if root:
                        root.after(0, self.callback, line)
                except Exception:
                    pass

    def flush(self):
        pass


if __name__ == "__main__":
    ResumeGUI()
