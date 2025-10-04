# src/character_ui.py

import tkinter as tk
from configparser import ConfigParser
from typing import TYPE_CHECKING
from PIL import Image, ImageTk
import os
from tkinter import font
from tkinterdnd2 import DND_FILES, TkinterDnD
import re
import numpy as np

# --- 自作モジュールのインポート ---
from src.emotion_handler import EmotionHandler
from src.input_box import InputBox
from src.output_box import OutputBox
from src.input_history_manager import InputHistoryManager
from src.windows_alpha_overlay import WindowsAlphaOverlay

# --- Windows API関連のインポート (追加) ---
if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    # SetWindowPos Flags
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    SWP_NOOWNERZORDER = 0x0200
    # HWND constants
    HWND_TOP = 0
    HWND_BOTTOM = 1

# 循環参照を避けるための型チェック用インポート
if TYPE_CHECKING:
    from src.character_controller import CharacterController

class MascotDNDWindow(tk.Toplevel, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)

class ChoiceDialog(tk.Toplevel):
    """イベントの選択肢を表示するためのカスタムダイア
    ログ"""
    def __init__(self, parent, character_controller, prompt, options):
        super().__init__(parent)
        self.char_ctrl = character_controller
        self.app = self.char_ctrl.mascot_app
        theme = self.app.theme_manager

        self.title("") # タイトルバーは空に
        self.transient(parent) # 親ウィンドウの上に表示
        self.grab_set()      # このダイアログ以外を操作できなくする
        self.resizable(False, False)

        # MODIFIED: ×ボタンでウィンドウを閉じられないようにする
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        
        self.configure(bg=theme.get('bg_main'))
        
        main_frame = tk.Frame(self, bg=theme.get('bg_main'), padx=self.app.padding_large, pady=self.app.padding_large)
        main_frame.pack(expand=True, fill="both")
        
        # 問いかけ文
        prompt_label = tk.Label(
            main_frame,
            text=prompt,
            font=self.app.font_normal,
            bg=theme.get('bg_main'),
            fg=theme.get('bg_text'),
            wraplength=int(self.winfo_screenwidth() * 0.3), # ウィンドウ幅に応じて自動で改行
            justify="left"
        )
        prompt_label.pack(pady=(0, self.app.padding_large))
        
        # 選択肢ボタン
        for option in options:
            text = option.get("text")
            jump_to = option.get("jump_to")

            def create_callback(label, choice_text):
                return lambda: self.on_choice_selected(label, choice_text)

            btn = tk.Button(
                main_frame,
                text=text,
                command=create_callback(jump_to, text),
                font=self.app.font_normal,
                fg=theme.get('button_text'),
                bg=theme.get('button_bg'),
                activeforeground=theme.get('button_active_text'),
                activebackground=theme.get('button_active_bg')
            )
            btn.pack(pady=self.app.padding_small, fill="x")

        # ウィンドウの位置をキャラクターの近くに調整
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() / 2) - (self.winfo_width() / 2)
        y = parent.winfo_y() + (parent.winfo_height() / 3) - (self.winfo_height() / 2)
        self.geometry(f"+{int(x)}+{int(y)}")

    def on_choice_selected(self, label, choice_text):
        """選択肢がクリックされたときの処理"""
        self.destroy() # ダイアログを閉じる
        self.char_ctrl.handle_event_choice_selection(label, choice_text)

