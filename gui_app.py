# gui_app.py
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from common import wait_if_paused_sync
from scanner import scan_all_scenarios
from downloader import download_worker
from stats import DownloadStats


class BestdoriApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Bestdori 背景图下载器 - Modern GUI")
        self.root.geometry("900x600")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=6)
        style.configure("TEntry", padding=4)
        style.configure("TLabel", padding=4)

        self.output_var = tk.StringVar(value=os.path.abspath("bestdori_scenarios"))
        self.conc_var = tk.IntVar(value=24)
        self.batch_var = tk.IntVar(value=20)

        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.batch_queue: "queue.Queue[dict]" = queue.Queue()

        # 下载统计
        self.stats = DownloadStats()
        self._build_layout()

        self.log_queue = queue.Queue()
        self.root.after(100, self._flush_log)

        self.scan_thread = None
        self.download_thread = None

    def _build_layout(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="保存目录").grid(row=0, column=0, sticky="w")
        entry_dir = ttk.Entry(top, textvariable=self.output_var, width=60)
        entry_dir.grid(row=0, column=1, padx=5, sticky="we")
        ttk.Button(top, text="选择…", command=self._choose_dir).grid(
            row=0, column=2, padx=5
        )

        ttk.Label(top, text="下载速度（并发数）").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        spin_conc = ttk.Spinbox(
            top, from_=1, to=64, textvariable=self.conc_var, width=6
        )
        spin_conc.grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(top, text="（推荐 16~32，越大越快，但对Bestdori服务器压力越大）").grid(
            row=1, column=1, sticky="e", padx=(0, 80), pady=(8, 0)
        )

        ttk.Label(top, text="每批扫描 scenario 数").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        spin_batch = ttk.Spinbox(
            top, from_=1, to=100, textvariable=self.batch_var, width=6
        )
        spin_batch.grid(row=2, column=1, sticky="w", pady=(8, 0))

        btn_frame = ttk.Frame(top)
        btn_frame.grid(row=0, column=3, rowspan=3, padx=10)

        self.btn_start = ttk.Button(btn_frame, text="开始", command=self._start)
        self.btn_start.pack(fill="x", pady=2)

        self.btn_pause = ttk.Button(
            btn_frame, text="暂停", state="disabled", command=self._pause
        )
        self.btn_pause.pack(fill="x", pady=2)

        self.btn_resume = ttk.Button(
            btn_frame, text="继续", state="disabled", command=self._resume
        )
        self.btn_resume.pack(fill="x", pady=2)

        prog_frame = ttk.Frame(self.root, padding=(10, 0, 10, 5))
        prog_frame.pack(fill="x")

        self.progress = ttk.Progressbar(prog_frame, mode="determinate")
        self.progress.pack(fill="x")

        self.label_status = ttk.Label(prog_frame, text="就绪")
        self.label_status.pack(anchor="w")

        log_frame = ttk.Frame(self.root, padding=10)
        log_frame.pack(fill="both", expand=True)

        self.text_log = tk.Text(
            log_frame,
            wrap="none",
            bg="#111111",
            fg="#eeeeee",
            insertbackground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
        )
        self.text_log.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.text_log.yview
        )
        scroll_y.pack(side="right", fill="y")
        self.text_log.configure(yscrollcommand=scroll_y.set)

    def log(self, msg: str):
        self.log_queue.put(str(msg))

    def _flush_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.text_log.insert("end", msg + "\n")
                self.text_log.see("end")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._flush_log)

    def _choose_dir(self):
        path = filedialog.askdirectory(initialdir=self.output_var.get())
        if path:
            self.output_var.set(path)

    def _start(self):
        if (self.scan_thread and self.scan_thread.is_alive()) or (
            self.download_thread and self.download_thread.is_alive()
        ):
            self.log("[info] 任务已经在运行中")
            return

        output_dir = self.output_var.get().strip() or os.path.abspath(
            "bestdori_scenarios"
        )
        self.output_var.set(output_dir)

        try:
            conc = int(self.conc_var.get())
        except ValueError:
            conc = 24
            self.conc_var.set(conc)

        try:
            batch_size = int(self.batch_var.get())
        except ValueError:
            batch_size = 20
            self.batch_var.set(batch_size)

        # 每次开始任务都重置统计
        self.stats = DownloadStats()

        # 重置控制变量
        self.pause_event.clear()
        self.stop_event.clear()
        while not self.batch_queue.empty():
            self.batch_queue.get_nowait()

        self.btn_start.config(state="disabled")
        self.btn_pause.config(state="normal")
        self.btn_resume.config(state="disabled")

        self.progress.config(value=0, maximum=100)
        self.label_status.config(text="运行中…")

        self.log("=== 开始任务 ===")
        self.log(f"保存目录: {output_dir}")
        self.log(f"并发数: {conc}，每批扫描 {batch_size} 个 scenario")

        # 启动下载线程
        self.download_thread = threading.Thread(
            target=download_worker,
            args=(
                self.batch_queue,
                self.pause_event,
                self.stop_event,
                output_dir,
                conc,
                self.log,
                lambda: self.root.after(0, self._on_done),
                self.stats, 
            ),
            daemon=True,
        )
        self.download_thread.start()

        # 启动扫描线程
        self.scan_thread = threading.Thread(
            target=self._scan_worker,
            args=(output_dir, batch_size),
            daemon=True,
        )
        self.scan_thread.start()

    def _pause(self):
        if not self.pause_event.is_set():
            self.pause_event.set()
            self.log("[info] 已请求暂停")
            self.btn_pause.config(state="disabled")
            self.btn_resume.config(state="normal")
            self.label_status.config(text="已暂停")

    def _resume(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.log("[info] 已继续")
            self.btn_pause.config(state="normal")
            self.btn_resume.config(state="disabled")
            self.label_status.config(text="运行中…")

    def _update_progress(self, scanned, total):
        self.progress.config(maximum=total, value=scanned)
        self.label_status.config(text=f"已扫描 {scanned}/{total} 个 scenario")

    def _scan_worker(self, output_dir, batch_size):
        """扫描线程：调用 scan_all_scenarios 并把每批结果放进队列"""
        try:
            for batch in scan_all_scenarios(
                output_dir,
                batch_size,
                self.pause_event,
                self.log,
                self._update_progress,
                stats=self.stats,  
            ):
                if self.stop_event.is_set():
                    break
                self.batch_queue.put(batch)

            self.log("=== 扫描完成 ===")
        except Exception as e:
            import traceback

            traceback.print_exc()
            self.log(f"[错误] 扫描时出现异常: {e!r}")
        finally:
            self.batch_queue.put(None)

    def _on_done(self):
        self.btn_start.config(state="normal")
        self.btn_pause.config(state="disabled")
        self.btn_resume.config(state="disabled")
        self.label_status.config(text="就绪")

        # 在任务结束时输出统计
        summary = self.stats.snapshot()
        total = summary["total"]
        success = summary["success"]
        failed = summary["failed"]
        failed_items = summary["failed_items"]

        self.log("\n=== 下载统计 ===")
        self.log(f"总共扫描图片数: {total}")
        self.log(f"成功下载: {success}")
        self.log(f"失败: {failed}")

        if failed_items:
            self.log("失败的图片：")
            for scen, alt in failed_items:
                self.log(f"  - {scen}/{alt}")
