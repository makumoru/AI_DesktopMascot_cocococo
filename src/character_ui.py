# src/character_ui.py

import tkinter as tk
from configparser import ConfigParser
from typing import TYPE_CHECKING

# --- 自作モジュールのインポート ---
from src.emotion_handler import EmotionHandler
from src.input_box import InputBox
from src.output_box import OutputBox

# 循環参照を避けるための型チェック用インポート
if TYPE_CHECKING:
    from src.character_controller import CharacterController

class CharacterUIGroup(tk.Toplevel):
    """
    キャラクター1体分のUI要素（画像、セリフ表示欄、入力欄）を管理するToplevelウィンドウクラス。
    各キャラクターはこのクラスのインスタンスを1つ持ちます。
    """
    def __init__(self, main_root: tk.Tk, character_controller: 'CharacterController', config: ConfigParser, char_config: ConfigParser):
        """
        CharacterUIGroupを初期化し、UIを構築します。

        Args:
            main_root (tk.Tk): アプリケーションのルートウィンドウ。
            character_controller (CharacterController): このUIを所有するキャラクターのコントローラー。
            config (ConfigParser): アプリケーション全体の設定情報。
            char_config (ConfigParser): このキャラクター固有の設定情報。
        """
        super().__init__(main_root)
        self.char_ctrl = character_controller
        
        transparent_color = self.char_ctrl.transparent_color
        
        # --- ウィンドウの初期設定 ---
        self.overrideredirect(True) # タイトルバーや境界線を非表示にする
        self.wm_attributes("-transparentcolor", transparent_color) # 指定色を透明に描画する
        self.configure(bg=transparent_color) # 背景色を透明色に設定
        
        window_width = self.char_ctrl.mascot_app.window_width
        
        # --- UIコンポーネントの生成 ---
        self.emotion_handler = EmotionHandler(
            self, config, char_config, self.char_ctrl, window_width,
            self.char_ctrl.mascot_app.transparency_tolerance,
            self.char_ctrl.edge_color,
            self.char_ctrl.is_left_side
        )
        self.output_box = OutputBox(self, window_width)
        self.input_box = InputBox(self, self.handle_send_message)

        # --- UIコンポーネントの配置 ---
        self.input_box.frame.pack(side="bottom", fill="x", expand=False, padx=0, pady=0)
        self.output_box.frame.pack(side="bottom", fill="x", expand=False, padx=0, pady=0)
        self.emotion_handler.image_label.pack(side="bottom", anchor="s", pady=0, padx=0)
        
        # --- イベントのバインド ---
        self.bind('<Button-3>', self.char_ctrl.mascot_app.show_context_menu)
        
        # 起動直後は画面外に配置し、画像ロード後に正しい位置へ移動させる
        self.geometry("+9999+9999")

    def handle_send_message(self, user_input):
        """入力ボックスで送信が押されたときの処理。CharacterControllerに処理を委譲します。"""
        if not user_input.strip(): return # 空の入力は無視
        self.char_ctrl.handle_user_input(user_input)
        self.input_box.clear_text()

    def update_geometry(self, is_initial=False):
        """
        ウィンドウのサイズとY座標を内容に合わせて再計算し、更新します。
        画像やウィジェットのサイズが変更された後に呼び出します。
        """
        self.update_idletasks() # ウィジェットのサイズが確定するのを待つ

        window_width = self.char_ctrl.mascot_app.window_width
        height = self.winfo_reqheight()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # is_initialがTrueの場合（起動時）はX座標を計算。
        # それ以外（衣装変更時など）は現在のX座標を維持する。
        if is_initial:
            x_pos = 0 if self.char_ctrl.is_left_side else screen_width - window_width
        else:
            try:
                # ジオメトリ文字列 'WxH+X+Y' からX座標をパース
                x_pos = self.winfo_x()
            except tk.TclError:
                # ウィンドウが非表示などで座標取得に失敗した場合のフォールバック
                x_pos = 0 if self.char_ctrl.is_left_side else screen_width - window_width

        # Y座標は常に画面下部を基準に再計算する
        y_pos = screen_height - height - 40
        
        new_geometry = f"{window_width}x{height}+{x_pos}+{y_pos}"
        # 現在のジオメトリと異なるときだけ更新
        if self.geometry() != new_geometry:
            self.geometry(new_geometry)