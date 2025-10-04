# src/engines/base_engine.py

from abc import ABC, abstractmethod
from configparser import ConfigParser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.character_controller import CharacterController

class BaseVoiceEngine(ABC):
    """
    全ての音声エンジンクラスが継承する抽象基底クラス。
    音声生成のインターフェースを定義します。
    """
    def __init__(self, global_config: ConfigParser, character_config: ConfigParser, character_controller: 'CharacterController'):
        """
        各エンジンクラスの初期化を行います。

        Args:
            global_config (ConfigParser): config.ini の内容
            character_config (ConfigParser): character.ini の内容
            character_controller (CharacterController): このエンジンを使用するキャラクターのコントローラー
        """
        self.global_config = global_config
        self.character_config = character_config
        self.character_controller = character_controller

    @abstractmethod
    def generate_wav(self, text: str, emotion_jp: str, character_volume_percent: int, speaker_id: int, voice_params: dict) -> bytes | None:
        """
        テキストから音声データを生成します。

        Args:
            text (str): 音声にするテキスト。
            emotion_jp (str): 感情の日本語名。
            character_volume_percent (int): キャラクターごとの音量設定(0-100)。

        Returns:
            bytes or None: 生成されたWAVデータ。失敗した場合はNone。
        """
        pass

    @abstractmethod
    def reload_settings(self):
        """
        設定が変更された際に呼び出され、エンジン固有の内部状態を更新します。
        """
        pass

    @abstractmethod
    def shutdown(self):
        """
        アプリケーション終了時に、エンジン固有のクリーンアップ処理（プロセス終了など）を行います。
        """
        pass