class CharacterUIGroup(MascotDNDWindow):
    """
    キャラクター1体分のUI要素（画像、セリフ表示欄、入力欄）を管理するToplevelウィンドウクラス。
    各キャラクターはこのクラスのインスタンスを1つ持ちます。
    """
    # クラス変数として名前欄のサイズ設定を「キャラクターウィンドウ幅に対する比率」で定義
    NAMEPLATE_SIZE_CONFIG = {
        'small': {'min_ratio': 0.3, 'max_ratio': 0.6},  # キャラクター幅の30%～60%
        'medium': {'min_ratio': 0.45, 'max_ratio': 0.8}, # キャラクター幅の45%～80%
        'large': {'min_ratio': 0.6, 'max_ratio': 0.9}   # キャラクター幅の60%～90%
    }
    CHARACTER_FRAME_OFFSET_RATIO = 0.05 # キャラクター幅の5%

    def __init__(self, character_controller: 'CharacterController', config: ConfigParser, char_config: 'ConfigParser', input_history_manager: InputHistoryManager):
        theme = character_controller.mascot_app.theme_manager
        super().__init__(character_controller.mascot_app.root)
        self.char_ctrl = character_controller
        app = self.char_ctrl.mascot_app # appインスタンスへのショートカット
        
        # --- Win32 APIの準備 (追加) ---
        if os.name == 'nt':
            self._user32 = ctypes.windll.user32
            self._user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            self._user32.SetWindowPos.restype = wintypes.BOOL
        
        transparent_color = self.char_ctrl.transparent_color
        active_transparency_mode = self.char_ctrl.transparency_mode
        
        self.tk_heart_images = {}
        self.alpha_heart_images = {} # アルファモード用のハート画像キャッシュ
        self.current_layout_side = None

        self.tk_still_images = {} # イベントスチル用の画像キャッシュ
        self.alpha_still_images = {}
        self.event_choice_buttons = [] # 選択肢ボタンの参照を保持

        self.tooltip_window = None

        self.fade_job = None # フェードアニメーションのIDを保持

        self.alpha_overlay = None
        
        # --- 多重実行防止用のフラグ (追加) ---
        self._is_updating_positions = False
        self._is_updating_z_order = False

        self.overrideredirect(True)
        self.wm_attributes("-transparentcolor", transparent_color)
        self.configure(bg=transparent_color)
        
        # 設定から基本の幅を取得
        self.base_window_width = self.char_ctrl.mascot_app.window_width
        
        # 名前欄の表示状態とサイズ設定をアプリケーションから取得
        self.is_nameplate_visible = app.is_nameplate_visible.get()
        self.nameplate_size_key = app.nameplate_size_setting.get()
        self._calculate_nameplate_px() # 設定に基づいてピクセル幅を計算

        
        # --- メインフレームの構成 ---
        main_frame = tk.Frame(self, bg=transparent_color)
        main_frame.pack(expand=True, fill="both")

        self.character_display_frame = tk.Frame(main_frame, bg=transparent_color)

        border_color = theme.get('bg_accent')
        # ボーダー幅を基準単位で指定
        border_width = app.padding_small 
        self.io_container_frame = tk.Frame(main_frame, bg=theme.get('bg_main'))
        self.io_container_frame.config(
            highlightbackground=border_color, highlightthickness=border_width, highlightcolor=border_color,
        )
        self.io_container_frame.pack(side="bottom", fill="x", expand=True,padx=(self.character_frame_offset_px, 0))
        
        # InputBoxとOutputBoxのインスタンス化時にappを渡す
        self.output_box = OutputBox(self.io_container_frame, app, self.char_ctrl)
        self.input_box = InputBox(self.io_container_frame, self.char_ctrl, self.handle_send_message, input_history_manager, app)

        # 「次へ」ボタンをInputBoxと同じ場所に作成し、最初は隠しておく
        self.event_proceed_button = tk.Button(
            self.input_box.frame, # InputBoxのフレームを親にする
            text="次へ",
            command=self.char_ctrl.proceed_event,
            font=app.font_normal,
            fg=theme.get('button_text'),
            bg=theme.get('button_bg'),
            activeforeground=theme.get('button_active_text'),
            activebackground=theme.get('button_active_bg')
        )

         # 「次へ」ボタンをInputBoxと同じ場所に作成し、最初は隠しておく
        self.event_proceed_button = tk.Button(
            self.input_box.frame, # InputBoxのフレームを親にする
            text="次へ",
            command=self.char_ctrl.proceed_event,
            font=app.font_normal,
            fg=theme.get('button_text'),
            bg=theme.get('button_bg'),
            activeforeground=theme.get('button_active_text'),
            activebackground=theme.get('button_active_bg')
        )

        # --- 名札を独立したToplevelウィンドウとして作成 ---
        self.name_window = tk.Toplevel(self)
        self.name_window.overrideredirect(True)
        self.name_window.withdraw() # 最初は非表示

        name_label_border_width = app.border_width_normal * 2
        # 枠線用のFrameを挟むことで、Toplevelに枠線のような見た目を実装
        name_border_frame = tk.Frame(
            self.name_window,
            bg=theme.get('nameplate_bg'),
            highlightbackground=theme.get('nameplate_bg'),
            highlightthickness=name_label_border_width
        )
        name_border_frame.pack(fill='both', expand=True)

        self.name_font = app.font_title
        self.name_font_obj = font.Font(font=self.name_font)

        self.name_label = tk.Label(
            name_border_frame, # 親を枠線フレームに変更
            text=self.char_ctrl.name,
            font=self.name_font, 
            bg=theme.get('nameplate_bg'),
            fg=theme.get('nameplate_text'),
            padx=0,
            pady=0,
            justify='center',
        )
        self.name_label.pack(fill='both', expand=True)

        # --- ハート用のUIコンポーネントを初期化 ---
        self.heart_window = tk.Toplevel(self) # カラーキーモード用の土台ウィンドウ
        self.heart_window.overrideredirect(True)
        self.heart_window.withdraw()
        
        self.heart_alpha_overlay = None # アルファモード用のオーバーレイ
        if self.char_ctrl.heart_transparency_mode == 'alpha' and os.name == 'nt':
            try:
                # アルファモードの場合、オーバーレイウィンドウを準備
                self.heart_alpha_overlay = WindowsAlphaOverlay(self)
                # 土台ウィンドウは完全に透明にしておく
                self.heart_window.attributes("-alpha", 0.0)
            except Exception as e:
                print(f"警告: ハートのアルファ透過ウィンドウ初期化に失敗。color_keyにフォールバックします: {e}")
                self.char_ctrl.heart_transparency_mode = 'color_key'
                self.heart_alpha_overlay = None # 失敗した場合はNoneに戻す
        
        # カラーキーモード用の設定 (フォールバックした場合もここが使われる)
        if self.char_ctrl.heart_transparency_mode == 'color_key':
            trans_color = self.char_ctrl.heart_transparent_color or self.char_ctrl.transparent_color
            self.heart_window.wm_attributes("-transparentcolor", trans_color)
            self.heart_window.configure(bg=trans_color)
            self.heart_window_label = tk.Label(self.heart_window, bg=trans_color)
            self.heart_window_label.pack()
        else: # アルファモードの場合
            # ラベルは不要だが、互換性のためにダミーを作成
            self.heart_window_label = tk.Label(self.heart_window)
        
        # オーバーレイウィンドウの初期化
        self.overlay_window = tk.Toplevel(self)
        self.overlay_window.overrideredirect(True)
        self.overlay_window.configure(bg="#000000") # 初期色は黒
        self.overlay_window.wm_attributes("-alpha", 0.0) # 最初は完全に透明
        self.overlay_window.withdraw() # 最初は非表示

        if active_transparency_mode == 'alpha':
            try:
                self.alpha_overlay = WindowsAlphaOverlay(self)
            except Exception as e:
                print(f"警告: アルファ透過ウィンドウの初期化に失敗しました。color_key モードへフォールバックします: {e}")
                self.alpha_overlay = None
                active_transparency_mode = 'color_key'
                self.char_ctrl.transparency_mode = 'color_key'

        self.emotion_handler = EmotionHandler(
            self.character_display_frame, self,
            config, char_config, self.char_ctrl, self.base_window_width,
            self.char_ctrl.mascot_app.transparency_tolerance,
            self.char_ctrl.edge_color,
            self.char_ctrl.is_left_side,
            active_transparency_mode
        )
        self.active_transparency_mode = active_transparency_mode

        # ドロップを受け付けるウィジェットのリスト
        self.drop_targets = [
            self.emotion_handler.image_label, # キャラクター画像
            self.output_box.text_widget       # セリフ表示欄
        ]
        # 各ウィジェットにD&Dの設定を適用
        for widget in self.drop_targets:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind('<<Drop>>', self.on_character_drop)
        
        # レイアウトの初期設定
        initial_side = self.char_ctrl.initial_position_side
        self._relayout_display(initial_side)

        # ウィンドウがフォーカスを得た際のイベントをバインド
        self.bind("<FocusIn>", self._on_focus_in)
        self.heart_window.bind("<FocusIn>", self._on_focus_in)
        self.name_window.bind("<FocusIn>", self._on_focus_in) # 追加

        self.bind("<Button-1>", self.on_window_click)
        self.heart_window.bind("<Button-1>", self.on_window_click)
        self.name_window.bind("<Button-1>", self.on_window_click)
        self.name_label.bind("<Button-1>", self.on_window_click)

        self.output_box.text_widget.bind("<Button-1>", self.on_window_click)
        self.input_box.entry.bind("<Button-1>", self.on_window_click)

        # イベントのバインド
        self.character_display_frame.bind('<Button-3>', lambda event: self.char_ctrl.mascot_app.show_context_menu(event, self.char_ctrl))
        self.name_label.bind('<Button-3>', lambda event: self.char_ctrl.mascot_app.show_context_menu(event, self.char_ctrl))
        self.name_window.bind('<Button-3>', lambda event: self.char_ctrl.mascot_app.show_context_menu(event, self.char_ctrl))
        self.emotion_handler.image_label.bind('<Button-3>', lambda event: self.char_ctrl.mascot_app.show_context_menu(event, self.char_ctrl))
        # ハート関連のイベントは、アルファ/カラーキーでバインド先を切り替える
        heart_event_target = self.heart_alpha_overlay.window if self.heart_alpha_overlay else self.heart_window_label
        heart_event_target.bind('<Button-3>', lambda event: self.char_ctrl.mascot_app.show_context_menu(event, self.char_ctrl))
        heart_event_target.bind('<Enter>', self.show_favorability_tooltip)
        heart_event_target.bind('<Leave>', self.hide_favorability_tooltip)

        self.geometry("+9999+9999")

    def resize(self, new_window_width: int):
        """ウィンドウ全体のサイズを動的に変更する"""
        # 1. 基準となるウィンドウ幅を更新
        self.base_window_width = new_window_width
        
        # 新しい幅に基づいて、名前欄のピクセルサイズを再計算
        self._calculate_nameplate_px()

        # 2. EmotionHandlerにサイズ変更を通知し、画像をリロードさせる
        self.emotion_handler.resize(new_window_width)
        
        # 3. ウィンドウ全体のジオメトリとレイアウトを再計算
        self.update_geometry()
        self.check_and_update_layout(force_update=True)
        # 4. ハート表示も再計算
        self._update_heart_label()
        self.lift_window()

    def _get_trimmed_name_text(self):
        """名前が最大幅を超える場合、末尾を '...' で省略した文字列を返す"""
        original_name = self.char_ctrl.name
        # パディングを基準単位で指定
        padding = self.char_ctrl.mascot_app.padding_large
        
        text_width = self.name_font_obj.measure(original_name)
        
        if text_width + padding <= self.max_name_width_px:
            return original_name
        
        trimmed_name = original_name
        while self.name_font_obj.measure(trimmed_name + "...") + padding > self.max_name_width_px and len(trimmed_name) > 0:
            trimmed_name = trimmed_name[:-1]
            
        return trimmed_name + "..."

    def _on_focus_in(self, event=None):
        """このウィンドウまたは関連ウィンドウがフォーカスを得たときに重なり順を修正する"""
        self.lift_window()

    def finalize_initial_position(self):
        """起動シーケンスの最後に呼び出され、ウィンドウとハートの位置を最終確定させる"""
        self.after(50, self._place_window_initially)

    def _place_window_initially(self):
        """初回起動時のウィンドウ配置を計算し、適用する内部メソッド"""
        self.update_idletasks()

        char_frame_width = self.character_display_frame.winfo_reqwidth()
        width = max(char_frame_width, self.base_window_width)
        height = self.winfo_reqheight()

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        x_pos = 0 if self.char_ctrl.initial_position_side == 'left' else screen_width - width
        
        taskbar_offset = int(screen_height * 0.04)
        y_pos = screen_height - height - taskbar_offset
        
        self.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

        self._update_positions()
        print("_place_window_initially > self._update_z_order()")
        self._update_z_order()
        self.check_and_update_layout()

    def on_window_click(self, event=None):
        """ウィンドウのいずれかの部分がクリックされたときに重なり順を整える"""
        self.lift_window()

    def _update_z_order(self):
        """
        SetWindowPosを使用して、関連ウィンドウの重なり順をアクティブ化せずに制御します。(修正)
        多重実行を防止するロック機構を追加し、コンポーネントの存在チェックとZオーダーのロジックを修正。
        """
        if self._is_updating_z_order:
            return
        self._is_updating_z_order = True
        try:
            if not self.winfo_exists() or os.name != 'nt':
                return

            # ベースウィンドウ以外のコンポーネントを「手前 → 奥」の順で列挙
            overlay_components = [
                self.heart_alpha_overlay,  # ハートのアルファ (最前面)
                self.heart_window,         # ハート本体
                self.name_window,          # 名前欄
                self.overlay_window,       # キャラクター画像などのオーバーレイ
                self.alpha_overlay,        # 全体アルファ (ベースの直前)
            ]

            # Win32では、同じオーナーを持つウィンドウを前面へ積み直す際に
            # 1) ベースウィンドウを明示的に最背面へ送る
            # 2) 残りを背面→前面の順で HWND_TOP へ積み上げる
            # ことで、期待した重なり順を確実に作れる。

            base_hwnd = self.winfo_id()
            self._user32.SetWindowPos(
                base_hwnd,
                HWND_BOTTOM,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
            )

            valid_hwnds = []
            for component in overlay_components:
                # component自体がNoneの場合をチェック
                if not component:
                    continue

                win_obj = getattr(component, 'window', component)

                try:
                    exists = bool(win_obj and win_obj.winfo_exists())
                except tk.TclError:
                    continue

                if not exists:
                    continue

                # WindowsAlphaOverlay系は has_image で表示状態を管理している。
                # winfo_viewable() だけに依存すると、描画済みでも常に除外されてしまうため
                # has_image が真である場合はZオーダー更新の対象とする。
                if hasattr(component, 'has_image'):
                    if not component.has_image:
                        continue
                else:
                    try:
                        if not win_obj.winfo_viewable():
                            continue
                    except tk.TclError:
                        continue

                valid_hwnds.append(win_obj.winfo_id())

            for hwnd_to_place in reversed(valid_hwnds):
                # SetWindowPosでZオーダーを設定。SWP_NOOWNERZORDERを指定して親ウィンドウの順序変化を抑止しつつ、
                # HWND_TOP で逐次前面へ積み直す。
                self._user32.SetWindowPos(
                    hwnd_to_place,
                    HWND_TOP,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
                )

        except (tk.TclError, AttributeError):
            # ウィンドウ破棄後などに発生する可能性のあるエラーを安全に無視
            pass
        finally:
            self._is_updating_z_order = False

    def _update_positions(self):
        """
        関連ウィンドウの位置を同期させます。(修正)
        多重実行を防止するロック機構を追加。
        """
        if self._is_updating_positions:
            return
        self._is_updating_positions = True
        try:
            self._update_name_window_position()
            self._update_heart_window_position()
            self._update_overlay_window_position()
            self._update_alpha_window_position()
        finally:
            self._is_updating_positions = False

    def lift_window(self):
        """キャラクターウィンドウ群を他のアプリケーションより手前に表示します。(修正)"""
        if not self.winfo_exists(): return
        
        # super().lift() を削除し、Zオーダーの制御を_update_z_orderに完全に委任する
        print("lift_window > self._update_z_order()")
        self._update_z_order()

    def move_window(self, new_x, new_y):
        """キャラクターウィンドウ群全体を移動させます。(新設)"""
        if not self.winfo_exists(): return
        
        # 1. ベースウィンドウを移動
        self.geometry(f"+{int(new_x)}+{int(new_y)}")
        
        # 2. 関連ウィンドウの位置を追従させる
        self._update_positions()
        
        # 3. Zオーダーも念のため更新（ドラッグ中に他のウィンドウが挟まるのを防ぐ）
        print("move_window > self._update_z_order()")
        self._update_z_order()

    def move_to_side(self, side: str):
        self.update_idletasks()
        
        screen_center_x = self.winfo_screenwidth() / 2
        window_center_x = self.winfo_x() + (self.winfo_width() / 2)
        was_on_left = window_center_x < screen_center_x
        
        is_moving_to_left = (side == 'left')
        
        self.check_and_update_layout(force_update=True)
        self.update_idletasks()
        width = self.character_display_frame.winfo_reqwidth()
        height = self.winfo_reqheight()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        if side == 'left': x_pos = 0
        elif side == 'right': x_pos = screen_width - width
        else: return
        
        taskbar_offset = int(screen_height * 0.04)
        y_pos = screen_height - height - taskbar_offset
        self.move_window(x_pos, y_pos)

        if was_on_left != is_moving_to_left:
            self.char_ctrl.flip_character()
        else:
            self.check_and_update_layout()

    def check_and_update_layout(self, force_update=False):
        """現在のウィンドウ位置をチェックし、必要であればレイアウトを再構築する。"""
        self.update_idletasks()
        
        screen_center_x = self.winfo_screenwidth() / 2
        window_center_x = self.winfo_x() + (self.winfo_width() / 2)
        
        new_side = 'left' if window_center_x < screen_center_x else 'right'
        
        if force_update or (new_side != self.current_layout_side):
            self._relayout_display(new_side)

    def _relayout_display(self, side: str):
        """place()を使い、名前欄の幅を制御しながらレイアウトを再構築（名札は画像に重なる）"""
        print(f"レイアウトを '{side}' サイド用に変更します。")
        self.current_layout_side = side

        for widget in self.character_display_frame.winfo_children():
            if not isinstance(widget, tk.Toplevel):
                try:
                    widget.place_forget()
                except tk.TclError:
                    pass
        
        self.character_display_frame.pack_forget()
        self.io_container_frame.pack_forget()

        self.update_idletasks()
        
        if side == 'left':
            char_anchor = 'e'
            io_padx = (0, self.character_frame_offset_px)
        else: # 'right'
            char_anchor = 'w'
            io_padx = (self.character_frame_offset_px, 0)

        self.character_display_frame.pack(side="top", anchor=char_anchor)
        self.io_container_frame.pack(
            side="bottom",
            fill="x",
            expand=True,
            padx=io_padx
        )
        
        image_label = self.emotion_handler.image_label
        name_label = self.name_label

        trimmed_name = self._get_trimmed_name_text()
        name_label.config(text=trimmed_name)
        
        actual_text_width = self.name_font_obj.measure(trimmed_name)
        padding = self.char_ctrl.mascot_app.padding_large
        name_label_width = max(self.min_name_width_px, min(actual_text_width + padding, self.max_name_width_px))

        self.update_idletasks()
        image_width = self.emotion_handler.image_label.winfo_reqwidth()
        image_height = self.emotion_handler.image_label.winfo_reqheight()

        self.character_display_frame.config(width=image_width, height=image_height)
        self.emotion_handler.image_label.place(x=0, y=0)

        self._update_name_window_position()

        self.update_geometry()

    def update_character_image(self, tk_image, alpha_image=None, lift_ui: bool = False):
        # 1. 標準の画像ラベルを更新 (カラーキーモード用)
        if tk_image:
            self.emotion_handler.image_label.config(image=tk_image)
        else:
            self.emotion_handler.image_label.config(image="")

        # 2. アルファオーバーレイウィンドウが存在する場合 (TRANSPARENCY_MODE = alpha)
        if self.alpha_overlay:
            if alpha_image is not None:
                self.update_idletasks() 
                try:
                    frame_x = self.character_display_frame.winfo_rootx()
                    frame_y = self.character_display_frame.winfo_rooty()
                    
                    # 2a. 画像を描画し、ウィンドウを再表示する。
                    #    この関数の内部で deiconify() が呼ばれるため、この時点で
                    #    キャラクターウィンドウが一時的に最前面に来てしまい、Zオーダーが崩れる。
                    self.alpha_overlay.update_image(alpha_image, frame_x, frame_y)

                    # 2b. deiconify() によって崩れたZオーダーを即座に再修正する。
                    #    これにより、名前欄やハートが常にキャラクターより手前に表示されることが保証される。
                    #    lift_ui フラグに関わらず、alphaモードでの画像更新時は常にこの修正が必要。
                    print("update_character_image > self._update_z_order()")
                    self._update_z_order()
                except tk.TclError:
                    return
            else:
                self.alpha_overlay.hide()

        # 3. カラーキーモードの場合、lift_ui フラグが True の時のみZオーダーを更新する
        #    (alphaモードでは上記 2b で既に更新されているため、ここには入らない)
        elif lift_ui:
            self.lift_window()

    def enter_event_mode(self):
        """イベント再生モードに移行する。"""
        self.input_box.entry.pack_forget()
        self.input_box.send_button.pack_forget()
        self.event_proceed_button.pack(side="right", padx=self.char_ctrl.mascot_app.padding_small, pady=self.char_ctrl.mascot_app.padding_small)
        self.event_proceed_button.config(state="disabled")

    def enter_event_wait_mode(self):
        """相方がイベント中の待機モードに移行する。"""
        self.input_box.entry.config(state="disabled")
        self.input_box.send_button.config(state="disabled")
        self.output_box.set_text("（...しずかに見守っている）")

    def exit_event_mode(self):
        """通常モードに復帰する。"""
        self.event_proceed_button.pack_forget()
        self._clear_choice_buttons()
        
        self.input_box.entry.pack(side="left", fill="x", expand=True, padx=self.char_ctrl.mascot_app.padding_small, pady=self.char_ctrl.mascot_app.padding_small)
        self.input_box.send_button.pack(side="right", padx=self.char_ctrl.mascot_app.padding_small, pady=self.char_ctrl.mascot_app.padding_small)
        self.input_box.entry.config(state="normal")
        self.input_box.send_button.config(state="normal")
        
        self.emotion_handler.update_image("normal", lift_ui=True)
        self.output_box.set_text("...")

    def display_event_dialogue(self, text: str, emotion_jp: str, still_image_filename: str = None, transparent_color: str = None, edge_color: str = None):
        """イベントのセリフ/モノローグを表示する。"""
        self._clear_choice_buttons()
        self.event_proceed_button.config(state="disabled")
        self.output_box.set_text(text)

        if still_image_filename:
            self._show_still_image(still_image_filename, transparent_color, edge_color)
        else:
            self.emotion_handler.update_image(emotion_jp, lift_ui=True)

    def display_event_choices(self, prompt: str, options: list):
        """イベントの選択肢をカスタムダイアログで表示する。"""
        self.output_box.set_text(prompt)
        self.event_proceed_button.pack_forget()
        self._clear_choice_buttons()
        ChoiceDialog(self, self.char_ctrl, prompt, options)

    def _clear_choice_buttons(self):
        """表示されている選択肢ボタンを全て削除する。"""
        for btn in self.event_choice_buttons:
            btn.destroy()
        self.event_choice_buttons.clear()

    def enable_event_proceed_button(self):
        """「次へ」ボタンをクリック可能にする。"""
        self.event_proceed_button.config(state="normal")
        
    def _show_still_image(self, filename: str, transparent_color: str = None, edge_color: str = None):
        """イベントスチル画像を読み込んで表示する。"""
        cache_key = f"{filename}_{transparent_color}_{edge_color}"
        tk_image = self.tk_still_images.get(cache_key)
        alpha_image = None
        if self.active_transparency_mode == 'alpha':
            alpha_image = self.alpha_still_images.get(cache_key)

        if not tk_image:
            try:
                stills_dir = os.path.join(self.char_ctrl.character_dir, "stills")
                image_path = os.path.join(stills_dir, filename)
                
                with Image.open(image_path) as img_pil:
                    aspect_ratio = img_pil.height / img_pil.width
                    resized_img = img_pil.resize((self.emotion_handler.window_width, int(self.emotion_handler.window_width * aspect_ratio)), Image.Resampling.LANCZOS)
                    
                    if self.active_transparency_mode == 'alpha':
                        rgba_img = resized_img.convert("RGBA")
                        
                        # --- ここから修正 ---
                        # プリマルチプライドアルファ形式に変換
                        data = np.array(rgba_img, dtype=np.uint8)
                        alpha = (data[:, :, 3] / 255.0)[:, :, np.newaxis]
                        rgb = data[:, :, :3]
                        premultiplied_rgb = (rgb * alpha).astype(np.uint8)
                        data[:, :, :3] = premultiplied_rgb
                        low_alpha_mask = data[:, :, 3] < 10
                        data[low_alpha_mask] = [0, 0, 0, 0]
                        processed_img = Image.fromarray(data)
                        # --- ここまで修正 ---

                        tk_image = self.emotion_handler.get_placeholder_for_size(processed_img.width, processed_img.height)
                        alpha_image = processed_img
                    else:
                        trans_hex = transparent_color or self.char_ctrl.transparent_color
                        edge_hex = edge_color or self.char_ctrl.edge_color
                        trans_rgb = self.emotion_handler._hex_to_rgb(trans_hex)
                        edge_rgb = self.emotion_handler._hex_to_rgb(edge_hex)
                        processed_img = self.emotion_handler._process_transparency(resized_img, trans_rgb, edge_rgb)
                        tk_image = ImageTk.PhotoImage(processed_img)

                if tk_image:
                    self.tk_still_images[cache_key] = tk_image
                    if self.active_transparency_mode == 'alpha' and alpha_image is not None:
                        self.alpha_still_images[cache_key] = alpha_image
                else:
                    print(f"エラー: スチル画像 '{filename}' の読み込みに失敗しました。")
                    self.emotion_handler.update_image("troubled", lift_ui=True)
                    return
            except Exception as e:
                print(f"スチル画像の処理中にエラー: {e}")
                self.emotion_handler.update_image("troubled", lift_ui=True)
                return

        self.update_character_image(tk_image, alpha_image, lift_ui=True)
        self.emotion_handler.is_showing_still = True

    def prepare_for_next_event_step(self):
        """選択肢ダイアログが閉じた後など、次のイベントステップに備えるためのUI準備を行う。"""
        self._clear_choice_buttons()
        self.event_proceed_button.pack(side="right", padx=self.char_ctrl.mascot_app.padding_small, pady=self.char_ctrl.mascot_app.padding_small)
        self.event_proceed_button.config(state="disabled")


    def handle_send_message(self, user_input):
        if not user_input.strip(): return
        if self.char_ctrl.mascot_app.is_event_running:
            return
        self.char_ctrl.handle_user_input(user_input)
        self.input_box.clear_text()

    def _calculate_nameplate_px(self):
        """現在のサイズ設定とキャラクターウィンドウ幅に基づいて名前欄のピクセル幅を計算・設定する"""
        size_config = self.NAMEPLATE_SIZE_CONFIG.get(self.nameplate_size_key, self.NAMEPLATE_SIZE_CONFIG['medium'])
        base_width = self.base_window_width 
        self.min_name_width_px = int(base_width * size_config['min_ratio'])
        self.max_name_width_px = int(base_width * size_config['max_ratio'])
        self.character_frame_offset_px = int(base_width * self.CHARACTER_FRAME_OFFSET_RATIO)

    def update_nameplate_visibility(self, is_visible: bool):
        """名前欄の表示/非表示を切り替える"""
        self.is_nameplate_visible = is_visible
        if self.is_nameplate_visible:
            self._update_name_window_position()
        else:
            if self.name_window and self.name_window.winfo_exists():
                self.name_window.withdraw()
        self.lift_window()

    def update_nameplate_size(self, size_key: str):
        """名前欄のサイズ設定を更新し、UIに即時反映する"""
        self.nameplate_size_key = size_key
        self._calculate_nameplate_px()
        self.check_and_update_layout(force_update=True)
        self.update_geometry()
        self.lift_window()

    def _update_name_window_position(self):
        """名前欄ウィンドウの位置、サイズ、表示を更新する"""
        if not self.is_nameplate_visible:
            if self.name_window and self.name_window.winfo_exists():
                self.name_window.withdraw()
            return

        if not self.winfo_exists() or not self.name_window.winfo_exists(): return
        self.update_idletasks()

        trimmed_name = self._get_trimmed_name_text()
        self.name_label.config(text=trimmed_name)
        
        actual_text_width = self.name_font_obj.measure(trimmed_name)
        padding = self.char_ctrl.mascot_app.padding_large
        name_win_width = max(self.min_name_width_px, min(actual_text_width + padding, self.max_name_width_px))

        self.name_window.update_idletasks() 
        name_win_height = self.name_label.winfo_reqheight()

        frame_abs_x = self.character_display_frame.winfo_rootx()
        frame_abs_y = self.character_display_frame.winfo_rooty()
        frame_width = self.character_display_frame.winfo_width()
        frame_height = self.character_display_frame.winfo_height()

        y_pos = frame_abs_y + frame_height - name_win_height

        if self.current_layout_side == 'left':
            x_pos = frame_abs_x + frame_width - name_win_width
        else: # 'right'
            x_pos = frame_abs_x
            
        self.name_window.geometry(f"{name_win_width}x{name_win_height}+{int(x_pos)}+{int(y_pos)}")
        print("character_ui.py > _update_name_window_position > self.name_window.deiconify()")
        self.name_window.deiconify()

    def update_geometry(self, force_x=None):
        """
        ウィンドウのサイズと位置を更新する。下辺を基準に高さを調整する。
        """
        try:
            old_x = self.winfo_x()
            old_y = self.winfo_y()
            old_height = self.winfo_height()
            old_bottom = old_y + old_height
        except tk.TclError:
            old_x = 0
            old_bottom = self.winfo_screenheight()

        self.update_idletasks()

        char_frame_width = self.character_display_frame.winfo_reqwidth()
        new_width = max(char_frame_width, self.base_window_width)
        new_height = self.winfo_reqheight()

        new_x = force_x if force_x is not None else old_x
        new_y = old_bottom - new_height
        new_geometry = f"{new_width}x{new_height}+{new_x}+{new_y}"
        
        if self.geometry() != new_geometry:
            self.geometry(new_geometry)

        self._update_positions()
        print("update_geometry > self._update_z_order()")
        self._update_z_order()
        self.check_and_update_layout()

    def update_info_display(self):
        pre_x = self.winfo_x()
        screen_width = self.winfo_screenwidth()

        # 初期配置前のプレースホルダー座標に留まっている場合は、再配置を実行する
        if pre_x >= screen_width or pre_x <= -screen_width:
            self._place_window_initially()
            pre_x = self.winfo_x()

        self.check_and_update_layout(force_update=True)
        self._update_heart_label()
        self.update_geometry(force_x=pre_x)
        self.lift_window()

    def _update_heart_label(self):
        """ハート画像を読み込み、専用ウィンドウに表示する"""
        image_filename = self.char_ctrl.get_current_heart_image_filename()
        mode = self.char_ctrl.heart_transparency_mode

        if not image_filename:
            self.heart_window.withdraw()
            if self.heart_alpha_overlay: self.heart_alpha_overlay.hide()
            return

        self.name_label.update_idletasks()
        name_label_height = self.name_label.winfo_reqheight()
        target_heart_height = name_label_height * 2
        cache_key = f"{image_filename}_{target_heart_height}"

        tk_image = None
        alpha_image = None
        
        if mode == 'alpha':
            alpha_image = self.alpha_heart_images.get(cache_key)
        else:
            tk_image = self.tk_heart_images.get(cache_key)

        if not tk_image and not alpha_image:
            char_path = os.path.join(self.char_ctrl.character_dir, 'hearts', image_filename)
            default_path = os.path.join('images', 'hearts', image_filename)
            path_to_load = char_path if os.path.exists(char_path) else default_path if os.path.exists(default_path) else None
            
            if not path_to_load:
                self.heart_window.withdraw()
                if self.heart_alpha_overlay: self.heart_alpha_overlay.hide()
                return
            
            try:
                with Image.open(path_to_load) as img_pil:
                    aspect_ratio = img_pil.width / img_pil.height
                    new_width = int(target_heart_height * aspect_ratio)
                    resized_img = img_pil.resize((new_width, target_heart_height), Image.Resampling.LANCZOS)

                    if mode == 'alpha':
                        rgba_img = resized_img.convert("RGBA")

                        # --- ここから修正 ---
                        # プリマルチプライドアルファ形式に変換
                        data = np.array(rgba_img, dtype=np.uint8)
                        alpha = (data[:, :, 3] / 255.0)[:, :, np.newaxis]
                        rgb = data[:, :, :3]
                        premultiplied_rgb = (rgb * alpha).astype(np.uint8)
                        data[:, :, :3] = premultiplied_rgb
                        low_alpha_mask = data[:, :, 3] < 10
                        data[low_alpha_mask] = [0, 0, 0, 0]
                        alpha_image = Image.fromarray(data)
                        # --- ここまで修正 ---
                        
                        self.alpha_heart_images[cache_key] = alpha_image
                    else:
                        trans_color_hex = self.char_ctrl.heart_transparent_color or self.char_ctrl.transparent_color
                        edge_color_hex = self.char_ctrl.heart_edge_color or self.char_ctrl.edge_color
                        trans_color_rgb = self.emotion_handler._hex_to_rgb(trans_color_hex)
                        edge_color_rgb = self.emotion_handler._hex_to_rgb(edge_color_hex)
                        processed_img = self.emotion_handler._process_transparency(resized_img, trans_color_rgb, edge_color_rgb)
                        tk_image = ImageTk.PhotoImage(processed_img)
                        self.tk_heart_images[cache_key] = tk_image
            except Exception as e:
                print(f"ハート画像の読み込み/処理に失敗: {path_to_load}, {e}")
                self.heart_window.withdraw()
                if self.heart_alpha_overlay: self.heart_alpha_overlay.hide()
                return

        image_width = 0
        image_height = 0

        if mode == 'alpha':
            if self.heart_alpha_overlay and alpha_image:
                image_width, image_height = alpha_image.size
                self.heart_window.geometry(f"{image_width}x{image_height}")
                self._update_heart_window_position()
                self.update_idletasks()
                root_x, root_y = self.heart_window.winfo_rootx(), self.heart_window.winfo_rooty()
                self.heart_alpha_overlay.update_image(alpha_image, root_x, root_y)
            else:
                if self.heart_alpha_overlay: self.heart_alpha_overlay.hide()
        else: # color_key
            if tk_image:
                image_width, image_height = tk_image.width(), tk_image.height()
                self.heart_window_label.config(image=tk_image)
                self.heart_window.geometry(f"{image_width}x{image_height}")
                self._update_heart_window_position()
            if self.heart_alpha_overlay: self.heart_alpha_overlay.hide()
        
        if image_width > 0:
            print("character_ui.py > _update_heart_label > self.heart_window.deiconify()")
            self.heart_window.deiconify()
        else:
            self.heart_window.withdraw()

    def _update_heart_window_position(self):
        """画面の左右に応じてハートの吸着面を切り替える"""
        try:
            if not self.heart_window.winfo_exists():
                return
            if not self.heart_window.winfo_viewable():
                return
        except tk.TclError:
            return

        self.update_idletasks()

        img_abs_x = self.emotion_handler.image_label.winfo_rootx()
        img_width = self.emotion_handler.image_label.winfo_width()
        name_abs_y = self.name_label.winfo_rooty()
        name_height = self.name_label.winfo_height()
        heart_win_width = self.heart_window.winfo_width()
        heart_win_height = self.heart_window.winfo_height()

        y_pos = (name_abs_y + name_height) - (heart_win_height/1.2)

        self.is_on_left_side = self.winfo_x() + (self.winfo_width() / 2) < self.winfo_screenwidth() / 2

        if self.is_on_left_side:
            x_pos = img_abs_x
        else:
            img_right_edge_abs_x = img_abs_x + img_width
            x_pos = img_right_edge_abs_x - heart_win_width
            
        self.heart_window.geometry(f"+{int(x_pos)}+{int(y_pos)}")
        try:
            self.heart_window.deiconify()
        except tk.TclError:
            pass

        self._update_heart_alpha_overlay_position()

    def _update_overlay_window_position(self):
        """キャラクターの画像表示領域にオーバーレイウィンドウを追従させる"""
        if not self.winfo_exists(): return
        self.update_idletasks()

        frame_x = self.character_display_frame.winfo_rootx()
        frame_y = self.character_display_frame.winfo_rooty()
        frame_width = self.character_display_frame.winfo_width()
        frame_height = self.character_display_frame.winfo_height()

        if frame_width > 1 and frame_height > 1:
            self.overlay_window.geometry(f"{frame_width}x{frame_height}+{frame_x}+{frame_y}")

    def _update_alpha_window_position(self):
        if not self.alpha_overlay or not self.alpha_overlay.has_image:
            return
        try:
            self.update_idletasks()
            frame_x = self.character_display_frame.winfo_rootx()
            frame_y = self.character_display_frame.winfo_rooty()
        except tk.TclError:
            return
        print(f"frame_x:{frame_x} | frame_y:{frame_y}")
        self.alpha_overlay.move(frame_x, frame_y)

    def _update_heart_alpha_overlay_position(self):
        """ハートのアルファオーバーレイの位置を、土台となるheart_windowに同期させる。"""
        if not self.heart_alpha_overlay or not self.heart_alpha_overlay.has_image:
            return
        try:
            self.heart_window.update_idletasks()
            x = self.heart_window.winfo_rootx()
            y = self.heart_window.winfo_rooty()
            self.heart_alpha_overlay.move(x, y)
            self.heart_alpha_overlay.ensure_visible()
        except tk.TclError:
            pass

    def apply_screen_effect(self, effect_type, color, method, duration_sec, callback):
        """UIに画面効果を適用する（黒いチラつき・前回の色残りを完全対策済み）"""
        if self.fade_job:
            self.after_cancel(self.fade_job)
            self.fade_job = None
        
        self._update_overlay_window_position()

        if effect_type == 'fade_out':
            if method == 'instant':
                self.overlay_window.configure(bg=color)
                self.overlay_window.wm_attributes("-alpha", 1.0)
                print("character_ui.py > apply_screen_effect > method == 'instant' > self.overlay_window.deiconify()")
                self.overlay_window.deiconify()
                self.overlay_window.update()
                self.lift_window()
                if callback: callback()
            elif method == 'fade':
                self.overlay_window.configure(bg=color)
                self.overlay_window.wm_attributes("-alpha", 0.0)
                print("character_ui.py > apply_screen_effect > method == 'fade' > self.overlay_window.deiconify()")
                self.overlay_window.deiconify()
                self.lift_window()
                steps = 20
                interval_ms = int((duration_sec * 1000) / steps) if duration_sec > 0 else 1
                self._fade_animation(0.0, 1.0, steps, 0, interval_ms, callback)

        elif effect_type == 'fade_in':
            if method == 'instant':
                self.overlay_window.wm_attributes("-alpha", 0.0)
                self.overlay_window.withdraw()
                self.overlay_window.update()
                if callback: callback()
            elif method == 'fade':
                steps = 20
                interval_ms = int((duration_sec * 1000) / steps) if duration_sec > 0 else 1
                self._fade_animation(1.0, 0.0, steps, 0, interval_ms, callback)
    
    def _fade_animation(self, start_alpha, end_alpha, total_steps, current_step, interval, callback):
        """フェードアニメーションの1フレームを処理する再帰メソッド"""
        current_step += 1
        progress = current_step / total_steps
        current_alpha = start_alpha + (end_alpha - start_alpha) * progress
        
        self.overlay_window.wm_attributes("-alpha", current_alpha)

        if current_step < total_steps:
            self.fade_job = self.after(interval, self._fade_animation, start_alpha, end_alpha, total_steps, current_step, interval, callback)
        else: # アニメーション完了
            self.fade_job = None
            if end_alpha == 0.0: # フェードイン完了時
                self.overlay_window.withdraw()
            if callback:
                callback()

    def hide_overlay(self):
        """オーバーレイウィンドウを即座に非表示にする"""
        if self.fade_job:
            self.after_cancel(self.fade_job)
            self.fade_job = None
        self.overlay_window.withdraw()

    def show_favorability_tooltip(self, event):
        if self.tooltip_window: self.tooltip_window.destroy()
        
        app = self.char_ctrl.mascot_app
        self.tooltip_window = tk.Toplevel(self.heart_window)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_attributes("-topmost", True)
        status = self.char_ctrl.get_user_recognition_status()
        score = self.char_ctrl.favorability
        tooltip_text = f"関係：{status}\n好感度：{score}"
        theme = self.char_ctrl.mascot_app.theme_manager
        label = tk.Label(
            self.tooltip_window, text=tooltip_text, bg=theme.get('tooltip_bg'), fg=theme.get('tooltip_text'), 
            relief="solid", borderwidth=app.border_width_normal, 
            font=app.font_small, justify='left'
        )
        label.pack()

        self.tooltip_window.update_idletasks()
        tooltip_width = self.tooltip_window.winfo_width()
        
        x_offset = app.padding_large
        y_offset = app.padding_normal

        base_x = self.heart_window.winfo_x()
        base_y = self.heart_window.winfo_y()
        mouse_x_in_heart = event.x
        mouse_y_in_heart = event.y

        if self.is_on_left_side:
            x = base_x + mouse_x_in_heart + x_offset
        else:
            x = base_x + mouse_x_in_heart - tooltip_width - x_offset

        y = base_y + mouse_y_in_heart + y_offset

        self.tooltip_window.geometry(f"+{x}+{y}")
        
    def hide_favorability_tooltip(self, event):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

    def destroy(self):
        """メインウィンドウが破棄されるときに、関連ウィンドウも一緒に破棄する"""
        if self.emotion_handler:
            self.emotion_handler.destroy()
        if self.name_window: self.name_window.destroy() 
        if self.heart_window: self.heart_window.destroy()
        if self.overlay_window: self.overlay_window.destroy()
        if self.alpha_overlay: self.alpha_overlay.destroy()
        if self.heart_alpha_overlay: self.heart_alpha_overlay.destroy()
        super().destroy()

    def reload_theme(self):
        """
        このUIグループを構成する全ウィジェットのテーマカラーを再適用します。
        """
        theme = self.char_ctrl.mascot_app.theme_manager
        
        border_color = theme.get('bg_accent')
        self.io_container_frame.config(
            bg=theme.get('bg_main'),
            highlightbackground=border_color,
            highlightcolor=border_color,
        )
        
        self.name_label.config(
            bg=theme.get('nameplate_bg'),
            fg=theme.get('nameplate_text'),
            highlightbackground=theme.get('nameplate_bg'),
        )
        
        if self.tooltip_window:
            self.hide_favorability_tooltip(None)
            
        self.output_box.reload_theme(theme)
        self.input_box.reload_theme(theme)
        self.emotion_handler.reload_theme()

    def on_character_drop(self, event):
        """キャラクターUIにファイルがドロップされたときの処理"""
        file_data = event.data
        paths = re.findall(r'\{[^{}]+\}|\S+', file_data)
        if not paths:
            return
        filepath = paths[0].strip('{}')
        if not filepath.lower().endswith('.zip'):
            print(f"無視されたドロップファイル (非ZIP): {filepath}")
            return
        self.char_ctrl.mascot_app.install_character_from_zip(filepath)

    def show_exit_button(self, exit_callback):
        """
        アプリケーション終了時に、音声OFFの場合に表示する終了ボタンを設定・表示します。
        """
        self.input_box.entry.pack_forget()
        self.input_box.send_button.pack_forget()
        
        self.event_proceed_button.config(
            text="終了",
            command=exit_callback,
            state="normal"
        )
        self.event_proceed_button.pack(side="right", padx=self.char_ctrl.mascot_app.padding_small, pady=self.char_ctrl.mascot_app.padding_small)

    def reload_assets(self):
        """
        このUIが保持している画像キャッシュ（ハートなど）をクリアします。
        """
        print(f"[{self.char_ctrl.name}] のUIアセットキャッシュをクリアします。")
        self.tk_heart_images.clear()
        self.alpha_heart_images.clear()
        self.tk_still_images.clear()
