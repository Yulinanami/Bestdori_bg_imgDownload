import os
import queue
import threading
import customtkinter as ctk
from tkinter import filedialog 
from scanner import scan_all_scenarios
from downloader import download_worker
from stats import DownloadStats


class BestdoriAppModern(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark") 
        ctk.set_default_color_theme("blue") 
        self.title("Bestdori 背景图下载器")
        self.geometry("1000x640")

        self.output_dir = ctk.StringVar(value=os.path.abspath("bestdori_scenarios"))
        self.conc_var = ctk.IntVar(value=8)
        self.batch_var = ctk.IntVar(value=20)

        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.batch_queue: "queue.Queue[dict]" = queue.Queue()
        self.stats = DownloadStats()

        self.scan_thread = None
        self.download_thread = None

        self.log_queue = queue.Queue()

        self._build_layout()
        self.after(100, self._flush_log)

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, corner_radius=16)
        left.grid(row=0, column=0, sticky="nsw", padx=16, pady=16)

        right = ctk.CTkFrame(self, corner_radius=16)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 16), pady=16)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            left, text="Bestdori 背景图下载器", font=ctk.CTkFont(size=18, weight="bold")
        )
        title.pack(padx=16, pady=(16, 4))

        subtitle = ctk.CTkLabel(
            left,
            text="扫描 Bestdori 场景并批量下载背景图片",
            font=ctk.CTkFont(size=12),
        )
        subtitle.pack(padx=16, pady=(0, 12))

        dir_frame = ctk.CTkFrame(left, fg_color="transparent")
        dir_frame.pack(fill="x", padx=16, pady=(8, 4))
        ctk.CTkLabel(dir_frame, text="保存目录", anchor="w").grid(
            row=0, column=0, sticky="w"
        )

        entry_dir = ctk.CTkEntry(dir_frame, textvariable=self.output_dir, width=260)
        entry_dir.grid(row=1, column=0, sticky="w", pady=(4, 0))

        btn_browse = ctk.CTkButton(
            dir_frame, text="选择…", width=80, command=self._choose_dir
        )
        btn_browse.grid(row=1, column=1, padx=(8, 0), pady=(4, 0))

        # 下载并发数
        speed_frame = ctk.CTkFrame(left, fg_color="transparent")
        speed_frame.pack(fill="x", padx=16, pady=(12, 4))

        self.lbl_conc_title = ctk.CTkLabel(speed_frame, text="下载并发数", anchor="w")
        self.lbl_conc_title.grid(
            row=0, column=0, sticky="w"
        )

        self.lbl_conc_val = ctk.CTkLabel(speed_frame, text=str(self.conc_var.get()))
        self.lbl_conc_val.grid(row=0, column=1, sticky="e")

        self.slider_conc = ctk.CTkSlider(
            speed_frame,
            from_=1,
            to=24,
            number_of_steps=23,
            command=self._on_conc_change,
        )
        self.slider_conc.set(self.conc_var.get())
        self.slider_conc.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        speed_frame.grid_columnconfigure(0, weight=1)

        hint = ctk.CTkLabel(
            speed_frame,
            text="推荐 1-8，越大越快，但对 Bestdori 服务器压力越大，而且会导致下载不稳定",
            font=ctk.CTkFont(size=10),
            text_color=("gray40", "gray70"),
            wraplength=260,
            justify="left",
        )
        hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # 每批扫描 scenario 数
        batch_frame = ctk.CTkFrame(left, fg_color="transparent")
        batch_frame.pack(fill="x", padx=16, pady=(12, 4))

        self.lbl_batch_title = ctk.CTkLabel(batch_frame, text="每批扫描 scenario 数", anchor="w")
        self.lbl_batch_title.grid(
            row=0, column=0, sticky="w"
        )

        self.lbl_batch_val = ctk.CTkLabel(batch_frame, text="20")
        self.lbl_batch_val.grid(row=0, column=1, sticky="e")

        self.slider_batch = ctk.CTkSlider(
            batch_frame,
            from_=5,
            to=50,
            number_of_steps=45,
            command=self._on_batch_change,
        )
        self.slider_batch.set(self.batch_var.get())
        self.slider_batch.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        batch_frame.grid_columnconfigure(0, weight=1)

        # 按钮区域
        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(16, 8))

        self.btn_start = ctk.CTkButton(btn_frame, text="开始", command=self._start)
        self.btn_start.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.btn_pause = ctk.CTkButton(
            btn_frame, text="暂停", state="disabled", command=self._pause
        )
        self.btn_pause.grid(row=0, column=1, padx=6, sticky="ew")

        self.btn_resume = ctk.CTkButton(
            btn_frame, text="继续", state="disabled", command=self._resume
        )
        self.btn_resume.grid(row=0, column=2, padx=(6, 0), sticky="ew")

        self.btn_stop = ctk.CTkButton(
            btn_frame, text="停止", state="disabled", fg_color="#b53b3b", command=self._stop
        )
        self.btn_stop.grid(row=0, column=3, padx=(6, 0), sticky="ew")

        btn_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # 底部状态 + 进度
        status_frame = ctk.CTkFrame(left, fg_color="transparent")
        status_frame.pack(fill="x", padx=16, pady=(8, 16))

        self.progressbar = ctk.CTkProgressBar(status_frame)
        self.progressbar.grid(row=0, column=0, sticky="ew")
        self.progressbar.set(0)

        self.lbl_status = ctk.CTkLabel(
            status_frame, text="就绪", anchor="w", font=ctk.CTkFont(size=11)
        )
        self.lbl_status.grid(row=1, column=0, sticky="w", pady=(4, 0))

        status_frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(
            right,
            text="输出日志",
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        self.text_log = ctk.CTkTextbox(
            right,
            fg_color=("black", "#101010"),
            text_color=("white", "#f0f0f0"),
            corner_radius=12,
        )
        self.text_log.grid(row=1, column=0, sticky="nsew", padx=16, pady=(4, 16))

        # 记录控件默认颜色，方便禁用时置灰后再恢复
        self._default_text_colors = {
            "conc_title": self.lbl_conc_title.cget("text_color"),
            "conc_val": self.lbl_conc_val.cget("text_color"),
            "batch_title": self.lbl_batch_title.cget("text_color"),
            "batch_val": self.lbl_batch_val.cget("text_color"),
        }
        self._default_slider_colors = {
            "fg_color": self.slider_conc.cget("fg_color"),
            "progress_color": self.slider_conc.cget("progress_color"),
            "button_color": self.slider_conc.cget("button_color"),
            "button_hover_color": self.slider_conc.cget("button_hover_color"),
        }
        self._disabled_text_color = ("gray50", "gray70")
        self._disabled_slider_colors = {
            "fg_color": ("gray30", "gray25"),
            "progress_color": ("gray45", "gray35"),
            "button_color": ("gray55", "gray45"),
            "button_hover_color": ("gray55", "gray45"),
        }

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
            self.after(100, self._flush_log)

    def _choose_dir(self):
        path = filedialog.askdirectory(initialdir=self.output_dir.get())
        if path:
            self.output_dir.set(path)

    def _on_conc_change(self, value):
        v = int(round(float(value)))
        self.conc_var.set(v)
        self.lbl_conc_val.configure(text=str(v))

    def _on_batch_change(self, value):
        v = int(round(float(value)))
        self.batch_var.set(v)
        self.lbl_batch_val.configure(text=str(v))

    def _set_control_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        slider_colors = (
            self._default_slider_colors if enabled else self._disabled_slider_colors
        )

        self.slider_conc.configure(state=state, **slider_colors)
        self.slider_batch.configure(state=state, **slider_colors)

        self.lbl_conc_title.configure(
            text_color=(
                self._default_text_colors["conc_title"]
                if enabled
                else self._disabled_text_color
            )
        )
        self.lbl_conc_val.configure(
            text_color=(
                self._default_text_colors["conc_val"]
                if enabled
                else self._disabled_text_color
            )
        )
        self.lbl_batch_title.configure(
            text_color=(
                self._default_text_colors["batch_title"]
                if enabled
                else self._disabled_text_color
            )
        )
        self.lbl_batch_val.configure(
            text_color=(
                self._default_text_colors["batch_val"]
                if enabled
                else self._disabled_text_color
            )
        )

    def _start(self):
        if (self.scan_thread and self.scan_thread.is_alive()) or (
            self.download_thread and self.download_thread.is_alive()
        ):
            self.log("[info] 任务已经在运行中")
            return

        output_dir = self.output_dir.get().strip() or os.path.abspath(
            "bestdori_scenarios"
        )
        self.output_dir.set(output_dir)

        conc = int(self.conc_var.get())
        batch_size = int(self.batch_var.get())

        # 重置统计
        self.stats = DownloadStats()
        self.progressbar.set(0)

        # 重置控制变量
        self.pause_event.clear()
        self.stop_event.clear()
        while not self.batch_queue.empty():
            self.batch_queue.get_nowait()

        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal")
        self.btn_resume.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._set_control_enabled(False)

        self.lbl_status.configure(text="运行中…")

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
                lambda: self.after(0, self._on_done),
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
            self.btn_pause.configure(state="disabled")
            self.btn_resume.configure(state="normal")
            self.lbl_status.configure(text="已暂停")

    def _resume(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.log("[info] 已继续")
            self.btn_pause.configure(state="normal")
            self.btn_resume.configure(state="disabled")
            self.lbl_status.configure(text="运行中…")

    def _stop(self):
        if self.stop_event.is_set():
            return

        self.stop_event.set()
        self.pause_event.clear()
        self.log("[info] 已请求停止，正在等待当前批次收尾")
        self.lbl_status.configure(text="停止中，等待收尾…")

        try:
            while True:
                self.batch_queue.get_nowait()
        except queue.Empty:
            pass

        self.batch_queue.put(None)
        self.btn_pause.configure(state="disabled")
        self.btn_resume.configure(state="disabled")
        self.btn_stop.configure(state="disabled")

    def _update_progress(self, scanned, total):
        if total > 0:
            self.progressbar.set(scanned / total)
        self.lbl_status.configure(text=f"已扫描 {scanned}/{total} 个 scenario")

    def _scan_worker(self, output_dir, batch_size):
        from scanner import scan_all_scenarios 

        try:
            for batch in scan_all_scenarios(
                output_dir,
                batch_size,
                self.pause_event,
                self.log,
                self._update_progress,
                stats=self.stats,
                stop_event=self.stop_event,
            ):
                if self.stop_event.is_set():
                    break
                self.batch_queue.put(batch)

            if self.stop_event.is_set():
                self.log("=== 扫描已停止 ===")
            else:
                self.log("=== 扫描完成 ===")
        except Exception as e:
            import traceback

            traceback.print_exc()
            self.log(f"[错误] 扫描时出现异常: {e!r}")
        finally:
            self.batch_queue.put(None)

    def _on_done(self):
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled")
        self.btn_resume.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self._set_control_enabled(True)
        self.lbl_status.configure(text="就绪")

        # 输出统计
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


def main():
    app = BestdoriAppModern()
    app.mainloop()


if __name__ == "__main__":
    main()
