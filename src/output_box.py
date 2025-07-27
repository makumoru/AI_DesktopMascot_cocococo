# output_box.py

import tkinter as tk
from tkinter import ttk

class OutputBox:
    """
    AIからの応答テキストを表示するためのUIコンポーネント。
    TkinterのTextウィジェットとScrollbarウィジェットを使い、スクロール可能な表示領域を提供します。
    """
    def __init__(self, root, window_width):
        """
        OutputBoxのインスタンスを初期化し、テキスト表示用のウィジェットを生成します。

        Args:
            root (tk.Tk or tk.Frame): このウィジェットを配置する親ウィジェット。
            window_width (int): 親ウィンドウの幅。テキストの折り返し幅の計算に使用します。
        """
        font_size = 12

        # スクロールバーとテキストウィジェットを配置するためのフレーム
        self.frame = tk.Frame(root, bg="#e0e0e0")
        self.frame.pack(side="bottom", fill="x", pady=0, padx=0)

        # スクロールバーの作成
        self.scrollbar = ttk.Scrollbar(self.frame, orient="vertical")
        
        # Textウィジェットの作成
        self.text_widget = tk.Text(
            self.frame,
            font=("Arial", font_size),
            height=5,  # 複数行のテキストに対応できるよう、高さを5行分に固定
            bg="#e0e0e0",
            fg="black",
            padx=10,
            pady=10,
            wrap="word", # 単語単位で自動的に折り返す
            relief="solid",
            bd=1,
            # Textウィジェットの垂直スクロールコマンドをスクロールバーに接続
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