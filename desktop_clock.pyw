# -*- coding: utf-8 -*-
"""桌面时钟小组件

- 置顶悬浮、无边框、可拖动
- 右上角 × 或右键菜单可随时关闭
- 自动记住位置与置顶设置，重开时恢复
- 同一时间只允许一个实例
"""

import ctypes
import json
import os
import sys
import traceback
from datetime import datetime

import tkinter as tk
import tkinter.font as tkfont

APP_TITLE = "桌面时钟"
MUTEX_NAME = "Local\\DSH_DesktopClock_Widget_v1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "clock_config.json")
LOG_PATH = os.path.join(BASE_DIR, "clock_error.log")

BG = "#12141b"
BORDER = "#2b3242"
TIME_COLOR = "#f4f6fb"
SEC_COLOR = "#4fd1c5"
DATE_COLOR = "#8b94a7"
CLOSE_COLOR = "#454d60"
CLOSE_HOVER = "#ff6b6b"

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_scale():
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi:
            return dpi / 96.0
    except Exception:
        pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    except Exception:
        return 1.0


def acquire_single_instance():
    """返回互斥句柄；若已有实例在运行则返回 None。"""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if not handle or kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return None
        return handle
    except Exception:
        return True  # 互斥不可用时照常运行


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_config(data):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=48, **kwargs)


