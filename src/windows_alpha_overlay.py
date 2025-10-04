# src\windows_alpha_overlay.py

import tkinter as tk
import ctypes
from ctypes import wintypes
from typing import Optional
from PIL import Image

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00000000
AC_SRC_ALPHA = 0x00000001
DIB_RGB_COLORS = 0x00000000
BI_RGB = 0x00000000

# --- SetWindowPos Flags (追加) ---
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wintypes.BYTE),
        ("BlendFlags", wintypes.BYTE),
        ("SourceConstantAlpha", wintypes.BYTE),
        ("AlphaFormat", wintypes.BYTE),
    ]

class WindowsAlphaOverlay:
    """Win32 API を利用してアルファチャンネル付き画像を合成するウィンドウ。"""

    def __init__(self, parent: tk.Toplevel):
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.overrideredirect(True)
        self.window.withdraw()
        # 背景色はUpdateLayeredWindowでは使われないが、念のため設定
        self.window.configure(bg="#000000")

        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        
        # SetWindowPos のプロトタイプを定義 (追加)
        self._user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        self._user32.SetWindowPos.restype = wintypes.BOOL

        self.hwnd = self.window.winfo_id()
        current_style = self._user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        
        # WS_EX_TRANSPARENT を削除し、クリックイベントを受け取れるようにする
        self._user32.SetWindowLongW(
            self.hwnd,
            GWL_EXSTYLE,
            current_style | WS_EX_LAYERED, # WS_EX_TRANSPARENT を削除
        )

        # マウスイベントを検知し、親ウィンドウの処理担当に中継（フォワード）する
        self.window.bind('<Button-1>', self._forward_press)
        self.window.bind('<B1-Motion>', self._forward_motion)
        self.window.bind('<ButtonRelease-1>', self._forward_release)
        self.window.bind('<Button-3>', self._forward_right_click)
        self.window.bind('<Motion>', self._forward_mouse_move)
        self.window.bind('<Leave>', self._forward_mouse_leave)
        self.window.bind('<MouseWheel>', self._forward_mouse_wheel)

        self.current_image: Optional[Image.Image] = None
        self.current_position = (0, 0)
        self.available = True
        
        # ★★★ ここから修正 ★★★
        # 透明と判定するアルファ値の閾値。0に近いほど完全に透明な部分のみを対象とする。
        self.ALPHA_TRANSPARENT_THRESHOLD = 10
        # 有効なクリック（ドラッグ）操作が開始されたかを管理するフラグ
        self.is_valid_press_started = False
        # ★★★ ここまで修正 ★★★

    def _is_transparent(self, x: int, y: int) -> bool:
        """指定された座標のピクセルが透明かどうかを判定するヘルパーメソッド。"""
        if not self.current_image:
            return True # 画像がなければ透明とみなす

        # 画像の範囲外の座標は透明とみなす
        if not (0 <= x < self.current_image.width and 0 <= y < self.current_image.height):
            return True

        try:
            # ピクセルのRGBA値を取得 (Aはアルファ値)
            pixel_alpha = self.current_image.getpixel((x, y))[3]
            # アルファ値が閾値より低い場合は透明と判定
            return pixel_alpha < self.ALPHA_TRANSPARENT_THRESHOLD
        except (IndexError, TypeError):
            # getpixelが失敗した場合（例: 予期せぬ画像フォーマット）も安全に透明として扱う
            return True

    @property
    def has_image(self) -> bool:
        return self.current_image is not None

    # --- イベントを中継するためのメソッド群 ---
    def _forward_press(self, event):
        """左クリック開始イベントを中継する"""
        # ★★★ ここから修正 ★★★
        if self._is_transparent(event.x, event.y):
            # 透明な部分でクリックが開始された場合、フラグをFalseにしてイベントを無視
            self.is_valid_press_started = False
            return
        
        # 有効な領域でクリックされたので、フラグをTrueに設定
        self.is_valid_press_started = True
        # ★★★ ここまで修正 ★★★
        if self.parent.emotion_handler:
            self.parent.emotion_handler.press_window(event)

    def _forward_motion(self, event):
        """ドラッグイベントを中継する"""
        # ★★★ ここから修正 ★★★
        # 有効なクリックで始まっていないドラッグ操作はすべて無視する
        if not self.is_valid_press_started:
            return
        # ★★★ ここまで修正 ★★★
        if self.parent.emotion_handler:
            self.parent.emotion_handler.drag_window(event)

    def _forward_release(self, event):
        """左クリック終了イベントを中継する"""
        # ★★★ ここから修正 ★★★
        # EmotionHandler側でドラッグ終了処理などを正しく行うために、
        # releaseイベント自体は常に中継する。
        if self.parent.emotion_handler:
            self.parent.emotion_handler.release_window(event)

        # クリック/ドラッグ操作が完了したので、フラグをリセットする
        self.is_valid_press_started = False
        # ★★★ ここまで修正 ★★★

    def _forward_right_click(self, event):
        """右クリックイベントを中継する。キャラクター自身の参照も渡す。"""
        if self._is_transparent(event.x, event.y):
            return
        # 右クリックメニューの表示はEmotionHandlerではなく、アプリ本体が持つ
        if self.parent.char_ctrl and self.parent.char_ctrl.mascot_app:
            # イベントオブジェクトと一緒に、このオーバーレイが属するキャラクターコントローラーを渡す
            self.parent.char_ctrl.mascot_app.show_context_menu(event, self.parent.char_ctrl)
    
    def _forward_mouse_move(self, event):
        """マウス移動イベントを中継する（タッチエリア判定用）"""
        if self._is_transparent(event.x, event.y):
            # 透明な部分にカーソルがある場合、タッチエリアの判定は行わず、
            # カーソルをデフォルトに戻す処理を呼び出す。
            if self.parent.emotion_handler:
                self.parent.emotion_handler.reset_cursor(event)
            return
        if self.parent.emotion_handler:
            self.parent.emotion_handler.check_cursor_change(event)
            
    def _forward_mouse_leave(self, event):
        """マウスがウィンドウから離れたイベントを中継する"""
        if self.parent.emotion_handler:
            self.parent.emotion_handler.reset_cursor(event)
            
    def _forward_mouse_wheel(self, event):
        """マウスホイールイベントを中継する（タッチエリア選択用）"""
        if self._is_transparent(event.x, event.y):
            return
        if self.parent.emotion_handler:
            self.parent.emotion_handler.on_mouse_wheel(event)

    def update_image(self, image: Image.Image, x: int, y: int):
        if not isinstance(image, Image.Image):
            raise TypeError("image must be a PIL.Image.Image instance")

        self.current_image = image.copy()
        self.current_position = (int(x), int(y))
        print("update_image > _render")
        self._render(self.current_image, *self.current_position)

    def move(self, x: int, y: int):
        if not self.current_image:
            return
        self.current_position = (int(x), int(y))
        print("move > _render")
        self._render(self.current_image, *self.current_position)

    def hide(self):
        self.current_image = None
        # 【修正】attributes("-alpha") の呼び出しを削除
        try:
            if self.window.winfo_exists():
                self.window.withdraw()
        except tk.TclError:
            pass

    def ensure_visible(self):
        """ウィンドウを再表示して最前面へ引き上げる。"""
        try:
            if self.window.winfo_exists():
                self.window.deiconify()
                self.window.update_idletasks()
        except tk.TclError:
            pass

    def destroy(self):
        try:
            self.hide()
        finally:
            if self.window.winfo_exists():
                self.window.destroy()

    def lift_above(self, base: tk.Toplevel):
        """
        Zオーダーの制御は呼び出し元の_update_z_orderに一任するため、このメソッドでは何もしません。(修正)
        """
        pass

    def _render(self, image: Image.Image, x: int, y: int):
        width, height = image.size
        if width <= 0 or height <= 0:
            self.hide()
            return

        # UpdateLayeredWindowを呼び出す前に、Tkinterウィンドウオブジェクトの
        # ジオメトリをOSレベルで更新される予定の位置とサイズに設定しておく。
        # これにより、Tkinter内部の状態とOSの状態の同期が取れ、
        # 見切れや追従漏れの問題を防ぐ。
        try:
            if self.window.winfo_exists():
                self.window.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:
            # ウィンドウが破棄されている場合は何もしない
            return

        image_data = image.tobytes("raw", "BGRA")

        hdc = self._user32.GetDC(0)
        mem_dc = self._gdi32.CreateCompatibleDC(hdc)

        bmi = BITMAPINFO()
        ctypes.memset(ctypes.byref(bmi), 0, ctypes.sizeof(bmi))
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        bits = ctypes.c_void_p()
        dib = self._gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        if not dib:
            self._cleanup_dc(hdc, mem_dc)
            return

        old_bitmap = self._gdi32.SelectObject(mem_dc, dib)
        ctypes.memmove(bits, image_data, len(image_data))

        size = SIZE(width, height)
        point_dest = POINT(int(x), int(y))
        point_src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

        self._user32.UpdateLayeredWindow(
            self.hwnd,
            hdc,
            ctypes.byref(point_dest),
            ctypes.byref(size),
            mem_dc,
            ctypes.byref(point_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )

        self._gdi32.SelectObject(mem_dc, old_bitmap)
        self._gdi32.DeleteObject(dib)
        self._cleanup_dc(hdc, mem_dc)
        
        try:
            if self.window.winfo_exists():
                # ウィンドウが現在非表示の場合にのみ deiconify() を呼び出す。
                # これにより、移動時など既に表示されている場合にはZオーダーが変更されなくなる。
                if not self.window.winfo_viewable():
                    print("windows_alpha_overlay.py > _render > self.window.deiconify() ")
                    self.window.deiconify() 
                self.window.update_idletasks()
        except tk.TclError:
            pass

    def _cleanup_dc(self, hdc, mem_dc):
        self._gdi32.DeleteDC(mem_dc)
        self._user32.ReleaseDC(0, hdc)
