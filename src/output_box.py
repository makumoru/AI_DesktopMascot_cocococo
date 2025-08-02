# src/output_box.py

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

# 循環参照を避けるための型チェック用インポート
if TYPE_CHECKING:
    from src.character_controller import CharacterController

class OutputBox:
    """
    AIからの応答テキストを表示するためのUIコンポーネント。
    TkinterのTextウィジェットとScrollbarウィジェットを使い、スクロール可能な表示領域を提供します。
    """
    def __init__(self, root, app, character_controller: 'CharacterController'):
        """
        OutputBoxのインスタンスを初期化し、テキスト表示用のウィジェットを生成します。

        Args:
            root (tk.Tk or tk.Frame): このウィジェットを配置する親ウィジェット。
            app (DesktopMascot): アプリケーションのメインインスタンス。基準単位の取得に使用。
        """
        # 
        theme = character_controller.mascot_app.theme_manager
        self.frame = tk.Frame(root, bg=theme.get('bg_main'))
        self.frame.pack(side="top", fill="both", expand=True, pady=0, padx=0)

        # スクロールバーの作成
        self.scrollbar = ttk.Scrollbar(self.frame, orient="vertical")
        
        # Textウィジェットの作成
        self.text_widget = tk.Text(
            self.frame,
            font=app.font_normal,
            height=5,
            bg=theme.get('output_bg'),
            fg=theme.get('output_text'),
            padx=app.padding_normal,
            pady=app.padding_normal,
            wrap="word",
            relief="flat",
            bd=0,
            yscrollcommand=self.scrollbar.set 
        )

        # スクロールバーのコマンドをTextウィジェットのyview（垂直表示位置の制御）に接続
        self.scrollbar.config(command=self.text_widget.yview)

        # ウィジェットの配置
        self.scrollbar.pack(side="right", fill="y")
        self.text_widget.pack(side="left", fill="both", expand=True)

        # 初期テキストを設定
        self.set_text("システム起動中...")

    def set_text(self, text):
        """
        Textウィジェットに表示されているテキストを更新します。

        Args:
            text (str): 新しく表示するテキスト。
        """
        # Textウィジェットを書き込み可能にする
        self.text_widget.config(state="normal")
        # 既存のテキストをすべて削除
        self.text_widget.delete("1.0", tk.END)
        # 新しいテキストを挿入
        self.text_widget.insert(tk.END, text)
        # スクロール位置を一番上にリセット
        self.text_widget.see("1.0")
        # ユーザーが編集できないように、再度読み取り専用にする
        self.text_widget.config(state="disabled")

    def get_frame_height(self):
        """
        このコンポーネントのフレームの高さを取得する。ウィンドウ全体の高さ計算に使用。
        """
        # packされたウィジェットの要求サイズを更新
        self.frame.update_idletasks()
        return self.frame.winfo_reqheight()
    
    def reload_theme(self, theme):
        """
        新しいテーマ設定でウィジェットの色を更新します。
        
        Args:
            theme (ColorThemeManager): 新しいテーマを提供するマネージャーインスタンス。
        """
        self.frame.config(bg=theme.get('bg_main'))
        self.text_widget.config(
            bg=theme.get('output_bg'),
            fg=theme.get('output_text')
        )
