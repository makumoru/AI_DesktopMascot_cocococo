# src/character_ui.py

import tkinter as tk
from configparser import ConfigParser
from typing import TYPE_CHECKING
from PIL import Image, ImageTk
import os
from tkinter import font
from tkinterdnd2 import DND_FILES, TkinterDnD
import re

# --- 自作モジュールのインポート ---
from src.emotion_handler import EmotionHandler
from src.input_box import InputBox
from src.output_box import OutputBox
from src.input_history_manager import InputHistoryManager

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
    # クラス変数として名前欄の幅の制約を「スクリーン幅に対する比率」で定義
    MIN_NAME_WIDTH_RATIO = 0.08
    MAX_NAME_WIDTH_RATIO = 0.18
    CHARACTER_FRAME_OFFSET_RATIO = 0.01
    def __init__(self, character_controller: 'CharacterController', config: ConfigParser, char_config: 'ConfigParser', input_history_manager: InputHistoryManager):
        theme = character_controller.mascot_app.theme_manager
        super().__init__(character_controller.mascot_app.root)
        self.char_ctrl = character_controller
        app = self.char_ctrl.mascot_app # appインスタンスへのショートカット
        
        transparent_color = self.char_ctrl.transparent_color
        
        self.tk_heart_images = {}
        self.current_layout_side = None

        self.tk_still_images = {} # イベントスチル用の画像キャッシュ
        self.event_choice_buttons = [] # 選択肢ボタンの参照を保持

        self.tooltip_window = None

        self.overrideredirect(True) 
        self.wm_attributes("-transparentcolor", transparent_color) 
        self.configure(bg=transparent_color) 
        
        # 比率から実際のピクセル幅を計算してインスタンス変数に格納
        screen_width = self.winfo_screenwidth()
        self.min_name_width_px = int(screen_width * self.MIN_NAME_WIDTH_RATIO)
        self.max_name_width_px = int(screen_width * self.MAX_NAME_WIDTH_RATIO)
        self.character_frame_offset_px = int(screen_width * self.CHARACTER_FRAME_OFFSET_RATIO)
        # 設定から基本の幅を取得
        self.base_window_width = self.char_ctrl.mascot_app.window_width
        
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

        self.emotion_handler = EmotionHandler(
            self.character_display_frame, self,
            config, char_config, self.char_ctrl, self.base_window_width,
            self.char_ctrl.mascot_app.transparency_tolerance,
            self.char_ctrl.edge_color,
            self.char_ctrl.is_left_side
        )

        # 名札のボーダー幅を基準単位で指定
        name_label_border_width = app.border_width_normal * 2
        # フォントを基準単位で指定
        self.name_font = app.font_title
        self.name_font_obj = font.Font(font=self.name_font)

        self.name_label = tk.Label(
            self.character_display_frame, 
            text=self.char_ctrl.name,
            font=self.name_font, 
            bg=theme.get('nameplate_bg'),
            fg=theme.get('nameplate_text'),
            padx=0,
            pady=0,
            justify='center',
            highlightbackground=theme.get('nameplate_bg'),
            highlightthickness=name_label_border_width
        )

        # ハート用の独立したウィンドウを作成
        self.heart_window = tk.Toplevel(self)
        self.heart_window.overrideredirect(True)
        self.heart_window.wm_attributes("-transparentcolor", transparent_color)
        self.heart_window.configure(bg=transparent_color)
        self.heart_window.withdraw()
        
        self.heart_window_label = tk.Label(self.heart_window, bg=transparent_color)
        self.heart_window_label.pack()
        
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
        self.bind("<Button-1>", self.on_window_click)
        self.heart_window.bind("<Button-1>", self.on_window_click)
        self.name_label.bind("<Button-1>", self.on_window_click)
        self.output_box.text_widget.bind("<Button-1>", self.on_window_click)
        self.input_box.entry.bind("<Button-1>", self.on_window_click)

        # イベントのバインド
        self.character_display_frame.bind('<Button-3>', self.char_ctrl.mascot_app.show_context_menu)
        self.name_label.bind('<Button-3>', self.char_ctrl.mascot_app.show_context_menu)
        self.emotion_handler.image_label.bind('<Button-3>', self.char_ctrl.mascot_app.show_context_menu)
        self.heart_window_label.bind('<Button-3>', self.char_ctrl.mascot_app.show_context_menu)
        self.heart_window_label.bind('<Enter>', self.show_favorability_tooltip)
        self.heart_window_label.bind('<Leave>', self.hide_favorability_tooltip)

        self.geometry("+9999+9999")

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
        """このウィンドウまたはハートウィンドウがフォーカスを得たときに重なり順を修正する"""
        if self.heart_window.winfo_viewable():
            self.heart_window.lift(self)

    def finalize_initial_position(self):
        """起動シーケンスの最後に呼び出され、ウィンドウとハートの位置を最終確定させる"""
        self.update_geometry(is_initial=True)

    def on_window_click(self, event=None):
        """ウィンドウのいずれかの部分がクリックされたときに、ペアで前面に表示する"""
        if not self.char_ctrl.mascot_app.is_always_on_top.get():
            self.lift_with_heart()

    def lift_with_heart(self):
        """キャラクターとハートをペアで最前面に持ち上げ、重なり順を修正する"""
        super().lift()
        if self.heart_window.winfo_viewable():
            self.heart_window.lift(self)


    def move_with_heart(self, new_x, new_y):
        """キャラクターウィンドウとハートウィンドウを一緒に動かす"""
        self.geometry(f"+{new_x}+{new_y}")
        self._update_heart_window_position()

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
        
        # タスクバーの高さを考慮したオフセットを基準単位で計算
        taskbar_offset = int(screen_height * 0.04)
        y_pos = screen_height - height - taskbar_offset
        self.move_with_heart(x_pos, y_pos)

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
            try: widget.place_forget()
            except tk.TclError: pass
        
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
        # パディングを基準単位で指定
        padding = self.char_ctrl.mascot_app.padding_large
        name_label_width = max(self.min_name_width_px, min(actual_text_width + padding, self.max_name_width_px))

        self.update_idletasks()
        image_width = image_label.winfo_reqwidth()
        image_height = image_label.winfo_reqheight()
        name_label_height = name_label.winfo_reqheight()

        self.character_display_frame.config(width=image_width, height=image_height)

        image_label.place(x=0, y=0)

        name_label_y = image_height - name_label_height

        if side == 'left':
            name_label_x = image_width - name_label_width
        else: # 'right'
            name_label_x = 0
            
        name_label.place(x=name_label_x, y=name_label_y, width=name_label_width, height=name_label_height)
        
        self.update_geometry()

    def enter_event_mode(self):
        """イベント再生モードに移行する。"""
        # 通常の入力UIを隠し、「次へ」ボタンを表示する
        self.input_box.entry.pack_forget()
        self.input_box.send_button.pack_forget()
        self.event_proceed_button.pack(side="right", padx=self.char_ctrl.mascot_app.padding_small, pady=self.char_ctrl.mascot_app.padding_small)
        # 最初は「次へ」ボタンを無効化しておく
        self.event_proceed_button.config(state="disabled")

    def enter_event_wait_mode(self):
        """相方がイベント中の待機モードに移行する。"""
        # 入力UIを完全に無効化する
        self.input_box.entry.config(state="disabled")
        self.input_box.send_button.config(state="disabled")
        self.output_box.set_text("（...しずかに見守っている）")

    def exit_event_mode(self):
        """通常モードに復帰する。"""
        # 「次へ」ボタンと選択肢ボタンを隠す
        self.event_proceed_button.pack_forget()
        self._clear_choice_buttons()
        
        # 通常の入力UIを再表示・有効化する
        self.input_box.entry.pack(side="left", fill="x", expand=True, padx=self.char_ctrl.mascot_app.padding_small, pady=self.char_ctrl.mascot_app.padding_small)
        self.input_box.send_button.pack(side="right", padx=self.char_ctrl.mascot_app.padding_small, pady=self.char_ctrl.mascot_app.padding_small)
        self.input_box.entry.config(state="normal")
        self.input_box.send_button.config(state="normal")
        
        # 表情を通常に戻し、テキストをクリア
        self.emotion_handler.update_image("normal")
        self.output_box.set_text("...")

    def display_event_dialogue(self, text: str, emotion_jp: str, still_image_filename: str = None, transparent_color: str = None, edge_color: str = None):
        """イベントのセリフ/モノローグを表示する。"""
        self._clear_choice_buttons()
        self.event_proceed_button.config(state="disabled")
        self.output_box.set_text(text)

        if still_image_filename:
            # スチル画像を表示 (新しい引数を渡す)
            self._show_still_image(still_image_filename, transparent_color, edge_color)
        else:
            # 通常の表情を表示
            self.emotion_handler.update_image(emotion_jp)

    def display_event_choices(self, prompt: str, options: list):
        """イベントの選択肢をカスタムダイアログで表示する。"""
        self.output_box.set_text(prompt) # キャラクターの吹き出しにも問いかけを表示
        self.event_proceed_button.pack_forget()
        self._clear_choice_buttons() # 念のため古いボタンはクリア

        # 新しいChoiceDialogを生成して表示
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
        # --- キャッシュキーに色情報を含める ---
        cache_key = f"{filename}_{transparent_color}_{edge_color}"
        tk_image = self.tk_still_images.get(cache_key)

        if not tk_image:
            try:
                stills_dir = os.path.join(self.char_ctrl.character_dir, "stills")
                image_path = os.path.join(stills_dir, filename)
                
                # --- 色指定の上書きロジック ---
                # 指定があればそれを使う、なければキャラクターのデフォルト設定を使う
                trans_hex = transparent_color or self.char_ctrl.transparent_color
                edge_hex = edge_color or self.char_ctrl.edge_color

                trans_rgb = self.emotion_handler._hex_to_rgb(trans_hex)
                edge_rgb = self.emotion_handler._hex_to_rgb(edge_hex)

                # 処理をEmotionHandlerに集約するため、内部メソッドを呼び出す形に変更
                with Image.open(image_path) as img_pil:
                    # リサイズ処理
                    aspect_ratio = img_pil.height / img_pil.width
                    resized_img = img_pil.resize((self.emotion_handler.window_width, int(self.emotion_handler.window_width * aspect_ratio)), Image.Resampling.LANCZOS)
                    # 透明化処理
                    processed_img = self.emotion_handler._process_transparency(resized_img, trans_rgb, edge_rgb)
                    tk_image = ImageTk.PhotoImage(processed_img)

                if tk_image:
                    self.tk_still_images[cache_key] = tk_image
                else:
                    print(f"エラー: スチル画像 '{filename}' の読み込みに失敗しました。")
                    self.emotion_handler.update_image("troubled")
                    return
            except Exception as e:
                print(f"スチル画像の処理中にエラー: {e}")
                self.emotion_handler.update_image("troubled")
                return
        
        # EmotionHandlerの画像ラベルを直接更新
        self.emotion_handler.image_label.config(image=tk_image)
        # EmotionHandlerにスチル表示中であることを通知
        self.emotion_handler.is_showing_still = True

    def prepare_for_next_event_step(self):
        """選択肢ダイアログが閉じた後など、次のイベントステップに備えるためのUI準備を行う。"""
        # 古い選択肢ボタンが残っていればクリア
        self._clear_choice_buttons()
        # 「次へ」ボタンを再表示し、無効化しておく（セリフが表示されたら有効化される）
        self.event_proceed_button.pack(side="right", padx=self.char_ctrl.mascot_app.padding_small, pady=self.char_ctrl.mascot_app.padding_small)
        self.event_proceed_button.config(state="disabled")


    def handle_send_message(self, user_input):
        if not user_input.strip(): return
        if self.char_ctrl.mascot_app.is_event_running:
            return
        self.char_ctrl.handle_user_input(user_input)
        self.input_box.clear_text()

    def update_geometry(self, is_initial=False, force_x=None, force_y=None):
        self.update_idletasks()

        char_frame_width = self.character_display_frame.winfo_reqwidth()
        width = max(char_frame_width, self.base_window_width)
        height = self.winfo_reqheight()

        x_pos, y_pos = 0, 0

        if force_x is not None and force_y is not None:
            # 引数で座標が指定された場合（通常の発話時など）は、それを最優先で使う
            x_pos, y_pos = force_x, force_y
        elif is_initial:
            # アプリケーション起動時の初回配置
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            x_pos = 0 if self.char_ctrl.initial_position_side == 'left' else screen_width - width
            taskbar_offset = int(screen_height * 0.04)
            y_pos = screen_height - height - taskbar_offset
        else:
            # 上記以外の予期せぬケースでは、現在の位置を維持する
            try:
                x_pos, y_pos = self.winfo_x(), self.winfo_y()
            except tk.TclError:
                pass # ウィンドウが存在しない場合は何もしない

        new_geometry = f"{width}x{height}+{x_pos}+{y_pos}"
        if self.geometry() != new_geometry:
            self.geometry(new_geometry)

        self._update_heart_window_position()
        self.check_and_update_layout() # 位置確定後に必ずレイアウトを再チェック

    def update_info_display(self):
        # レイアウト変更でウィンドウがジャンプするのを防ぐため、処理前の座標を記憶する
        pre_x, pre_y = self.winfo_x(), self.winfo_y()

        # レイアウトとハートの更新処理
        self.check_and_update_layout(force_update=True)
        self._update_heart_label()

        # 記憶しておいた正しい座標を使って、ウィンドウの位置を再設定・確定させる
        self.update_geometry(force_x=pre_x, force_y=pre_y)

    def _update_heart_label(self):
        """ハート画像を読み込み、専用ウィンドウに表示する"""
        image_filename = self.char_ctrl.get_current_heart_image_filename()
        if not image_filename:
            self.heart_window.withdraw()
            return
            
        self.name_label.update_idletasks()
        name_label_height = self.name_label.winfo_reqheight()
        target_heart_height = name_label_height * 2
        cache_key = f"{image_filename}_{target_heart_height}"

        tk_image = self.tk_heart_images.get(cache_key)

        if not tk_image:
            char_path = os.path.join(self.char_ctrl.character_dir, 'hearts', image_filename)
            default_path = os.path.join('images', 'hearts', image_filename)
            path_to_load = char_path if os.path.exists(char_path) else default_path if os.path.exists(default_path) else None
            
            if path_to_load:
                try:
                    has_custom_heart_settings = bool(self.char_ctrl.favorability_hearts)
                    trans_color_hex = (self.char_ctrl.heart_transparent_color or self.char_ctrl.transparent_color) if has_custom_heart_settings else '#FF00FF'
                    edge_color_hex = (self.char_ctrl.heart_edge_color or self.char_ctrl.edge_color) if has_custom_heart_settings else '#000000'
                    
                    trans_color_rgb = self.emotion_handler._hex_to_rgb(trans_color_hex)
                    edge_color_rgb = self.emotion_handler._hex_to_rgb(edge_color_hex)
                    
                    with Image.open(path_to_load) as img_pil:
                        aspect_ratio = img_pil.width / img_pil.height
                        new_height = target_heart_height
                        new_width = int(new_height * aspect_ratio)
                        resized_img = img_pil.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        processed_img = self.emotion_handler._process_transparency(
                            resized_img, trans_color_rgb, edge_color_rgb
                        )
                        tk_image = ImageTk.PhotoImage(processed_img)
                        self.tk_heart_images[cache_key] = tk_image
                except Exception as e:
                    print(f"ハート画像の読み込みに失敗しました: {path_to_load}, {e}")
                    self.heart_window.withdraw()
                    return
            else:
                self.heart_window.withdraw()
                return

        self.heart_window_label.config(image=tk_image)
        self.heart_window.geometry(f"{tk_image.width()}x{tk_image.height()}")
        self._update_heart_window_position()
        self.heart_window.deiconify()

    def _update_heart_window_position(self):
        """画面の左右に応じてハートの吸着面を切り替える"""
        if not self.heart_window.winfo_viewable(): return
        self.update_idletasks()

        img_abs_x = self.emotion_handler.image_label.winfo_rootx()
        img_width = self.emotion_handler.image_label.winfo_width()
        name_abs_y = self.name_label.winfo_rooty()
        name_height = self.name_label.winfo_height()
        heart_win_width = self.heart_window.winfo_width()
        heart_win_height = self.heart_window.winfo_height()

        y_pos = (name_abs_y + name_height) - (heart_win_height/1.2)

        if self.winfo_x() + (self.winfo_width() / 2) < self.winfo_screenwidth() / 2:
            x_pos = img_abs_x
        else:
            img_right_edge_abs_x = img_abs_x + img_width
            x_pos = img_right_edge_abs_x - heart_win_width
            
        self.heart_window.geometry(f"+{int(x_pos)}+{int(y_pos)}")

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
        # オフセットを基準単位で指定
        x_offset = app.padding_large
        y_offset = app.padding_normal
        x = self.heart_window.winfo_x() + event.x + x_offset
        y = self.heart_window.winfo_y() + event.y + y_offset
        self.tooltip_window.geometry(f"+{x}+{y}")

    def hide_favorability_tooltip(self, event):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

    def destroy(self):
        """メインウィンドウが破棄されるときに、ハートウィンドウも一緒に破棄する"""
        if self.heart_window: self.heart_window.destroy()
        super().destroy()

    def reload_theme(self):
        """
        このUIグループを構成する全ウィジェットのテーマカラーを再適用します。
        """
        theme = self.char_ctrl.mascot_app.theme_manager
        
        # IOコンテナフレームの再設定
        border_color = theme.get('bg_accent')
        self.io_container_frame.config(
            bg=theme.get('bg_main'),
            highlightbackground=border_color,
            highlightcolor=border_color,
        )
        
        # 名札の再設定
        self.name_label.config(
            bg=theme.get('nameplate_bg'),
            fg=theme.get('nameplate_text'),
            highlightbackground=theme.get('nameplate_bg'),
        )
        
        # ツールチップが表示中なら一旦消す（再表示時に新しい色が適用される）
        if self.tooltip_window:
            self.hide_favorability_tooltip(None)
            
        # 構成コンポーネント（OutputBox, InputBox）にもテーマ更新を伝播
        self.output_box.reload_theme(theme)
        self.input_box.reload_theme(theme)
        # EmotionHandlerにもテーマ更新を伝播させる
        self.emotion_handler.reload_theme()

    def on_character_drop(self, event):
        """キャラクターUIにファイルがドロップされたときの処理"""
        # ドロップされたファイルパスの生データを取得
        file_data = event.data
        
        # 正規表現を使い、{...}で囲まれたパスか、スペースを含まないパスをリストとして抽出
        # これにより、スペースを含む単一のファイルパスが分割されるのを防ぐ
        paths = re.findall(r'\{[^{}]+\}|\S+', file_data)
        
        if not paths:
            # 念のため、パスが取得できなかった場合のガード処理
            return

        # 複数ドロップされた場合も、最初のファイルパスのみを処理対象とする
        # パスを囲む波括弧が残っている場合は取り除く
        filepath = paths[0].strip('{}')

        # ZIPファイルでなければ、何もせず処理を終える
        if not filepath.lower().endswith('.zip'):
            print(f"無視されたドロップファイル (非ZIP): {filepath}")
            return
        
        # DesktopMascotクラスのインストール用メソッドを呼び出す
        self.char_ctrl.mascot_app.install_character_from_zip(filepath)
