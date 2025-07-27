# src/log_manager.py

import os
import threading
from datetime import datetime

class ConversationLogManager:
    """
    会話ログの永続化（ファイルへの保存・読み込み）と管理を行うクラス。
    アプリケーションを再起動しても会話の文脈が維持されるようにします。
    """
    LOG_FILE_NAME = "conversation_log.log" # ログファイル名
    LOG_HISTORY_LIMIT = 20 # AIに渡す会話履歴の最大件数

    def __init__(self, log_dir, character_map):
        """
        ConversationLogManagerを初期化します。

        Args:
            log_dir (str): ログファイルを保存するディレクトリのパス。
            character_map (dict): キャラクターIDと名前を対応させる辞書。ログを人間可読にするために使用。
        """
        self.log_dir = log_dir
        self.log_file_path = os.path.join(self.log_dir, self.LOG_FILE_NAME)
        self.character_map = character_map # {'CHAR_1': 'ずんだもん', ...}
        self.lock = threading.Lock() # 複数スレッドからの同時書き込みを防ぐためのロック
        os.makedirs(self.log_dir, exist_ok=True) # ログディレクトリがなければ作成

    def add_entry(self, actor_id, target_id, action_type, content):
        """
        新しいログエントリをファイルに追記します。

        Args:
            actor_id (str): 発言/行動した主体 ('USER', 'CHAR_1', 'SYSTEM'など)。
            target_id (str): 発言/行動の対象 ('USER', 'CHAR_2', 'ALL'など)。
            action_type (str): 行動の種類 ('INPUT', 'SPEECH', 'TOUCH', 'INFO'など)。
            content (str): 発言内容やアクション名。
        """
        with self.lock:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # ログファイルはカンマ区切りなため、コンテンツ内の改行やカンマを安全な文字列に置換（エスケープ）します。
            safe_content = content.replace(',', '<comma>').replace('\n', '<br>')
            log_line = f"{timestamp},{actor_id},{target_id},{action_type},{safe_content}\n"
            try:
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    f.write(log_line)
            except Exception as e:
                print(f"会話ログの書き込みに失敗しました: {e}")

    def get_formatted_log(self):
        """
        保存されているログを読み込み、AIのプロンプトに適した形式に変換して返します。

        Returns:
            list[str]: 人間が読みやすい形式に整形された会話ログのリスト。
                       例: ["ユーザー(ずんだもんへ): こんにちは", "ずんだもん: こんにちはなのだ"]
        """
        with self.lock:
            if not os.path.exists(self.log_file_path):
                return []
            
            try:
                with open(self.log_file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except Exception as e:
                print(f"会話ログの読み込みに失敗しました: {e}")
                return []

        # 最新のログから一定件数のみを対象とします。
        recent_lines = lines[-self.LOG_HISTORY_LIMIT:]
        formatted_log = []
        for line in recent_lines:
            try:
                parts = line.strip().split(',', 4)
                if len(parts) < 5: continue
                
                _timestamp, actor_id, target_id, action_type, content = parts
                # エスケープされた文字を元の文字に戻します。
                content = content.replace('<comma>', ',').replace('<br>', '\n')

                # IDをキャラクター名に変換します。
                actor_name = self.character_map.get(actor_id, actor_id)
                target_name = self.character_map.get(target_id, target_id)
                
                # ログの種類に応じて、整形された文字列を生成します。
                entry = ""
                if action_type == 'INPUT':
                    entry = f"ユーザー({target_name}へ): {content}"
                elif action_type == 'SPEECH':
                    if target_id == 'USER':
                        entry = f"{actor_name}: {content}"
                    else:
                        entry = f"{actor_name}({target_name}へ): {content}"
                elif action_type == 'TOUCH':
                    entry = f"ユーザー({target_name}へ): [アクション] {content}"
                elif action_type == 'INFO':
                     entry = f"システム: {content}"
                
                if entry:
                    formatted_log.append(entry)

            except Exception as e:
                print(f"ログ行の解析に失敗: {line.strip()} - {e}")
                continue
        
        return formatted_log

    def clear_log(self):
        """会話ログファイルを削除して、会話履歴をリセットします。"""
        with self.lock:
            if os.path.exists(self.log_file_path):
                try:
                    os.remove(self.log_file_path)
                    print("会話ログをクリアしました。")
                except Exception as e:
                    print(f"会話ログのクリアに失敗しました: {e}")