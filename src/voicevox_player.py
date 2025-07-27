# voicevox_player.py

import requests
import platform
import subprocess
import time
import os
import threading
import ast

# --- プラットフォーム依存ライブラリのインポート ---
if platform.system() == "Windows":
    import winsound
else:
    print("警告: このコードの自動起動・再生機能はWindows環境でのみ動作します。")

class VoicevoxManager:
    """
    VOICEVOXエンジンとの連携を管理するクラス。
    エンジンの起動、感情に応じた音声データの生成、バックグラウンドでの再生、
    および口パクアニメーションと同期するためのコールバック機能を提供します。
    """
    def __init__(self, config):
        """
        VoicevoxManagerを初期化します。
        config.iniからVOICEVOX関連の設定（実行ファイルのパス、APIのURL）を読み込みます。

        Args:
            config (ConfigParser): 設定情報。
        """
        try:
            self.exe_path = config.get('VOICEVOX', 'exe_path')
            self.api_url = config.get('VOICEVOX', 'api_url')
        except Exception as e:
            print(f"エラー: config.iniからVOICEVOX設定の読み込みに失敗 - {e}")
            self.exe_path = ""
            self.api_url = "http://127.0.0.1:50021"
            
        self.is_running = False
        self.is_muted = False

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
        if not self.exe_path or not os.path.exists(self.exe_path):
            print(f"エラー: config.ini指定のVOICEVOXパスが見つかりません: {self.exe_path}")
            return False
        
        print(f"VOICEVOXを起動します... ({self.exe_path})")
        try:
            if platform.system() == "Windows":
                subprocess.Popen([self.exe_path], creationflags=0x08000000) 
            else:
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
            return False
        except Exception as e:
            print(f"VOICEVOXの起動中にエラーが発生しました: {e}")
            return False

    def ensure_engine_running(self):
        """VOICEVOXエンジンが起動していることを保証します。"""
        if self._is_engine_running():
            print("VOICEVOX ENGINEはすでに起動しています。")
            self.is_running = True
            return True
        return self._start_engine()
        
    def generate_wav(self, text, speaker_id, emotion_jp="normal", voice_params=None):
        """
        指定されたテキスト、話者ID、感情からWAV形式の音声データを生成します。

        Args:
            text (str): 音声にするテキスト。
            speaker_id (int): VOICEVOXの話者ID。
            emotion_jp (str, optional): 感情の日本語名。デフォルトは "normal"。
            voice_params (dict, optional): character.iniから読み込んだ音声パラメータの辞書。

        Returns:
            bytes or None: 生成されたWAVデータ。失敗した場合はNone。
        """
        if not self.is_running or not text:
            return None
            
        try:
            res_query = requests.post(
                f"{self.api_url}/audio_query",
                params={"text": text, "speaker": speaker_id}
            )
            res_query.raise_for_status()
            audio_query_data = res_query.json()

            # 引数で渡された音声パラメータを適用する
            if voice_params:
                # 指定された感情のパラメータを取得、なければ'normal'のパラメータにフォールバック
                params_to_apply = voice_params.get(emotion_jp, voice_params.get("normal", {}))
                print(f"音声生成に適用する感情パラメータ ({emotion_jp}): {params_to_apply}")

                for key, value in params_to_apply.items():
                    if key in audio_query_data:
                        audio_query_data[key] = float(value)

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

    def set_mute_state(self, is_muted):
        """ミュート状態を設定します。"""
        self.is_muted = is_muted

    def play_wav(self, wav_data, on_start=None, on_finish=None):
        """受け取ったWAVデータを別スレッドで再生します。"""
        if self.is_muted or not wav_data or platform.system() != "Windows":
            if on_finish:
                on_finish()
            return
        
        play_thread = threading.Thread(
            target=self._play_sound_sync, 
            args=(wav_data, on_start, on_finish), 
            daemon=True
        )
        play_thread.start()

    def _play_sound_sync(self, sound_data, on_start, on_finish):
        """【別スレッドで実行】音声データを同期的に再生し、コールバックで通知します。"""
        try:
            if on_start:
                on_start()
            winsound.PlaySound(sound_data, winsound.SND_MEMORY)
        except Exception as e:
            print(f"音声の再生中にエラーが発生しました: {e}")
        finally:
            if on_finish:
                on_finish()