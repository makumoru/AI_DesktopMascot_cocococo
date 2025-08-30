# src/api_settings_editor.py

import tkinter as tk
from tkinter import ttk, messagebox, font
from configparser import ConfigParser
import os
import webbrowser
import threading

from src.character_controller import CharacterController
from src.gemini_api_handler import GeminiAPIHandler

class ApiSettingsEditorWindow(tk.Toplevel):
    """APIキーとモデル名、RPDを設定するためのGUIウィンドウ"""

    CONFIG_PATH = 'config.ini'

    def __init__(self, character_controller: 'CharacterController', parent, app_controller):
        """
        ウィンドウを初期化し、UI要素を配置します。
        """
        super().__init__(parent)
        self.app = app_controller
        self.available_gemini_models = []
        self.available_gemma_models = []

        # --- ウィンドウ設定 ---
        self.transient(parent)
        self.grab_set()
        self.title("API接続設定")
        # ウィンドウをリサイズ可能に変更
        self.resizable(True, True)

        theme = character_controller.mascot_app.theme_manager
        self.configure(bg=theme.get('bg_main'))
        
        # --- ウィンドウサイズの初期設定 ---
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        # 縦長のコンテンツに合わせて初期サイズを調整
        win_width = int(screen_width * 0.45)
        win_height = int(screen_height * 0.8)
        self.geometry(f"{win_width}x{win_height}")
        # 最小サイズを設定してウィンドウが小さくなりすぎるのを防ぐ
        self.minsize(int(screen_width * 0.35), int(screen_height * 0.6))

        style = ttk.Style(self)
        style.configure("TFrame", background=theme.get('bg_main'))
        style.configure("TLabel", 
                        background=theme.get('bg_main'), 
                        foreground=theme.get('bg_text'),
                        font=self.app.font_normal)
        style.configure("TButton", font=self.app.font_normal)
        style.configure("TSeparator", background=theme.get('bg_main'))
        style.configure("Link.TLabel", 
                        foreground=theme.get('link_text'),
                        background=theme.get('bg_main')) 

        style.map("Custom.TEntry",
                  bordercolor=[('focus', theme.get('border_focus'))])
        
        # Comboboxのスタイルを定義
        # 通常時のスタイル
        style.configure("Custom.TCombobox", 
                        foreground=theme.get('input_text'))
        style.map("Custom.TCombobox",
                  bordercolor=[('focus', theme.get('border_focus'))])
        # エラー時のスタイル
        style.configure("Error.TCombobox", foreground='red')
        style.map("Error.TCombobox",
                  bordercolor=[('focus', theme.get('border_focus'))])

        # --- スクロール可能なフレームを作成 ---
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(container, bg=theme.get('bg_main'), highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        # 実際にウィジェットを配置するフレーム
        scrollable_frame = ttk.Frame(self.canvas, padding=self.app.padding_large)
        self.canvas_frame_id = self.canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        # --- コンテンツを scrollable_frame に配置 ---
        scrollable_frame.columnconfigure(3, weight=1)

        self.entries = {}
        
        def create_model_row(parent, row, key_prefix, display_text):
            padding_x = self.app.padding_small
            
            ttk.Label(parent, text="").grid(row=row, column=0, sticky="w", padx=(0, padding_x))
            ttk.Label(parent, text="").grid(row=row, column=1, sticky="w", padx=padding_x)
            ttk.Label(parent, text="モデル名:").grid(row=row, column=2, sticky="w", padx=(padding_x, 0))
            
            model_combobox = ttk.Combobox(parent, font=self.app.font_normal, style="Custom.TCombobox")
            model_combobox.grid(row=row, column=3, sticky="ew", padx=padding_x)
            # 値が変更されたときに検証メソッドを呼び出すようにバインド
            model_combobox.bind("<<ComboboxSelected>>", self._validate_model_selection)
            self.entries[("GEMINI", f"{key_prefix}_MODEL_NAME")] = model_combobox

            ttk.Label(parent, text="RPD:").grid(row=row, column=4, sticky="w", padx=(padding_x, 0))
            rpd_entry = ttk.Entry(parent, width=8, font=self.app.font_normal, style="Custom.TEntry")
            rpd_entry.grid(row=row, column=5, sticky="w", padx=padding_x)
            self.entries[("GEMINI", f"{key_prefix}_RPD")] = rpd_entry

        # === Geminiセクション ===
        ttk.Label(scrollable_frame, text="Gemini", font=self.app.font_title).pack(anchor="w")
        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=self.app.padding_small)
        gemini_frame = ttk.Frame(scrollable_frame)
        gemini_frame.pack(fill='x', pady=(0, self.app.padding_normal))
        gemini_frame.columnconfigure(2, weight=1)
        
        padding_y = self.app.padding_small
        padding_x = self.app.padding_small

        ttk.Label(gemini_frame, text="Gemini APIキー:").grid(row=0, column=0, sticky="w", pady=padding_y)
        gemini_api_entry = ttk.Entry(gemini_frame, font=self.app.font_normal, style="Custom.TEntry")
        gemini_api_entry.grid(row=0, column=1, columnspan=5, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("GEMINI", "GEMINI_API_KEY")] = gemini_api_entry
        
        ttk.Label(gemini_frame, text="現行モデル (基本的な応答や自発発言、スケジュール通知に使用)").grid(row=1, column=0, columnspan = 6, sticky="w")
        ttk.Label(gemini_frame, text="Proモデル (思考モードで使用)").grid(row=2, column=1, columnspan = 5, sticky="w")
        create_model_row(gemini_frame, 3, "PRO", "")
        ttk.Label(gemini_frame, text="Flashモデル (基本)").grid(row=4, column=1, columnspan = 5, sticky="w")
        create_model_row(gemini_frame, 5, "FLASH", "")
        ttk.Label(gemini_frame, text="Flash-Liteモデル (Flashモデルの予備)").grid(row=6, column=1, columnspan = 5, sticky="w")
        create_model_row(gemini_frame, 7, "FLASH_LITE", "")
        
        ttk.Label(gemini_frame, text="旧モデル (タッチ反応に使用)").grid(row=8, column=0, columnspan = 6, sticky="w")
        ttk.Label(gemini_frame, text="Flashモデル (基本)").grid(row=9, column=1, columnspan = 5, sticky="w")
        create_model_row(gemini_frame, 10, "FLASH_2", "")
        ttk.Label(gemini_frame, text="Flash-Liteモデル (Flashモデルの予備)").grid(row=11, column=1, columnspan = 5, sticky="w")
        create_model_row(gemini_frame, 12, "FLASH_LITE_2", "")

        # === Gemmaセクション ===
        ttk.Label(scrollable_frame, text="Gemma", font=self.app.font_title).pack(anchor="w", pady=(self.app.padding_normal, 0))
        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=self.app.padding_small)
        gemma_frame = ttk.Frame(scrollable_frame)
        gemma_frame.pack(fill='x')
        gemma_frame.columnconfigure(1, weight=1)

        ttk.Label(gemma_frame, text="Gemma APIキー:").grid(row=0, column=0, sticky="w", pady=padding_y)
        gemma_api_entry = ttk.Entry(gemma_frame, font=self.app.font_normal, style="Custom.TEntry")
        gemma_api_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("GEMMA", "GEMMA_API_KEY")] = gemma_api_entry
                      
        ttk.Label(gemma_frame, text="Gemma モデル名:").grid(row=1, column=0, sticky="w", pady=padding_y)
        gemma_model_combobox = ttk.Combobox(gemma_frame, font=self.app.font_normal, style="Custom.TCombobox")
        gemma_model_combobox.grid(row=1, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        # Gemmaも同様にバインド
        gemma_model_combobox.bind("<<ComboboxSelected>>", self._validate_model_selection)
        self.entries[("GEMMA", "GEMMA_MODEL_NAME")] = gemma_model_combobox

        # VOICEVOXセクション
        ttk.Label(scrollable_frame, text="VOICEVOX", font=self.app.font_title).pack(anchor="w", pady=(self.app.padding_normal, 0))
        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=self.app.padding_small)
        voicevox_frame = ttk.Frame(scrollable_frame)
        voicevox_frame.pack(fill='x', pady=(0, 0)) # MODIFIED: 次のセクションとの間隔をなくす
        voicevox_frame.columnconfigure(1, weight=1)

        ttk.Label(voicevox_frame, text="run.exeのパス:").grid(row=0, column=0, sticky="w", pady=padding_y)
        voicevox_exe_entry = ttk.Entry(voicevox_frame, font=self.app.font_normal, style="Custom.TEntry")
        voicevox_exe_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("VOICEVOX", "exe_path")] = voicevox_exe_entry
                      
        ttk.Label(voicevox_frame, text="APIのURL:").grid(row=1, column=0, sticky="w", pady=padding_y)
        voicevox_url_entry = ttk.Entry(voicevox_frame, font=self.app.font_normal, style="Custom.TEntry")
        voicevox_url_entry.grid(row=1, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("VOICEVOX", "api_url")] = voicevox_url_entry

        # AIVIS_SPEECHセクション - ADDED
        ttk.Label(scrollable_frame, text="AivisSpeech", font=self.app.font_title).pack(anchor="w", pady=(self.app.padding_normal, 0))
        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=self.app.padding_small)
        aivis_frame = ttk.Frame(scrollable_frame)
        aivis_frame.pack(fill='x', pady=(0, self.app.padding_normal))
        aivis_frame.columnconfigure(1, weight=1)

        ttk.Label(aivis_frame, text="run.exeのパス:").grid(row=0, column=0, sticky="w", pady=padding_y)
        aivis_exe_entry = ttk.Entry(aivis_frame, font=self.app.font_normal, style="Custom.TEntry")
        aivis_exe_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("AIVIS_SPEECH", "exe_path")] = aivis_exe_entry
                      
        ttk.Label(aivis_frame, text="APIのURL:").grid(row=1, column=0, sticky="w", pady=padding_y)
        aivis_url_entry = ttk.Entry(aivis_frame, font=self.app.font_normal, style="Custom.TEntry")
        aivis_url_entry.grid(row=1, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("AIVIS_SPEECH", "api_url")] = aivis_url_entry

        # === フッター部分 ===
        link_frame = ttk.Frame(scrollable_frame)
        link_frame.pack(pady=(self.app.padding_large, self.app.padding_small))

        def create_link(parent, text, url):
            link_font = font.Font(font=self.app.font_small)
            link_font.configure(underline=True)
            label = ttk.Label(parent, text=text, font=link_font, style="Link.TLabel", cursor="hand2")
            label.pack(side="top", pady=self.app.padding_small) 
            label.bind("<Button-1>", lambda event: webbrowser.open_new_tab(url))

        create_link(link_frame, "Google AI Studio (APIキー取得/モデル名確認)", "https://aistudio.google.com/")
        create_link(link_frame, "レート制限の公式ドキュメント (Google)", "https://ai.google.dev/gemini-api/docs/rate-limits?hl=ja")
        create_link(link_frame, "VOICEVOX (公式サイト/ダウンロード)", "https://voicevox.hiroshiba.jp/")
        create_link(link_frame, "AivisSpeech (公式サイト/ダウンロード)", "https://aivis-project.com/") # ADDED

        # クレジット表記
        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=self.app.padding_small)
        credit_text = "This application is powered by Google Gemini API, VOICEVOX, and AivisSpeech."
        ttk.Label(
            scrollable_frame,
            text=credit_text,
            font=self.app.font_small,
            foreground=theme.get('info_text'),
            justify='center'
        ).pack(pady=self.app.padding_small)
        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=self.app.padding_small)

        self.info_label = ttk.Label(
            scrollable_frame,
            text="注意: 「保存して適用」を押すと設定は即座に反映されます。",
            font=self.app.font_small,
            foreground=theme.get('info_text')
        )
        self.info_label.pack(pady=self.app.padding_small)

        button_frame = ttk.Frame(scrollable_frame)
        button_frame.pack(pady=(self.app.padding_small, 0))
        
        button_padding = self.app.padding_normal
        ttk.Button(button_frame, text="保存して適用", command=self._save_settings).pack(side="left", padx=button_padding)
        # キャンセルボタンのコマンドをself.destroyに変更
        ttk.Button(button_frame, text="キャンセル", command=self.destroy).pack(side="left", padx=button_padding)

        # --- イベントのバインド ---
        scrollable_frame.bind("<Configure>", self.on_frame_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        # マウスホイールでのスクロールを有効にする
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.protocol("WM_DELETE_WINDOW", self.destroy)


        self._load_current_settings()
        self._populate_model_lists_async()

    def on_frame_configure(self, event=None):
        """スクロール対象フレームのサイズが変更されたら、Canvasのスクロール領域を更新"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_canvas_configure(self, event=None):
        """Canvas自体のサイズが変更されたら、内部のフレームの幅を追従させる"""
        self.canvas.itemconfig(self.canvas_frame_id, width=event.width)

    def _on_mousewheel(self, event):
        """マウスホイールでスクロールする"""
        # Windows/Linux/Mac間の差異を吸収
        if event.num == 5 or event.delta < 0:
            scroll_val = 1
        elif event.num == 4 or event.delta > 0:
            scroll_val = -1
        else:
            return
            
        self.canvas.yview_scroll(scroll_val, "units")

    def destroy(self):
        """ウィンドウ破棄時にマウスホイールのバインドを解除"""
        self.unbind_all("<MouseWheel>")
        super().destroy()

    def _populate_model_lists_async(self):
        """別スレッドでモデルリストの取得を開始します。"""
        for (section, key), widget in self.entries.items():
            if "MODEL_NAME" in key and isinstance(widget, ttk.Combobox):
                widget.config(state="disabled")

        thread = threading.Thread(target=self._fetch_models_worker, daemon=True)
        thread.start()

    def _fetch_models_worker(self):
        """ワーカースレッド: APIからモデルリストを取得します。"""
        config = ConfigParser()
        config.read(self.CONFIG_PATH, encoding='utf-8-sig')
        api_key = config.get('GEMINI', 'GEMINI_API_KEY', fallback=None)
        
        # resultの構造は {'status': '...', 'models': {...}}
        result = {'status': 'no_key', 'models': {}}
        if api_key:
            result = GeminiAPIHandler.list_available_models(api_key)
        
        # 成功した場合のみ、'models'キーの中身を渡す。失敗時は空の辞書を渡す。
        models_data = result.get('models', {}) if result.get('status') == 'success' else {}
        self.after(0, self._update_comboboxes, models_data)

    def _update_comboboxes(self, models):
        """UIスレッド: 取得したモデルリストでComboboxを更新し、初期値を検証します。"""
        # 取得したモデルリストをインスタンス変数に保存
        self.available_gemini_models = models.get('gemini', [])
        self.available_gemma_models = models.get('gemma', [])

        # --- 各役割ごとのおすすめモデルを選定 ---
        recommendations = {
            "PRO_MODEL_NAME": GeminiAPIHandler.recommend_pro_model(self.available_gemini_models),
            "FLASH_MODEL_NAME": GeminiAPIHandler.recommend_flash_model(self.available_gemini_models),
            "FLASH_LITE_MODEL_NAME": GeminiAPIHandler.recommend_flash_lite_model(self.available_gemini_models),
            "FLASH_2_MODEL_NAME": GeminiAPIHandler.recommend_legacy_flash_model(self.available_gemini_models),
            "FLASH_LITE_2_MODEL_NAME": GeminiAPIHandler.recommend_legacy_flash_lite_model(self.available_gemini_models),
            "GEMMA_MODEL_NAME": GeminiAPIHandler.recommend_gemma_model(self.available_gemma_models),
        }

        # --- 全てのモデルComboboxをループして更新と検証を行う ---
        for (section, key), widget in self.entries.items():
            if "MODEL_NAME" in key and isinstance(widget, ttk.Combobox):
                
                is_gemini = (section == "GEMINI")
                valid_list = self.available_gemini_models if is_gemini else self.available_gemma_models
                recommendation = recommendations.get(key)
                
                # 表示用のリストを作成 (推奨モデルに接尾辞を追加)
                display_list = []
                if valid_list:
                    for model_name in valid_list:
                        if model_name == recommendation:
                            display_list.append(f"{model_name} (推奨)")
                        else:
                            display_list.append(model_name)
                
                # Comboboxを更新
                widget.config(values=display_list)
                widget.config(state="readonly" if valid_list else "disabled")
                
                # 現在設定されている値を、推奨表示に合わせて更新
                current_value = widget.get()
                if current_value == recommendation:
                    widget.set(f"{current_value} (推奨)")

                # スタイルを検証
                self._check_and_style_widget(widget, valid_list)

    def _check_and_style_widget(self, widget, valid_list):
        """値から接尾辞を取り除いてから検証する"""
        current_value_display = widget.get()
        # 検証する前に "(推奨)" を削除
        value_to_check = current_value_display.removesuffix(" (推奨)")
        
        # 値が設定されていて、かつ有効リストにない場合
        if value_to_check and value_to_check not in valid_list:
            widget.config(style="Error.TCombobox")
        else:
            widget.config(style="Custom.TCombobox")

    def _validate_model_selection(self, event):
        """Comboboxの値が選択されたときに呼び出されるイベントハンドラ"""
        widget = event.widget
        # 選択された値は常に有効なはずなので、スタイルを通常に戻す
        widget.config(style="Custom.TCombobox")

    def _load_current_settings(self):
        """現在のconfig.iniから値を読み込み、入力欄に表示します。"""
        if not os.path.exists(self.CONFIG_PATH):
            messagebox.showwarning("警告", "設定ファイルが見つかりません。", parent=self)
            return

        config = ConfigParser()
        config.read(self.CONFIG_PATH, encoding='utf-8-sig')

        for (section, key), widget in self.entries.items():
            value = config.get(section, key, fallback="")
            if isinstance(widget, (ttk.Entry)):
                widget.delete(0, tk.END)
                widget.insert(0, value)
            elif isinstance(widget, ttk.Combobox):
                widget.set(value)

    def _save_settings(self):
        """保存時に "(推奨)" 接尾辞を削除する"""
        try:
            with open(self.CONFIG_PATH, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()

            new_lines = []
            current_section = ""
            for line in lines:
                stripped_line = line.strip()
                if stripped_line.startswith('[') and stripped_line.endswith(']'):
                    current_section = stripped_line[1:-1]
                    new_lines.append(line)
                    continue

                if '=' in stripped_line and not stripped_line.startswith((';', '#')):
                    key_in_line = stripped_line.split('=', 1)[0].strip()
                    if (current_section, key_in_line) in self.entries:
                        
                        raw_value = self.entries[(current_section, key_in_line)].get()
                        # 値から "(推奨)" を削除してから保存
                        new_value = raw_value.removesuffix(" (推奨)")
                        
                        indentation = line[:line.find(key_in_line)]
                        new_lines.append(f"{indentation}{key_in_line} = {new_value}\n")
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            
            with open(self.CONFIG_PATH, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            messagebox.showinfo("保存完了", "設定を保存し、反映しました。", parent=self)
            
            self.app.reload_config_and_services()
            
            self.destroy()

        except Exception as e:
            messagebox.showerror("保存エラー", f"設定の保存中にエラーが発生しました:\n{e}", parent=self)

    def reload_theme(self):
        """
        ウィンドウ全体のテーマカラーを再適用します。
        """
        theme = self.app.theme_manager
        self.configure(bg=theme.get('bg_main'))
        # Canvasの背景色もテーマに合わせる
        if hasattr(self, 'canvas'):
            self.canvas.configure(bg=theme.get('bg_main'))
        
        style = ttk.Style(self)
        style.configure("TFrame", background=theme.get('bg_main'))
        style.configure("TLabel", 
                        background=theme.get('bg_main'), 
                        foreground=theme.get('bg_text'))
        style.configure("TSeparator", background=theme.get('bg_main'))
        style.configure("Link.TLabel", 
                        foreground=theme.get('link_text'), 
                        background=theme.get('bg_main')) 
        
        # テーマ再読み込み時にもスタイルを再設定
        style.configure("Custom.TCombobox", foreground=theme.get('input_text'))
        style.map("Custom.TEntry",
                  bordercolor=[('focus', theme.get('border_focus'))])
        style.map("Custom.TCombobox",
                  bordercolor=[('focus', theme.get('border_focus'))])
        style.map("Error.TCombobox",
                  bordercolor=[('focus', theme.get('border_focus'))])

        self.info_label.configure(foreground=theme.get('info_text'))

        # テーマ再読み込み後に再度検証を実行してスタイルを再適用
        self._check_all_model_widgets()

    def _check_all_model_widgets(self):
        """すべてのモデルウィジェットの検証を一度に行うヘルパー"""
        for (section, key), widget in self.entries.items():
            if "MODEL_NAME" in key and isinstance(widget, ttk.Combobox):
                is_gemini = (section == "GEMINI")
                valid_list = self.available_gemini_models if is_gemini else self.available_gemma_models
                self._check_and_style_widget(widget, valid_list)