import os

class InputHistoryManager:
    """
    InputBoxでのユーザー入力履歴をファイルに永続化し、管理するクラス。
    """
    LOG_DIR = "logs"
    HISTORY_FILE_NAME = "input_history.log"
    HISTORY_LIMIT = 100 # 保存する履歴の最大件数

    def __init__(self):
        """
        InputHistoryManagerを初期化し、履歴ファイルを読み込む。
        """
        self.history_file_path = os.path.join(self.LOG_DIR, self.HISTORY_FILE_NAME)
        self.history = []
        
        # ログディレクトリが存在しない場合は作成
        os.makedirs(self.LOG_DIR, exist_ok=True)
        
        self.load_history()

    def load_history(self):
        """
        履歴ファイルから入力履歴を読み込み、リストに格納する。
        """
        if not os.path.exists(self.history_file_path):
            return # ファイルがなければ何もしない

        try:
            with open(self.history_file_path, 'r', encoding='utf-8') as f:
                # ファイルの内容を一行ずつ読み込み、改行文字を除去してリストに格納
                self.history = [line.strip() for line in f.readlines()]
        except Exception as e:
            print(f"入力履歴の読み込みに失敗しました: {e}")

    def add_entry(self, text):
        """
        新しい入力内容を履歴の先頭に追加し、ファイルに保存する。

        Args:
            text (str): ユーザーが入力したテキスト。
        """
        # 空の入力や、直前の履歴と同じ内容は追加しない
        if not text.strip() or (self.history and self.history[0] == text):
            return

        # 履歴の先頭に新しい項目を追加
        self.history.insert(0, text)
        
        # 履歴が上限を超えた場合、古いものから削除
        if len(self.history) > self.HISTORY_LIMIT:
            self.history = self.history[:self.HISTORY_LIMIT]

        # ファイルに書き込み
        try:
            with open(self.history_file_path, 'w', encoding='utf-8') as f:
                # 各履歴の末尾に改行を付けて書き込む
                f.write('\n'.join(self.history))
        except Exception as e:
            print(f"入力履歴の書き込みに失敗しました: {e}")

    def get_history(self):
        """
        現在の履歴リストを返す。
        """
        return self.history