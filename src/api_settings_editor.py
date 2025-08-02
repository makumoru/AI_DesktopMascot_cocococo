# src/api_settings_editor.py

import tkinter as tk
from tkinter import ttk, messagebox, font
from configparser import ConfigParser
import os
import webbrowser

from src.character_controller import CharacterController

class ApiSettingsEditorWindow(tk.Toplevel):
    """APIキーとモデル名、RPDを設定するためのGUIウィンドウ"""

    CONFIG_PATH = 'config.ini'

    def __init__(self, character_controller: 'CharacterController', parent, app_controller):
        """
        ウィンドウを初期化し、UI要素を配置します。
        """
        super().__init__(parent)
        self.app = app_controller

        # --- ウィンドウ設定 ---
        self.transient(parent)
        self.grab_set()
        self.title("API接続設定")
        self.resizable(False, False) # このウィンドウはサイズ固定で運用

        theme = character_controller.mascot_app.theme_manager
        self.configure(bg=theme.get('bg_main'))

        style = ttk.Style(self)
        style.configure("TFrame", background=theme.get('bg_main'))
        # 各ウィジェットのフォントを基準単位で設定
        style.configure("TLabel", 
                        background=theme.get('bg_main'), 
                        foreground=theme.get('bg_text'), # 文字色を追加
                        font=self.app.font_normal)
        style.configure("TButton", 
        #                background=theme.get('bg_main'), 
        #                foreground=theme.get('bg_text'), # 文字色を追加
                        font=self.app.font_normal)
        style.configure("TSeparator", background=theme.get('bg_main'))
        # リンク用のスタイル
        style.configure("Link.TLabel", 
                        foreground=theme.get('link_text'), # テーマからリンク色を取得
                        background=theme.get('bg_main')) 

        # --- Entryウィジェット用のスタイルを追加 ---
        #style.configure("Custom.TEntry", 
                        #background=theme.get('input_bg'),
                        #fieldbackground=theme.get('input_bg'),
                        #foreground=theme.get('input_text'),
                        #insertcolor=theme.get('input_text'))
        style.map("Custom.TEntry",
                  bordercolor=[('focus', theme.get('border_focus'))])

        # メインフレームのパディングを基準単位で設定
        main_frame = ttk.Frame(self, padding=self.app.padding_large)
        main_frame.pack(expand=True, fill="both")
        # グリッドレイアウトの伸縮設定
        main_frame.columnconfigure(3, weight=1)

        self.entries = {}
        
        # --- ヘルパー関数: 1行分のモデル設定UIを生成 ---
        def create_model_row(parent, row, key_prefix, display_text):
            # パディングを基準単位で設定
            padding_x = self.app.padding_small
            
            ttk.Label(parent, text="").grid(row=row, column=0, sticky="w", padx=(0, padding_x))
            ttk.Label(parent, text="").grid(row=row, column=1, sticky="w", padx=padding_x)
            ttk.Label(parent, text="モデル名:").grid(row=row, column=2, sticky="w", padx=(padding_x, 0))
            
            # Entryのフォントも基準単位で設定
            model_entry = ttk.Entry(parent, font=self.app.font_normal, style="Custom.TEntry")
            model_entry.grid(row=row, column=3, sticky="ew", padx=padding_x) # width指定をやめ、sticky="ew"で伸縮させる
            self.entries[("GEMINI", f"{key_prefix}_MODEL_NAME")] = model_entry

            ttk.Label(parent, text="RPD:").grid(row=row, column=4, sticky="w", padx=(padding_x, 0))
            # RPDのEntryは幅をフォントサイズに合わせて計算
            rpd_entry = ttk.Entry(parent, width=8, font=self.app.font_normal, style="Custom.TEntry")
            rpd_entry.grid(row=row, column=5, sticky="w", padx=padding_x)
            self.entries[("GEMINI", f"{key_prefix}_RPD")] = rpd_entry

        # === Geminiセクション ===
        ttk.Label(main_frame, text="Gemini", font=self.app.font_title).pack(anchor="w")
        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=self.app.padding_small)
        gemini_frame = ttk.Frame(main_frame)
        gemini_frame.pack(fill='x', pady=(0, self.app.padding_normal))
        gemini_frame.columnconfigure(2, weight=1) # 2列目を伸縮させる
        
        padding_y = self.app.padding_small
        padding_x = self.app.padding_small

        # Gemini APIキー
        ttk.Label(gemini_frame, text="Gemini APIキー:").grid(row=0, column=0, sticky="w", pady=padding_y)
        gemini_api_entry = ttk.Entry(gemini_frame, font=self.app.font_normal, style="Custom.TEntry")
        gemini_api_entry.grid(row=0, column=1, columnspan=5, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("GEMINI", "GEMINI_API_KEY")] = gemini_api_entry
        
        # 各モデルの行を生成
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
        ttk.Label(main_frame, text="Gemma", font=self.app.font_title).pack(anchor="w", pady=(self.app.padding_normal, 0))
        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=self.app.padding_small)
        gemma_frame = ttk.Frame(main_frame)
        gemma_frame.pack(fill='x')
        gemma_frame.columnconfigure(1, weight=1)

        # Gemma APIキー
        ttk.Label(gemma_frame, text="Gemma APIキー:").grid(row=0, column=0, sticky="w", pady=padding_y)
        gemma_api_entry = ttk.Entry(gemma_frame, font=self.app.font_normal, style="Custom.TEntry")
        gemma_api_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("GEMMA", "GEMMA_API_KEY")] = gemma_api_entry
                      
        # Gemma モデル名
        ttk.Label(gemma_frame, text="Gemma モデル名:").grid(row=1, column=0, sticky="w", pady=padding_y)
        gemma_model_entry = ttk.Entry(gemma_frame, font=self.app.font_normal, style="Custom.TEntry")
        gemma_model_entry.grid(row=1, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("GEMMA", "GEMMA_MODEL_NAME")] = gemma_model_entry

        # VOICEVOXセクション
        ttk.Label(main_frame, text="VOICEVOX", font=self.app.font_title).pack(anchor="w", pady=(self.app.padding_normal, 0))
        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=self.app.padding_small)
        voicevox_frame = ttk.Frame(main_frame)
        voicevox_frame.pack(fill='x', pady=(0, self.app.padding_normal))
        voicevox_frame.columnconfigure(1, weight=1)

        # VOICEVOX exe_path
        ttk.Label(voicevox_frame, text="run.exeのパス:").grid(row=0, column=0, sticky="w", pady=padding_y)
        voicevox_exe_entry = ttk.Entry(voicevox_frame, font=self.app.font_normal, style="Custom.TEntry")
        voicevox_exe_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("VOICEVOX", "exe_path")] = voicevox_exe_entry
                      
        # VOICEVOX api_url
        ttk.Label(voicevox_frame, text="APIのURL:").grid(row=1, column=0, sticky="w", pady=padding_y)
        voicevox_url_entry = ttk.Entry(voicevox_frame, font=self.app.font_normal, style="Custom.TEntry")
        voicevox_url_entry.grid(row=1, column=1, columnspan=4, sticky="ew", padx=padding_x, pady=padding_y)
        self.entries[("VOICEVOX", "api_url")] = voicevox_url_entry

        # === フッター部分 ===
        link_frame = ttk.Frame(main_frame)
        link_frame.pack(pady=(self.app.padding_large, self.app.padding_small))

        def create_link(parent, text, url):
            link_font = font.Font(font=self.app.font_small) # 基準フォントから生成
            link_font.configure(underline=True)
            label = ttk.Label(parent, text=text, font=link_font, style="Link.TLabel", cursor="hand2")
            label.pack(side="top", pady=self.app.padding_small) 
            label.bind("<Button-1>", lambda event: webbrowser.open_new_tab(url))

        create_link(link_frame, "Google AI Studio (APIキー取得/モデル名確認)", "https://aistudio.google.com/")
        create_link(link_frame, "レート制限の公式ドキュメント (Google)", "https://ai.google.dev/gemini-api/docs/rate-limits?hl=ja")
        create_link(link_frame, "VOICEVOX (公式サイト/ダウンロード)", "https://voicevox.hiroshiba.jp/")

        info_label = ttk.Label(
            main_frame,
            text="注意: 「保存して適用」を押すと設定は即座に反映されます。",
            font=self.app.font_small,
            foreground=theme.get('info_text') # テーマから情報テキスト色を取得
        )
        info_label.pack(pady=self.app.padding_small)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(self.app.padding_small, 0))
        
        button_padding = self.app.padding_normal
        ttk.Button(button_frame, text="保存して適用", command=self._save_settings).pack(side="left", padx=button_padding)
        ttk.Button(button_frame, text="キャンセル", command=self.destroy).pack(side="left", padx=button_padding)

        # ウィンドウが表示される前に、入力欄に値をロード
        self._load_current_settings()
        
        # ウィンドウのサイズを内容に合わせて調整
        self.update_idletasks()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")
        
    def _load_current_settings(self):
        """現在のconfig.iniから値を読み込み、入力欄に表示します。"""
        if not os.path.exists(self.CONFIG_PATH):
            messagebox.showwarning("警告", "設定ファイルが見つかりません。", parent=self)
            return

        config = ConfigParser()
        config.read(self.CONFIG_PATH, encoding='utf-8-sig')

        for (section, key), entry in self.entries.items():
            entry.insert(0, config.get(section, key, fallback=""))

    def _save_settings(self):
        """入力された値でconfig.iniを更新し、アプリを再起動します。"""
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
                        new_value = self.entries[(current_section, key_in_line)].get()
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
        
        style = ttk.Style(self)
        style.configure("TFrame", background=theme.get('bg_main'))
        style.configure("TLabel", 
                        background=theme.get('bg_main'), 
                        foreground=theme.get('bg_text'))
        #style.configure("TButton", 
        #                background=theme.get('bg_main'), 
        #                foreground=theme.get('bg_text'))
        style.configure("TSeparator", background=theme.get('bg_main'))
        style.configure("Link.TLabel", 
                        foreground=theme.get('link_text'), 
                        background=theme.get('bg_main')) 
        #style.configure("Custom.TEntry", 
        #                background=theme.get('input_bg'),
        #                fieldbackground=theme.get('input_bg'),
        #                foreground=theme.get('input_text'),
        #                insertcolor=theme.get('input_text'))
        style.map("Custom.TEntry",
                  bordercolor=[('focus', theme.get('border_focus'))])

        # 特定のウィジェットを更新
        self.info_label.configure(foreground=theme.get('info_text'))