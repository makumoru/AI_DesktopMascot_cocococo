# input_box.py

import tkinter as tk

class InputBox:
    """
    ユーザーがテキストを入力するためのUIコンポーネント。
    エントリー（テキストボックス）と送信ボタンで構成される。
    """
    def __init__(self, root, send_callback):
        """
        InputBoxを初期化し、UI要素を作成・配置する。

        Args:
            root (tk.Tk): 親ウィンドウ。
            send_callback (function): 送信ボタンが押されたとき、またはEnterキーが押されたときに
                                      呼び出されるコールバック関数。入力されたテキストが引数として渡される。
        """
        self.frame = tk.Frame(root, bg="white")
        # packのオプションで親ウィジェットの下部にぴったりと配置
        self.frame.pack(side="bottom", fill="x", pady=0, padx=0, ipady=5, ipadx=5)

        # テキスト入力欄
        self.entry = tk.Entry(self.frame, font=("Arial", 12), bd=2, relief="solid")
        self.entry.pack(side="left", fill="x", expand=True, padx=5, pady=5)

        # 送信ボタン
        self.send_button = tk.Button(self.frame, text="送信", command=lambda: send_callback(self.entry.get()))
        self.send_button.pack(side="right", padx=5, pady=5)
        
        # Enterキーを押したときにも送信できるようにイベントをバインド
        self.entry.bind("<Return>", lambda event: send_callback(self.entry.get()))

    def get_text(self):
        """入力されているテキストを取得する。"""
        return self.entry.get()

    def clear_text(self):
        """入力欄のテキストをすべて削除する。"""
        self.entry.delete(0, tk.END)