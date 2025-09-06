# src/voice_manager.py

import threading
import platform
from configparser import NoSectionError, NoOptionError

# --- プラットフォーム依存ライブラリのインポート ---
if platform.system() == "Windows":
    import winsound
else:
    print("警告: このコードの音声再生機能はWindows環境でのみ動作します。")

class VoiceManager:
    """
    音声エンジンを統括するクラス。
    キャラクターの設定に応じて適切なエンジンを呼び出し、音声再生を管理する。
    このクラスはキャラクターごとにインスタンス化されます。
    """
    def __init__(self, global_engine_manager, character_config, character_controller):
        """
        VoiceManagerを初期化し、キャラクター設定に応じたエンジンをロードします。
        
        Args:
            global_config (ConfigParser): config.ini の内容
            character_config (ConfigParser): character.ini の内容
            character_controller (CharacterController): 親となるキャラクターコントローラー
        """
        self.engine_instance = None
        
        # 変更点: DesktopMascotのグローバル設定から初期状態を直接読み込む
        # character_controller を経由して、アプリケーション全体の is_sound_enabled 変数を参照する
        app_controller = character_controller.mascot_app
        # is_sound_enabledがTrueならミュートはFalse、逆もまた然り
        self.is_muted = not app_controller.is_sound_enabled.get()
        self.character_controller = character_controller

        # 追加：キャラクター固有の情報をインスタンス変数として保持
        self.speaker_id = None
        self.engine_name = 'voicevox'
        # 解決に必要な情報を保存しておく
        self.global_engine_manager = global_engine_manager
        self.character_config = character_config
        self.is_id_resolution_attempted = False

        try:
            self.engine_name = self.character_config.get('VOICE', 'engine', fallback='voicevox').lower()
            # ここではエンジンのインスタンス参照だけ取得
            # self.engine_instance = self.global_engine_manager.get_engine_instance(self.engine_name)

        except Exception as e:
            print(f"[{self.character_controller.name}] VoiceManagerの基本初期化中にエラー: {e}")

    def resolve_speaker_id(self):
        """
        音声エンジンの準備完了後に呼び出され、話者IDを解決・設定する。
        """
        # 既に解決済み、または解決試行済みの場合は何もしない
        if self.speaker_id is not None or self.is_id_resolution_attempted:
            return
            
        self.is_id_resolution_attempted = True # 解決処理を実行したことを記録

        self.engine_instance = self.global_engine_manager.get_engine_instance(self.engine_name)

        if not self.engine_instance or not self.engine_instance.is_running:
            print(f"[{self.character_controller.name}] エンジン '{self.engine_name}' が利用不可のため、ID解決をスキップ。")
            return
        
        try:
            speaker_name_to_find = ""
            speaker_style_to_find = ""
            config_section = ""

            if self.engine_name == 'voicevox':
                config_section = 'VOICE_VOX'
            elif self.engine_name == 'aivisspeech':
                config_section = 'AIVIS_SPEECH'

            if config_section:
                speaker_name_to_find = self.character_config.get(config_section, 'speaker_name')
                speaker_style_to_find = self.character_config.get(config_section, 'speaker_style')

            if speaker_name_to_find and speaker_style_to_find:
                speaker_info = self.global_engine_manager.get_speaker_info(self.engine_name)
                if speaker_info:
                    self.speaker_id = self._find_speaker_id(
                        speaker_info, speaker_name_to_find, speaker_style_to_find
                    )

            if self.speaker_id is not None:
                print(f"[{self.character_controller.name}] 話者IDの解決に成功！")
                print(f"  -> 話者: '{speaker_name_to_find}' ({speaker_style_to_find}) / 解決後のID: {self.speaker_id}")
            else:
                print(f"エラー: [{self.character_controller.name}] character.iniで指定された話者が見つかりませんでした。")
                print(f"  -> 探索した名前: '{speaker_name_to_find}', スタイル: '{speaker_style_to_find}'")
                print(f"  -> 音声機能は無効になります。")
                self.engine_instance = None
        except (NoSectionError, NoOptionError) as e:
             print(f"[{self.character_controller.name}] ID解決中の設定読み込みエラー: {e}")


    def _find_speaker_id(self, speaker_data: list, name: str, style: str) -> int | None:
        """
        話者リストの中から、指定された名前とスタイルに一致する話者IDを探す。
        """
        for speaker in speaker_data:
            # 話者名が一致するかチェック
            if speaker.get('name') == name:
                # その話者が持つスタイルをループ
                for s in speaker.get('styles', []):
                    # スタイル名が一致するかチェック
                    if s.get('name') == style:
                        # IDが見つかったら即座に返す
                        return s.get('id')
        # 最後まで見つからなかった場合
        return None

    def generate_wav(self, text: str, emotion_jp: str, character_volume_percent: int) -> bytes | None:
        if not self.engine_instance or self.speaker_id is None:
            return None
            
        # エンジンを呼び出す際に、保持している話者IDとキャラクターの音声パラメータを渡す
        return self.engine_instance.generate_wav(
            text, 
            emotion_jp, 
            character_volume_percent,
            self.speaker_id, # ここで解決済みのIDを渡す
            self.character_controller.voice_params
        )

    def play_wav(self, wav_data: bytes, on_start=None, on_finish=None):
        """
        受け取ったWAVデータを別スレッドで再生します。この機能はエンジン非依存です。
        """
        if self.is_muted or not wav_data or platform.system() != "Windows":
            if on_finish:
                on_finish() # 再生しない場合でも完了コールバックは必ず呼ぶ
            return

        play_thread = threading.Thread(
            target=self._play_sound_sync,
            args=(wav_data, on_start, on_finish),
            daemon=True
        )
        play_thread.start()

    def _play_sound_sync(self, sound_data: bytes, on_start, on_finish):
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

    def set_mute_state(self, is_muted: bool):
        """ミュート状態を設定します。"""
        self.is_muted = is_muted

    def reload_settings(self):
        print(f"[{self.character_controller.name}] VoiceManagerの設定を再読み込みします。（話者IDの変更は再起動で反映されます）")
        try:
            char_config = self.character_controller.char_config
            self.engine_name = char_config.get('VOICE', 'engine', fallback='voicevox').lower()
            
            #if self.engine_name == 'voicevox':
            #    self.speaker_id = char_config.getint('VOICE_VOX', 'speaker_id')
            #elif self.engine_name == 'aivisspeech':
            #    self.speaker_id = char_config.getint('AIVIS_SPEECH', 'speaker_id')
            
            #print(f"[{self.character_controller.name}] 設定を再適用しました。(話者ID: {self.speaker_id})")
        except (NoSectionError, NoOptionError, ValueError) as e:
            print(f"話者IDの再読み込み中にエラー: {e}")

    def shutdown(self):
        """アプリケーション終了時に、エンジンインスタンスに必要なクリーンアップを指示します。"""
        pass