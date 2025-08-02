# src/input_box.py

import tkinter as tk
from src.input_history_manager import InputHistoryManager
from typing import TYPE_CHECKING

from src.input_history_manager import InputHistoryManager
# 循環参照を避けるための型チェック用インポート
if TYPE_CHECKING:
    from src.character_controller import CharacterController

class InputBox:
    """
    ユーザーがテキストを入力するためのUIコンポーネント。
    エントリー（テキストボックス）と送信ボタンで構成される。
    履歴参照機能を追加。
    """
    def __init__(self, root, character_controller: 'CharacterController', send_callback, history_manager: InputHistoryManager, app):
        """
        InputBoxを初期化し、UI要素を作成・配置する。

        Args:
            root (tk.Tk): 親ウィンドウ。
            send_callback (function): 送信ボタンが押されたときのコールバック。
            history_manager (InputHistoryManager): 入力履歴を管理するインスタンス。
            app (DesktopMascot): アプリケーションのメインインスタンス。基準単位の取得に使用。
        """
        theme = character_controller.mascot_app.theme_manager
        self.frame = tk.Frame(root, bg=theme.get('bg_main'))
        # 内部パディングを基準単位で指定
        self.frame.pack(side="bottom", fill="x", pady=0, padx=0, ipady=app.padding_small, ipadx=app.padding_small)

        # テキスト入力欄
        self.entry = tk.Entry(
            self.frame, 
            font=app.font_normal, 
            bd=app.border_width_normal, 
            relief="solid",
            fg=theme.get('input_text'),
            bg=theme.get('input_bg'),
            insertbackground=theme.get('input_text'), # カーソルの色
            highlightbackground=theme.get('border_normal'), # 非フォーカス時の枠線
            highlightcolor=theme.get('border_focus'), # フォーカス時の枠線
            highlightthickness=app.border_width_normal
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=app.padding_small, pady=app.padding_small)

        # 送信ボタン
        self.send_button = tk.Button(
            self.frame, 
            text="送信", 
            command=self._send_and_save, 
            font=app.font_normal,
            fg=theme.get('button_text'),
            bg=theme.get('button_bg'),
            activeforeground=theme.get('button_active_text'),
            activebackground=theme.get('button_active_bg')
        )
        self.send_button.pack(side="right", padx=app.padding_small, pady=app.padding_small)
        
        self.entry.bind("<Return>", lambda event: self._send_and_save())

        # 履歴を確認機能
        self.send_callback = send_callback
        self.history_manager = history_manager
        self.history = self.history_manager.get_history()
        self.history_index = -1
        self.current_input = ""

        self.entry.bind("<Up>", self.on_key_up)
        self.entry.bind("<Down>", self.on_key_down)
        self.entry.bind("<Key>", self.on_any_key_press)

    def _send_and_save(self):
        """メッセージを送信し、入力を履歴に保存する内部メソッド。"""
        text = self.get_text()
        if text:
            # 1. 履歴に追加
            self.history_manager.add_entry(text)
            self.history = self.history_manager.get_history()
            
            # 2. メインのコールバックを呼び出し
            self.send_callback(text)
            
            # 3. 状態をリセット
            self.clear_text()
            self.history_index = -1
            self.current_input = ""

    def on_key_up(self, event):
        """上キーが押されたら、一つ古い履歴を表示する。"""
        if not self.history:
            return

        if self.history_index == -1:
            # 履歴を初めて遡る場合、現在の入力内容を保存
            self.current_input = self.get_text()

        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._show_history()

    def on_key_down(self, event):
        """下キーが押されたら、一つ新しい履歴を表示する。"""
        if self.history_index > 0:
            self.history_index -= 1
            self._show_history()
        elif self.history_index == 0:
            # 履歴の最後まで来たので、元の入力に戻す
            self.history_index = -1
            self.clear_text()
            self.entry.insert(0, self.current_input)

    def on_any_key_press(self, event):
        """上下キー以外のキーが押されたら、履歴モードを解除する。"""
        if event.keysym not in ("Up", "Down"):
            self.history_index = -1

    def _show_history(self):
        """現在のインデックスに基づいて履歴をエントリーに表示する。"""
        self.clear_text()
        self.entry.insert(0, self.history[self.history_index])

    def get_text(self):
        """入力されているテキストを取得する。"""
        return self.entry.get()

    def clear_text(self):
        """入力欄のテキストをすべて削除する。"""
        self.entry.delete(0, tk.END)

    def reload_theme(self, theme):
        """
        新しいテーマ設定でウィジェットの色を更新します。
        
        Args:
            theme (ColorThemeManager): 新しいテーマを提供するマネージャーインスタンス。
        """
        self.frame.config(bg=theme.get('bg_main'))
        self.entry.config(
            fg=theme.get('input_text'),
            bg=theme.get('input_bg'),
            insertbackground=theme.get('input_text'),
            highlightbackground=theme.get('border_normal'),
            highlightcolor=theme.get('border_focus'),
        )
        self.send_button.config(
            fg=theme.get('button_text'),
            bg=theme.get('button_bg'),
            activeforeground=theme.get('button_active_text'),
            activebackground=theme.get('button_active_bg')
        )