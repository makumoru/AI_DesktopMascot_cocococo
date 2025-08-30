# src/log_viewer.py

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

# 循環参照を避けるための型チェック用インポート
if TYPE_CHECKING:
    from src.desktop_mascot import DesktopMascot
    from src.character_controller import CharacterController

class ConversationLogViewer(tk.Toplevel):
    """
    指定されたキャラクターの会話ログを閲覧するためのウィンドウ。
    """
    def __init__(self, parent, app: 'DesktopMascot', character_controller: 'CharacterController'):
        """
        ConversationLogViewerを初期化します。

        Args:
            parent (tk.Widget): 親ウィジェット。
            app (DesktopMascot): アプリケーションのメインインスタンス。
            character_controller (CharacterController): ログを表示する対象のキャラクター。
        """
        super().__init__(parent)
        self.app = app
        self.character_controller = character_controller
        self.theme = self.app.theme_manager

        # --- ウィンドウ設定 ---
        self.title(f"{self.character_controller.name} の会話ログ")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        win_width = int(screen_width * 0.3)
        win_height = int(screen_height * 0.6)
        # 親ウィンドウの中央に表示
        x_pos = parent.winfo_x() + (parent.winfo_width() // 2) - (win_width // 2)
        y_pos = parent.winfo_y() + (parent.winfo_height() // 2) - (win_height // 2)
        self.geometry(f"{win_width}x{win_height}+{x_pos}+{y_pos}")

        self.configure(bg=self.theme.get('bg_main'))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- UI要素の作成 ---
        main_frame = ttk.Frame(self, padding=self.app.padding_normal)
        main_frame.pack(expand=True, fill="both")
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)
        
        # テキスト表示エリア
        self.log_text = tk.Text(
            main_frame,
            wrap="word",
            font=self.app.font_normal,
            bg=self.theme.get('output_bg'),
            fg=self.theme.get('output_text'),
            padx=self.app.padding_normal,
            pady=self.app.padding_normal,
            relief="solid",
            bd=self.app.border_width_normal,
            highlightthickness=0,
            spacing1=self.app.padding_small, # 各行の上のスペース
            spacing3=self.app.padding_small, # 各段落の後のスペース
        )
        
        # スクロールバー
        self.scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.config(yscrollcommand=self.scrollbar.set)

        # 配置
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        # ログを読み込んで表示
        self.update_log_display()

    def update_log_display(self):
        """
        キャラクターのログマネージャーからログを取得し、Textウィジェットの内容を更新します。
        リアルタイム更新にも対応します。
        """
        # ユーザーがスクロール中かどうかを判定
        # (一番下までスクロールされている状態か、そうでないか)
        is_scrolled_to_bottom = self.scrollbar.get()[1] == 1.0

        # Textウィジェットを書き込み可能にする
        self.log_text.config(state="normal")
        # 既存のテキストをすべて削除
        self.log_text.delete("1.0", tk.END)

        log_entries = self.character_controller.log_manager.get_formatted_log()
        
        # 見やすさのため、エントリ間に2つの改行を入れる
        full_log_text = "\n\n".join(log_entries)
        
        self.log_text.insert(tk.END, full_log_text)
        
        # ユーザーが自分でスクロールしていない場合のみ、自動で一番下にスクロール
        if is_scrolled_to_bottom:
            self.log_text.see(tk.END)
        
        # ユーザーが編集できないように、再度読み取り専用にする
        self.log_text.config(state="disabled")

    def on_close(self):
        """
        ウィンドウが閉じられるときに、メインアプリの参照リストから自身を削除します。
        """
        char_id = self.character_controller.original_id
        if char_id in self.app.log_viewer_windows:
            del self.app.log_viewer_windows[char_id]
        self.destroy()

    def reload_theme(self):
        """
        テーマが変更されたときにUIの色を再適用します。
        """
        self.theme = self.app.theme_manager
        self.configure(bg=self.theme.get('bg_main'))
        self.log_text.config(
            bg=self.theme.get('output_bg'),
            fg=self.theme.get('output_text')
        )