class DesktopClock:
    def __init__(self, root, scale):
        self.root = root
        self.s = scale
        self.cfg = load_config()

        self.topmost = bool(self.cfg.get("topmost", True))
        self.time_font = tkfont.Font(family="Consolas", size=-int(round(46 * scale)), weight="bold")
        self.sec_font = tkfont.Font(family="Consolas", size=-int(round(22 * scale)), weight="bold")
        self.date_font = tkfont.Font(family="Microsoft YaHei UI", size=-int(round(13 * scale)))

        pad = 24.0 * scale
        self.pad = pad
        self.time_h = self.time_font.metrics("linespace")
        self.date_h = self.date_font.metrics("linespace")
        self.w = int(round(282 * scale))
        self.h = int(round(14 * scale + self.time_h + 7 * scale + self.date_h + 16 * scale))
        self.top_pad = 14.0 * scale
        self.time_bottom = self.top_pad + self.time_h

        self._hhmm = ""
        self._ss = ""
        self._date = ""

        root.title(APP_TITLE)
        root.overrideredirect(True)
        root.configure(bg=BG)
        root.attributes("-topmost", self.topmost)
        root.attributes("-transparentcolor", "#010203")
        self._restore_geometry()

        self.canvas = tk.Canvas(
            root, width=self.w, height=self.h, bg="#010203",
            highlightthickness=0, bd=0,
        )
        self.canvas.pack()

        rounded_rect(
            self.canvas, 1, 1, self.w - 1, self.h - 1, 18 * scale,
            fill=BG, outline=BORDER, width=max(1, int(round(scale))),
        )

        # 时间 HH:MM
        self.time_id = self.canvas.create_text(
            pad, self.top_pad, anchor="nw", text="00:00",
            font=self.time_font, fill=TIME_COLOR,
        )
        # 秒
        self.sec_id = self.canvas.create_text(
            pad, self.time_bottom, anchor="sw", text="00",
            font=self.sec_font, fill=SEC_COLOR,
        )
        # 日期
        self.date_id = self.canvas.create_text(
            pad + 1 * scale, self.time_bottom + 7 * scale, anchor="nw", text="",
            font=self.date_font, fill=DATE_COLOR,
        )

        self._build_close_button()
        self._build_menu()
        self._bind_events()

        self.tick()

    # ---------- 界面 ----------
    def _build_close_button(self):
        s = self.s
        cx, cy = self.w - 22 * s, 22 * s
        arm = 5.0 * s
        # 先铺一块与卡片同色的点击热区，再画 ×，保证整个区域都能点
        self.close_hit = self.canvas.create_rectangle(
            cx - 13 * s, cy - 13 * s, cx + 13 * s, cy + 13 * s,
            fill=BG, outline="", tags="closezone",
        )
        common = dict(
            fill=CLOSE_COLOR, width=max(1.5, 1.6 * s), capstyle="round",
            tags="closezone",
        )
        self.close_line1 = self.canvas.create_line(cx - arm, cy - arm, cx + arm, cy + arm, **common)
        self.close_line2 = self.canvas.create_line(cx - arm, cy + arm, cx + arm, cy - arm, **common)
        self.canvas.tag_bind("closezone", "<Button-1>", lambda e: self.close())
        self.canvas.tag_bind("closezone", "<Enter>", lambda e: self._hover_close(True))
        self.canvas.tag_bind("closezone", "<Leave>", lambda e: self._hover_close(False))
        self.canvas.tag_bind("closezone", "<Button-3>", self._popup_menu)

    def _hover_close(self, on):
        color = CLOSE_HOVER if on else CLOSE_COLOR
        self.canvas.itemconfigure(self.close_line1, fill=color)
        self.canvas.itemconfigure(self.close_line2, fill=color)
        self.canvas.configure(cursor="hand2" if on else "")

    def _build_menu(self):
        self.menu = tk.Menu(
            self.root, tearoff=0,
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff", fg="#222833",
            activebackground="#eaf3ff", activeforeground="#0f172a",
            bd=0, relief="flat",
        )
        self.top_var = tk.BooleanVar(value=self.topmost)
        self.menu.add_checkbutton(
            label="窗口置顶", variable=self.top_var, command=self._toggle_topmost,
        )
        self.menu.add_command(label="回到右上角", command=self._recenter)
        self.menu.add_separator()
        self.menu.add_command(label="关闭时钟", command=self.close)

    def _bind_events(self):
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Button-3>", self._popup_menu)
        self.root.bind("<Escape>", lambda e: self.close())

    # ---------- 位置 ----------
    def _screen(self):
        return self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _default_pos(self):
        sw, _ = self._screen()
        return sw - self.w - int(round(26 * self.s)), int(round(26 * self.s))

    def _restore_geometry(self):
        x, y = self._default_pos()
        try:
            cx, cy = int(self.cfg.get("x")), int(self.cfg.get("y"))
            sw, sh = self._screen()
            if -self.w + 80 <= cx <= sw - 80 and 0 <= cy <= sh - 60:
                x, y = cx, cy
        except Exception:
            pass
        self.x, self.y = x, y
        self.root.geometry(f"{self.w}x{self.h}+{x}+{y}")

    def _recenter(self):
        self.x, self.y = self._default_pos()
        self.root.geometry(f"+{self.x}+{self.y}")
        self._persist()

    def _persist(self):
        save_config({
            "x": self.x, "y": self.y,
            "topmost": self.topmost,
        })

    def _toggle_topmost(self):
        self.topmost = bool(self.top_var.get())
        self.root.attributes("-topmost", self.topmost)
        self._persist()

    def _popup_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # ---------- 拖动 ----------
    def _drag_start(self, event):
        self._drag_origin = (event.x_root, event.y_root, self.x, self.y)

    def _drag_move(self, event):
        if not getattr(self, "_drag_origin", None):
            return
        px, py, wx, wy = self._drag_origin
        self.x = wx + (event.x_root - px)
        self.y = wy + (event.y_root - py)
        self.root.geometry(f"+{self.x}+{self.y}")

    def _drag_end(self, event):
        self._drag_origin = None
        self._persist()

    # ---------- 走时 ----------
    def tick(self):
        now = datetime.now()
        hhmm = now.strftime("%H:%M")
        ss = now.strftime("%S")
        date = f"{now.year}年{now.month}月{now.day}日  {WEEKDAYS[now.weekday()]}"

        if hhmm != self._hhmm:
            self._hhmm = hhmm
            self.canvas.itemconfigure(self.time_id, text=hhmm)
            self._place_seconds()

        if ss != self._ss:
            self._ss = ss
            self.canvas.itemconfigure(self.sec_id, text=ss)

        if date != self._date:
            self._date = date
            self.canvas.itemconfigure(self.date_id, text=date)

        self.root.after(200, self.tick)

    def _place_seconds(self):
        text_w = self.time_font.measure(self._hhmm)
        self.canvas.coords(
            self.sec_id,
            self.pad + text_w + 3.0 * self.s,
            self.time_bottom - 1.0 * self.s,
        )

    # ---------- 关闭 ----------
    def close(self):
        self._persist()
        # 延迟一帧再销毁：避免在画布事件派发过程中直接销毁自身
        try:
            self.root.after(1, self._destroy)
        except Exception:
            self._destroy()

    def _destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    handle = acquire_single_instance()
    if handle is None:
        return

    enable_dpi_awareness()
    scale = get_scale()
    root = tk.Tk()
    app = DesktopClock(root, scale)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
                f.write(traceback.format_exc() + "\n\n")
        except Exception:
            pass
        sys.exit(1)
