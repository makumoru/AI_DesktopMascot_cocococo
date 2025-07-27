# src/behavior_manager.py

import time
import random
import os

try:
    from pynput import mouse, keyboard
except ImportError:
    mouse, keyboard = None, None

class BehaviorManager:
    """
    キャラクターの自律行動（自動発話、時報、離席判定）のスケジューリングと
    トリガーを担当するクラス。
    """
    def __init__(self, app):
        """
        BehaviorManagerを初期化します。

        Args:
            app (DesktopMascot): 親となるアプリケーションのインスタンス。
        """
        self.app = app
        self.root = app.root

    def start(self):
        """全てのスケジューリングとリスナーを開始します。"""
        self.schedule_updates()
        self.schedule_time_signal()
        self.schedule_api_timeout_check()
        self.start_activity_listener()

    def schedule_updates(self):
        """20秒ごとに定期実行されるタスク。"""
        if not self.app.is_ready: 
            self.root.after(5000, self.schedule_updates)
            return
        self.update_user_away_status()
        self.check_auto_speech()
        self.root.after(20000, self.schedule_updates)

    def schedule_time_signal(self):
        """60秒ごとに定期実行され、時報をチェックします。"""
        self.check_time_signal()
        self.root.after(60000, self.schedule_time_signal)
        
    def schedule_api_timeout_check(self):
        """1秒ごとに定期実行され、APIの応答タイムアウトを監視します。"""
        self.app.check_api_timeout() # このロジックはapp側に残す
        self.root.after(1000, self.schedule_api_timeout_check)

    def start_activity_listener(self):
        """ユーザーのマウス・キーボード操作の監視を開始します。"""
        if not mouse or not keyboard: return
        mouse_listener = mouse.Listener(on_move=self._on_user_activity, on_click=self._on_user_activity, on_scroll=self._on_user_activity, daemon=True)
        keyboard_listener = keyboard.Listener(on_press=self._on_user_activity, daemon=True)
        mouse_listener.start()
        keyboard_listener.start()
        print(f"ユーザーアクティビティの監視を開始しました（離席判定: {self.app.user_away_timeout}秒）。")

    def _on_user_activity(self, *args):
        """ユーザーのPC操作が検知されたときのコールバック。"""
        self.app.last_user_activity_time = time.time()
        if self.app.is_user_away:
            self.app.is_user_away = False
            print("ユーザーの操作を検知しました。離席モードを解除します。")
            self.app.reset_cool_time()

    def update_user_away_status(self):
        """一定時間ユーザーの操作がない場合、離席モードに移行します。"""
        if self.app.is_user_away: return
        if time.time() - self.app.last_user_activity_time > self.app.user_away_timeout:
            self.app.is_user_away = True
            print(f"ユーザーの操作が{self.app.user_away_timeout}秒間ありません。離席モードに移行します。")

    def check_auto_speech(self):
        """クールタイムが終了したら、自動発話のトリガーを引きます。"""
        if not self.app.is_auto_speech_enabled.get(): return
        if self.app.is_user_away or self.app.is_in_rally or self.app.is_processing_lock.locked(): return
        if not self.app.characters: return
        if time.localtime().tm_min in [0, 1]: return # 時報の直後は実行しない
        if time.time() - self.app.last_interaction_time > self.app.auto_speech_cool_time:
            # 実際のプロンプト生成とリクエストはDesktopMascotに委譲
            self.app.trigger_auto_speech()

    def check_time_signal(self):
        """毎時0分に時報のトリガーを引きます。"""
        if self.app.is_user_away or self.app.is_in_rally or self.app.is_processing_lock.locked(): return
        if not self.app.characters: return
        
        current_time = time.localtime()
        if current_time.tm_min == 0 and current_time.tm_hour != self.app.last_time_signal_hour:
            # 実際のプロンプト生成とリクエストはDesktopMascotに委譲
            self.app.trigger_time_signal()