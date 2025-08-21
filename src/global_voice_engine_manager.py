# src/global_voice_engine_manager.py

import os
import time
import threading
from configparser import ConfigParser, NoSectionError, NoOptionError

from src.engines.voicevox_engine import VoicevoxEngine
from src.engines.aivisspeech_engine import AivisSpeechEngine

class GlobalVoiceEngineManager:
    """
    アプリケーション全体で利用される可能性のある全ての音声エンジンを
    起動時に一括で初期化・管理するクラス。
    """
    
    ENGINE_MAP = {
        'voicevox': VoicevoxEngine,
        'aivisspeech': AivisSpeechEngine,
    }

    def __init__(self, global_config):
        self.global_config = global_config
        self.running_engines = {}
        self.speaker_info_cache = {}

    def initialize_engines_and_cache_speakers(self, on_complete_callback):
        """
        'characters'フォルダ内の全キャラクターの設定をスキャンし、
        必要な音声エンジンを重複なく起動し、話者情報をキャッシュする。
        全ての処理が完了したら、指定されたコールバック関数を実行する。
        """
        print("利用可能な全キャラクターの音声エンジンを初期化します...")
        
        characters_dir = 'characters'
        if not os.path.isdir(characters_dir):
            on_complete_callback()
            return

        required_engines = set()

        # 1. 'characters'フォルダ内の全キャラクターのiniファイルを読み込み、必要なエンジン名を収集
        for char_dir_name in os.listdir(characters_dir):
            char_dir_path = os.path.join(characters_dir, char_dir_name)
            if not os.path.isdir(char_dir_path):
                continue

            char_ini_path = os.path.join(char_dir_path, 'character.ini')
            if os.path.exists(char_ini_path):
                try:
                    char_config = ConfigParser()
                    char_config.read(char_ini_path, encoding='utf-8')
                    engine_name = char_config.get('VOICE', 'engine', fallback='voicevox').lower()
                    required_engines.add(engine_name)
                except Exception as e:
                    print(f"警告: {char_ini_path} の読み込み中にエラー: {e}")

        print(f"起動が必要なエンジンリスト: {list(required_engines)}")

        threads = []  # 各エンジンを初期化するためのスレッドを格納するリスト
        lock = threading.Lock()  # 共有リソースへの書き込みを安全にするためのロック

        # 2. 収集したエンジン名を元に、エンジンを起動
        # --- 各エンジンを初期化するためのワーカー関数を定義 ---
        def worker(engine_name):
            """単一のエンジンを初期化し、話者情報をキャッシュするワーカー関数。"""
            try:
                EngineClass = self.ENGINE_MAP[engine_name]
                print(f"[{engine_name}スレッド] 起動処理を開始します...")
                dummy_char_config = ConfigParser()
                engine_instance = EngineClass(self.global_config, dummy_char_config, None)

                # エンジンの起動完了を待機
                max_wait_seconds = 60
                start_time = time.time()
                while not engine_instance.is_running:
                    if time.time() - start_time > max_wait_seconds:
                        print(f"エラー: [{engine_name}スレッド] {max_wait_seconds}秒以内に起動しませんでした。")
                        return # タイムアウト
                    time.sleep(1)

                # 起動が成功したら話者一覧を取得
                print(f"[{engine_name}スレッド] 準備完了を確認。話者一覧を取得します。")
                speakers = engine_instance.get_speakers()

                # --- ロックを使って共有リソース（辞書）を安全に更新 ---
                with lock:
                    self.running_engines[engine_name] = engine_instance
                    if speakers:
                        self.speaker_info_cache[engine_name] = speakers
                        print(f"[{engine_name}スレッド] 話者情報のキャッシュに成功。")
                    else:
                        print(f"警告: [{engine_name}スレッド] 話者一覧を取得できませんでした。")

            except Exception as e:
                print(f"エラー: [{engine_name}スレッド] 起動処理中に失敗: {e}")

        # 起動が必要な各エンジンに対してスレッドを作成して開始
        required_engines = {'voicevox', 'aivisspeech'} # 仮のデータ
        for engine_name in required_engines:
            thread = threading.Thread(target=worker, args=(engine_name,))
            threads.append(thread)
            thread.start() # スレッドを即座に開始

        # 全てのスレッドが終了するのを待つ
        for thread in threads:
            thread.join()

        print("全音声エンジンの並行初期化が完了しました。")
        on_complete_callback()
    
    def get_engine_instance(self, engine_name: str):
        """
        指定された名前の起動済みエンジンインスタンスを返す。
        """
        return self.running_engines.get(engine_name.lower())

    def shutdown_all(self):
        """
        管理している全てのエンジンをシャットダウンする。
        """
        print("管理下の全音声エンジンをシャットダウンします...")
        for engine_name, engine_instance in self.running_engines.items():
            try:
                engine_instance.shutdown()
            except Exception as e:
                print(f"エラー: エンジン '{engine_name}' のシャットダウンに失敗: {e}")

    def get_speaker_info(self, engine_name: str) -> list | None:
        """
        キャッシュ済みの話者情報リストを返す。
        """
        return self.speaker_info_cache.get(engine_name.lower())