# src/behavior_manager.py

import time
import random
import os
import sys

# --- Windows APIを呼び出すための準備 (ctypes) ---
# この機能はWindowsでのみ動作するため、プラットフォームをチェックします
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.UINT),
            ('dwTime', wintypes.DWORD),
        ]

    # Windows API関数のプロトタイプを定義
    user32 = ctypes.windll.user32
    GetLastInputInfo = user32.GetLastInputInfo
    GetLastInputInfo.restype = wintypes.BOOL
    GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]

    kernel32 = ctypes.windll.kernel32
    GetTickCount = kernel32.GetTickCount
    GetTickCount.restype = wintypes.DWORD
else:
    # pynputを削除したため、Windows以外では離席判定は無効になります
    LASTINPUTINFO = None


class BehaviorManager:
    """
    キャラクターの自律行動（自動発話、スケジュール、離席判定）のスケジューリングと
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
        """全てのスケジューリングを開始します。"""
        self.schedule_updates()
        self.schedule_minute_tasks()
        self.schedule_api_timeout_check()
        self.schedule_periodic_checks()

    def schedule_updates(self):
        """20秒ごとに定期実行されるタスク。"""
        if not self.app.is_ready: 
            self.root.after(5000, self.schedule_updates)
            return
        self.update_user_away_status()
        self.check_auto_speech()
        self.root.after(20000, self.schedule_updates)

    def schedule_minute_tasks(self):
        """10秒ごとに定期実行され、スケジュールをチェックします。"""
        self.app.check_schedules()
        self.app.check_for_date_change()
        self.root.after(10000, self.schedule_minute_tasks)
        
    def schedule_api_timeout_check(self):
        """1秒ごとに定期実行され、APIの応答タイムアウトを監視します。"""
        self.app.check_api_timeout()
        self.root.after(1000, self.schedule_api_timeout_check)

    def schedule_periodic_checks(self):
        """3時間ごとに定期実行され、モデルの有効性などをチェックします。"""
        self.app.check_model_validity_and_recommendations_async()
        # 3時間 (10,800,000ミリ秒) 後に再度実行
        self.root.after(3 * 60 * 60 * 1000, self.schedule_periodic_checks)

    def _get_idle_duration_windows(self) -> float:
        """
        Windows APIを使用して、最後のユーザー入力からの経過時間（秒）を取得します。
        
        Returns:
            float: アイドル状態の秒数。API呼び出しに失敗した場合は0.0を返す。
        """
        last_input_info = LASTINPUTINFO()
        last_input_info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        
        if GetLastInputInfo(ctypes.byref(last_input_info)):
            # GetTickCountはシステム起動からのミリ秒を返す
            current_ticks = GetTickCount()
            last_input_ticks = last_input_info.dwTime
            
            # TickCountのラップアラウンド（約49.7日で0に戻る）を考慮
            if current_ticks < last_input_ticks:
                idle_time_ms = (2**32 - last_input_ticks) + current_ticks
            else:
                idle_time_ms = current_ticks - last_input_ticks
                
            return idle_time_ms / 1000.0
        return 0.0

    def update_user_away_status(self):
        """一定時間ユーザーの操作がない場合、離席モードに移行・復帰します。"""
        # Windows以外のプラットフォームでは、この機能を無効化
        if sys.platform != "win32" or not LASTINPUTINFO:
            return
        
        idle_seconds = self._get_idle_duration_windows()
        is_currently_away = idle_seconds > self.app.user_away_timeout
        print(f"離席判定：{is_currently_away}｜停止時間：{idle_seconds}秒間")
        # 状態が変化した瞬間のみ処理を実行
        if is_currently_away and not self.app.is_user_away:
            # 「操作中」から「離席中」になった
            self.app.is_user_away = True
            print(f"ユーザーの操作が{self.app.user_away_timeout}秒間ありません。離席モードに移行します。")
        elif not is_currently_away and self.app.is_user_away:
            # 「離席中」から「操作中」になった
            self.app.is_user_away = False
            print("ユーザーの操作を検知しました。離席モードを解除します。")
            self.app.reset_cool_time()

    def check_auto_speech(self):
        """クールタイムが終了したら、自動発話のトリガーを引きます。"""
        if not self.app.is_auto_speech_enabled.get(): return
        if self.app.is_user_away or self.app.is_in_rally or self.app.is_processing_lock.locked(): return
        if not self.app.characters: return
        if time.time() - self.app.last_interaction_time > self.app.auto_speech_cool_time:
            self.app.trigger_auto_speech()