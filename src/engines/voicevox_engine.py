# src/engines/voicevox_engine.py

import requests
import platform
import subprocess
import time
import os
import threading
from configparser import NoSectionError, NoOptionError

from src.engines.base_engine import BaseVoiceEngine

class VoicevoxEngine(BaseVoiceEngine):
    """
    VOICEVOXエンジンとの連携を管理するクラス。
    """
    def __init__(self, global_config, character_config, character_controller):
        super().__init__(global_config, character_config, character_controller)
        self.is_running = False
        self.engine_process = None

        self._load_global_settings()
        
        # エンジンの自動起動
        # UIを固まらせないよう、起動処理は別スレッドで行う
        threading.Thread(target=self.ensure_engine_running, daemon=True).start()

    def _load_global_settings(self):
        """config.iniからVOICEVOXのグローバル設定を読み込む"""
        try:
            self.exe_path = self.global_config.get('VOICEVOX', 'exe_path')
            print(self.exe_path)
            self.api_url = self.global_config.get('VOICEVOX', 'api_url')
            print(self.api_url)
        except (NoSectionError, NoOptionError) as e:
            print(f"エラー: config.iniから[VOICEVOX]設定の読み込みに失敗 - {e}")
            self.exe_path = ""
            self.api_url = "http://127.0.0.1:50021"

    def _load_character_specific_settings(self):
        pass

    def _is_engine_running(self):
        """VOICEVOXエンジンがAPIリクエストに応答可能かを確認します。"""
        try:
            response = requests.get(f"{self.api_url}/version", timeout=1)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException:
            return False

    def _start_engine(self):
        """設定ファイルで指定されたパスからVOICEVOXエンジンを起動します。"""
        # デバッグログを追加して、読み込まれたパスが正しいか確認
        print(f"VOICEVOXエンジンのパスを確認しています: '{self.exe_path}'")

        if not self.exe_path or not os.path.exists(self.exe_path):
            print(f"エラー: config.iniで指定されたVOICEVOXのパスが見つからないか、不正です。パス: '{self.exe_path}'")
            return False
        
        print(f"VOICEVOXエンジンを起動します... ({self.exe_path})")
        try:
            if platform.system() == "Windows":
                # 起動したプロセスの情報を self.engine_process に格納
                self.engine_process = subprocess.Popen(
                    [self.exe_path], 
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # Linux/Mac用の処理は変更なし
                subprocess.Popen([self.exe_path])

            max_wait_time = 60
            start_time = time.time()
            while time.time() - start_time < max_wait_time:
                if self._is_engine_running():
                    print("VOICEVOX ENGINEの準備が完了しました。")
                    self.is_running = True
                    return True
                time.sleep(2)

            print(f"エラー: {max_wait_time}秒以内にVOICEVOX ENGINEが起動しませんでした。")
        except Exception as e:
            # エラーメッセージをより具体的に
            print(f"VOICEVOXエンジンの起動コマンド実行中にエラーが発生しました: {e}")
            return False
        return True 

    def ensure_engine_running(self):
        """VOICEVOXエンジンが起動していることを保証します。"""
        if self._is_engine_running():
            print("VOICEVOX ENGINEはすでに起動しています。")
            self.is_running = True
            return True
        return self._start_engine()

    def generate_wav(self, text: str, emotion_jp: str, character_volume_percent: int, speaker_id: int, voice_params: dict) -> bytes | None:
        if not self.is_running or not text:
            return None
            
        try:
            # 引数で渡された speaker_id を使用
            res_query = requests.post(
                f"{self.api_url}/audio_query",
                params={"text": text, "speaker": speaker_id}
            )
            res_query.raise_for_status()
            audio_query_data = res_query.json()

            # --- 音量計算ロジック (引数の voice_params を使用) ---
            emotion_base_volume = 1.0
            if voice_params:
                params_to_apply = voice_params.get(emotion_jp, voice_params.get("normal", {}))
                emotion_base_volume = float(params_to_apply.get('volumeScale', 1.0))

            character_volume_ratio = character_volume_percent / 100.0
            final_volume_scale = emotion_base_volume * character_volume_ratio

            # --- 感情パラメータ適用ロジック (引数の voice_params を使用) ---
            if voice_params:
                params_to_apply = voice_params.get(emotion_jp, voice_params.get("normal", {}))
                # デバッグ用のprintは character_controller がないと動かないので修正
                # print(f"[{self.character_controller.name}] ...")
                for key, value in params_to_apply.items():
                    if key in audio_query_data and key != 'volumeScale':
                        audio_query_data[key] = float(value)
            
            audio_query_data['volumeScale'] = final_volume_scale

            # --- 音声合成 (引数の speaker_id を使用) ---
            res_synth = requests.post(
                f"{self.api_url}/synthesis",
                params={"speaker": speaker_id},
                json=audio_query_data,
                timeout=20
            )
            res_synth.raise_for_status()
            
            return res_synth.content
            
        except requests.exceptions.HTTPError as e:
            print(f"VOICEVOX APIエラー: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            print(f"音声データの生成中に予期せぬエラーが発生しました: {e}")
        return None

    def reload_settings(self):
        """グローバル設定が変更された際に内部状態を更新する"""
        print(f"[{self.character_controller.name}] VOICEVOXエンジンの設定を再読み込みします。")
        self._load_global_settings()
        # エンジンが起動していない場合、新しい設定で起動を試みる
        if not self.is_running:
             threading.Thread(target=self.ensure_engine_running, daemon=True).start()

    def shutdown(self):
        """
        保持しているプロセス情報を使い、直接プロセスを終了させる
        VOICEVOXエンジン(run.exe)を終了させます。
        """
        # ログ出力用のプレフィックスを動的に決定する
        log_prefix = f"[{self.character_controller.name}]" if self.character_controller else "[Global]"

        if self.engine_process and self.engine_process.poll() is None:
            print(f"{log_prefix} VOICEVOXエンジンプロセスを終了します (PID: {self.engine_process.pid})...")
            try:
                self.engine_process.terminate()
                self.engine_process.wait(timeout=5)
                print("VOICEVOXエンジンプロセスは正常に終了しました。")
            except subprocess.TimeoutExpired:
                print("VOICEVOXエンジンが5秒以内に応答しませんでした。強制終了します。")
                self.engine_process.kill()
            except Exception as e:
                print(f"{log_prefix} VOICEVOXエンジンの終了中にエラーが発生しました: {e}")
        else:
            print(f"{log_prefix} VOICEVOXエンジンは既に終了しているか、起動していません。")

    def get_speakers(self) -> list | None:
        """
        エンジンから利用可能な話者の一覧を取得します。
        """
        if not self._is_engine_running():
            print(f"[{self.__class__.__name__}] エンジンが起動していないため、話者一覧を取得できません。")
            return None
        try:
            response = requests.get(f"{self.api_url}/speakers", timeout=5)
            response.raise_for_status()
            print(f"[{self.__class__.__name__}] 話者一覧の取得に成功しました。")
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"[{self.__class__.__name__}] 話者一覧の取得中にAPIエラーが発生しました: {e}")
            return None