# src/memory_manager.py

import os
import json
import threading
from datetime import datetime, timedelta
import uuid
from configparser import ConfigParser, NoSectionError, NoOptionError

class MemoryManager:
    """
    キャラクターの長期記憶（LTM）を管理するクラス。
    重要と判断された会話の要約を永続化し、AIのプロンプトに供給する。
    """
    LTM_FILE_NAME = "long_term_memory.log"

    def __init__(self, character_save_dir_path: str, config: ConfigParser):
        """
        MemoryManagerを初期化します。

        Args:
            character_save_dir_path (str): この記憶が属するキャラクターのセーブデータ用ディレクトリパス。
            config (ConfigParser): アプリケーション全体の設定情報。
        """
        self.file_path = os.path.join(character_save_dir_path, self.LTM_FILE_NAME)
        self.lock = threading.RLock()
        self.memory = []
        
        # configから設定値を読み込み
        try:
            self.ltm_history_limit = config.getint('UI', 'LONG_TERM_MEMORY_LIMIT')
            if self.ltm_history_limit <= 0:
                print(f"警告: LONG_TERM_MEMORY_LIMIT の値 ({self.ltm_history_limit}) が不正です。デフォルト値(50)を使用します。")
                self.ltm_history_limit = 50
        except (ValueError, NoSectionError, NoOptionError):
            self.ltm_history_limit = 50

        try:
            self.ltm_prompt_limit = config.getint('UI', 'LONG_TERM_MEMORY_PROMPT_LIMIT')
            if self.ltm_prompt_limit <= 0:
                print(f"警告: LONG_TERM_MEMORY_PROMPT_LIMIT の値 ({self.ltm_prompt_limit}) が不正です。デフォルト値(20)を使用します。")
                self.ltm_prompt_limit = 20
        except (ValueError, NoSectionError, NoOptionError):
            self.ltm_prompt_limit = 20

        self._ensure_file_exists()
        self.load_memory()

    def _ensure_file_exists(self):
        """長期記憶ファイルが存在しない場合に、空のリストを書き込んだファイルを作成する。"""
        with self.lock:
            if not os.path.exists(self.file_path):
                try:
                    with open(self.file_path, 'w', encoding='utf-8') as f:
                        json.dump([], f)
                    print(f"長期記憶ファイルを作成しました: {self.file_path}")
                except Exception as e:
                    print(f"長期記憶ファイルの作成に失敗しました: {e}")

    def load_memory(self):
        """
        長期記憶ファイルを読み込み、メモリにロードします。
        """
        with self.lock:
            if not os.path.exists(self.file_path):
                self.memory = []
                return

            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip(): self.memory = json.loads(content)
                    else: self.memory = []
            except (json.JSONDecodeError, Exception) as e:
                print(f"長期記憶の読み込みに失敗しました: {e}。ファイルをリセットします。")
                self.memory = []
                self.save_memory()

    def save_memory(self):
        """
        現在の長期記憶をファイルに保存します。
        """
        with self.lock:
            try:
                with open(self.file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.memory, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"長期記憶の保存に失敗しました: {e}")

    def add_entry(self, summary: str, importance: int):
        """
        新しい長期記憶を追加します。上限を超えた場合は、重要度の低い古い記憶を削除します。

        Args:
            summary (str): AIによって要約された記憶の内容。
            importance (int): 記憶の重要度 (1-100)。
        """
        with self.lock:
            now_iso = datetime.utcnow().isoformat()
            new_entry = {
                "id": str(uuid.uuid4()),
                "created_at": now_iso,
                "last_accessed_at": now_iso,
                "importance": importance,
                "summary": summary,
            }
            self.memory.append(new_entry)

            if len(self.memory) > self.ltm_history_limit:
                self.memory.sort(key=lambda x: (x.get('importance', 0), x.get('last_accessed_at', '')))
                removed = self.memory.pop(0)
                print(f"LTM上限超過のため、最も価値の低い記憶を削除しました: {removed.get('summary', 'N/A')[:30]}...")

            self.save_memory()

    def get_memories_for_prompt(self) -> list[dict]:
        """
        AIのプロンプト用に、重要度の高い長期記憶を整形して返します。

        Returns:
            list[dict]: {'id': ..., 'summary': ...} の形式の辞書のリスト。
        """
        with self.lock:
            if not self.memory:
                return []
            self.memory.sort(key=lambda x: (x.get('importance', 0), x.get('last_accessed_at', '')), reverse=True)
            return self.memory[:self.ltm_prompt_limit]

    def update_access_times(self, memory_ids: list[str]):
        """
        指定されたIDの記憶のlast_accessed_atを現在時刻で更新する。

        Args:
            memory_ids (list[str]): AIが参照したと報告した記憶のIDリスト。
        """
        if not memory_ids:
            return
        with self.lock:
            now_iso = datetime.utcnow().isoformat()
            updated_count = 0
            for entry in self.memory:
                if entry.get('id') in memory_ids:
                    entry['last_accessed_at'] = now_iso
                    updated_count += 1
            if updated_count > 0:
                print(f"{updated_count}件の長期記憶の最終アクセス日時を更新しました。")
                self.save_memory()

    def decay_importance(self):
        """
        全ての長期記憶の重要度を時間経過でわずかに減少させます。
        アプリケーション起動時などに呼び出すことを想定しています。
        """
        with self.lock:
            if not self.memory: return
            now = datetime.utcnow()
            changed = False
            for entry in self.memory:
                if not all(k in entry for k in ['importance', 'last_accessed_at']): continue
                if entry['importance'] >= 100: continue
                try:
                    last_accessed = datetime.fromisoformat(entry['last_accessed_at'])
                    if (now - last_accessed) > timedelta(days=3):
                        entry['importance'] = max(1, entry['importance'] - 1)
                        changed = True
                except (ValueError, TypeError): continue
            if changed:
                print("時間経過により、一部の長期記憶の重要度を減衰させました。")
                self.save_memory()