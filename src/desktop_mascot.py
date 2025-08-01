# src/desktop_mascot.py

import tkinter as tk
from tkinter import messagebox
import threading
import random
import time
from configparser import ConfigParser, NoSectionError, NoOptionError
import re
import os
import signal
import sys
import subprocess
from datetime import datetime, timedelta

# --- 自作モジュールのインポート ---
from src.log_manager import ConversationLogManager
from src.input_history_manager import InputHistoryManager
from src.character_controller import CharacterController
from src.voicevox_player import VoicevoxManager
from src.gemini_api_handler import GeminiAPIHandler
from src.screenshot_handler import ScreenshotHandler
from src.ui_manager import UIManager
from src.behavior_manager import BehaviorManager
from src.schedule_manager import ScheduleManager
from src.schedule_editor import ScheduleEditorWindow
from src.api_settings_editor import ApiSettingsEditorWindow
from src.color_theme_manager import ColorThemeManager

class DesktopMascot:
    """
    アプリケーション全体を制御するメインクラス。
    UIや自律行動の管理は専門クラスに委譲し、自身は各コンポーネントの統括と
    AIとの対話フローの中心的な制御に責任を持つ。
    """
    MAX_RALLY_COUNT = 3
    API_TIMEOUT_SECONDS = 30
    SCHEDULE_RETRY_MINUTES = 10
    
    def __init__(self, app_root_dir: str):
        """DesktopMascotを初期化し、アプリケーションの全コンポーネントを準備します。"""
        self.app_root_dir = app_root_dir
        
        self.root = tk.Tk()
        self.root.withdraw() 
        
        self.config = ConfigParser()
        self.config.read('config.ini', encoding='utf-8')
        
        # ColorThemeManagerをインスタンス化
        self.theme_manager = ColorThemeManager(self.config)
        self.theme_setting_var = tk.StringVar(value=self.config.get('UI', 'theme', fallback=''))

        self.pos_config = ConfigParser()
        self.pos_config_path = 'position.ini'
        self.pos_config.read(self.pos_config_path, encoding='utf-8')

        # --- UI基準単位の計算 ---
        screen_height = self.root.winfo_screenheight()
        # 1. 基準フォントサイズ (例: 画面の高さの1.2%を基準にする。1080pで約13px)
        self.base_font_size = max(8, int(screen_height * 0.012)) # 小さすぎないように下限を設ける
        self.font_title = ("Yu Gothic UI", self.base_font_size + 2, "bold") # 少し大きめのフォント
        self.font_normal = ("Yu Gothic UI", self.base_font_size)
        self.font_small = ("Yu Gothic UI", self.base_font_size - 2)

        # 2. 基準パディング (例: フォントサイズの半分)
        self.padding_large = self.base_font_size
        self.padding_normal = int(self.base_font_size * 0.5)
        self.padding_small = int(self.base_font_size * 0.25)

        # 3. 基準ボーダー幅 (例: フォントサイズの1/10)
        self.border_width_normal = max(1, int(self.base_font_size * 0.1)) # 常に1px以上

        # キャラクターをセットアップする前に、共有インスタンスを生成
        self.input_history_manager = InputHistoryManager()

        self.log_character_map = {}

        self._load_config_values()

        self._setup_characters()
        if self.is_shutting_down: return

        self.schedule_manager = ScheduleManager()
        self._setup_services()

        # --- アプリケーションの状態管理変数 ---
        self.is_shutting_down = False
        self.is_ready = False
        self.is_processing_lock = threading.Lock()
        self.last_time_signal_hour = -1
        self.auto_speech_cool_time = self.generate_cool_time()
        self.last_interaction_time = time.time()
        self.last_user_activity_time = time.time()
        self.is_user_away = False
        self.is_in_rally = False
        self.current_rally_count = 0
        self.prevent_cool_down_reset = False
        # 実行済みスケジュールキーを記録する辞書 {execution_key: execution_time}
        self.executed_schedule_keys = {}
        self.current_app_date = datetime.now().date()
        self.schedule_editor_window = None # スケジュール管理ウィンドウの参照を保持する変数
        self.api_settings_window = None # API設定ウィンドウの参照を保持する変数
        self.executed_schedules_this_minute = []
        self.last_checked_minute = -1

        self.last_api_request_time = None
        self.current_speaker_on_request = None
        self.capture_targets_cache = []
        self.tray_icon = None
        self.context_menu_target_char = None
        
        self.ui_manager = UIManager(self)
        self.behavior_manager = BehaviorManager(self)
    
    def _load_config_values(self):
        """config.iniから各種設定値を読み込み、インスタンス変数に格納します。"""
        self.gemini_test_mode = self.config.getboolean('GEMINI', 'GEMINI_TEST_MODE')
        self.gemma_test_mode = self.config.getboolean('GEMMA', 'GEMMA_TEST_MODE')
        self.gemma_api_key = self.config.get('GEMMA', 'GEMMA_API_KEY')
        self.gemma_model_name = self.config.get('GEMMA', 'GEMMA_MODEL_NAME')
        self.user_away_timeout = self.config.getint('UI', 'USER_AWAY_TIMEOUT', fallback=900)
        self.cool_time_min = self.config.getint('UI', 'COOL_TIME_MIN_SECONDS', fallback=90)
        self.cool_time_max = self.config.getint('UI', 'COOL_TIME_MAX_SECONDS', fallback=300)
        
        self.default_transparent_color = self.config.get('UI', 'TRANSPARENT_COLOR', fallback='#ff00ff')
        self.default_edge_color = self.config.get('UI', 'EDGE_COLOR', fallback='#838383')
        self.transparency_tolerance = self.config.getint('UI', 'TRANSPARENCY_TOLERANCE', fallback=50)

        try:
            screen_width = self.root.winfo_screenwidth()
            width_ratio = self.config.getfloat('UI', 'WINDOW_WIDTH_RATIO', fallback=0.2)
            self.window_width = int(screen_width * width_ratio)
        except (NoSectionError, NoOptionError):
            self.window_width = 400
        
        self.is_pro_mode = tk.BooleanVar(value=False)
        self.is_screenshot_mode = tk.BooleanVar(value=False)
        self.is_always_on_top = tk.BooleanVar(value=self.config.getboolean('UI', 'ALWAYS_ON_TOP', fallback=False))
        self.is_auto_speech_enabled = tk.BooleanVar(value=self.config.getboolean('UI', 'ENABLE_AUTO_SPEECH', fallback=True))
        self.is_schedule_enabled = tk.BooleanVar(value=self.config.getboolean('UI', 'ENABLE_SCHEDULES', fallback=True))
        self.is_sound_enabled = tk.BooleanVar(value=self.config.getboolean('UI', 'ENABLE_SOUND', fallback=True))
        
        self.cool_time_presets = {
            "短い (30～90秒)": (30, 90), "普通 (90～300秒)": (90, 300),
            "長い (300～900秒)": (300, 900), "無口 (900～1800秒)": (900, 1800)
        }
        self.cool_time_setting_var = tk.StringVar(value=self._find_current_cool_time_preset())
        self.selected_capture_target_key = tk.StringVar() 
        
        self.is_always_on_top.trace_add("write", self._toggle_always_on_top)
        self.is_sound_enabled.trace_add("write", self._toggle_mute)

    def get_available_change_characters(self):
        """
        現在画面に表示されておらず、交代可能なキャラクターのディレクトリ名リストを取得します。
        """
        characters_dir = 'characters'
        if not os.path.isdir(characters_dir):
            return []

        # 現在表示中のキャラクターのディレクトリ名を取得
        current_dirs = [os.path.basename(char.character_dir) for char in self.characters]
        
        # `characters` フォルダ内の全ディレクトリから、表示中のものを除外
        available_dirs = [
            d for d in os.listdir(characters_dir)
            if os.path.isdir(os.path.join(characters_dir, d)) and d not in current_dirs
        ]
        return available_dirs

    def change_character(self, target_char_id, new_char_dir_name):
        """
        指定されたキャラクターを新しいキャラクターと入れ替えます。

        Args:
            target_char_id (str): 入れ替え対象のキャラクターID ('1' または '2')。
            new_char_dir_name (str): 新しいキャラクターのディレクトリ名。
        """
        if not self.is_ready or self.is_processing_lock.locked():
            # アプリ準備中か、他の処理が実行中の場合は中断
            print("他の処理が実行中か、アプリが準備中のため、キャラクター変更を中断しました。")
            # ユーザーにフィードバックを返す
            char_to_notify = self.char1 if self.char1 and self.char1.ui.winfo_exists() else None
            if char_to_notify:
                char_to_notify.ui.output_box.set_text("今は他のことを考えているみたい...")
            return

        with self.is_processing_lock:
            print(f"キャラクター {target_char_id} を '{new_char_dir_name}' に変更します。")

            # 1. 古いキャラクターを特定して破棄
            is_char1 = target_char_id == '1'
            old_char = self.char1 if is_char1 else self.char2
            
            if old_char is None:
                print("エラー: 入れ替え対象のキャラクターが見つかりません。")
                return

            old_char_x = old_char.ui.winfo_x()
            old_char_is_flipped = old_char.is_left_side
            old_char_pos_side = 'left' if old_char_x < (self.root.winfo_screenwidth() / 2) else 'right'

            # リストから削除し、UIを破棄
            self.characters.remove(old_char)
            old_char.destroy()

            # 2. 新しいキャラクターを生成
            try:
                new_char = CharacterController(
                    self.root, self, target_char_id, new_char_dir_name, old_char_is_flipped, self.config, old_char_pos_side,
                    self.input_history_manager
                )
            except Exception as e:
                messagebox.showerror("キャラクター変更エラー", f"'{new_char_dir_name}'の読み込みに失敗しました。\nアプリケーションを終了します。お手数ですが手動で再起動してください。")
                # self.restart_app() #封印処置
                self.exit_app() # 安全に終了させる
                return

            # 3. リストと参照を更新
            if is_char1:
                self.char1 = new_char
                self.characters.insert(0, new_char) # 元の位置に挿入
            else:
                self.char2 = new_char
                self.characters.append(new_char)

            # 4. パートナー情報を再設定
            if self.is_char2_enabled:
                self.char1.set_partner(self.char2)
                self.char2.set_partner(self.char1)
            else:
                self.char1.set_partner(None)

            # 5. アプリケーションタイトルとサービスを更新
            self._update_app_title()
            self.screenshot_handler.app_titles = [char.ui.title() for char in self.characters]

            # 交代後の表示を確定させる（名前とハートの位置を含む）
            self.root.after(0, new_char.ui.update_info_display)

            # 6. 交代後の挨拶をリクエスト
            self.prevent_cool_down_reset = True
            prompt = "ユーザーの操作で、新しく登場しました。自己紹介を兼ねた短い挨拶をしてください。"
            self.request_speech(new_char, prompt, "起動挨拶")
            self._update_all_character_maps()

    def _update_app_title(self):
        """キャラクター情報に基づいてウィンドウタイトルを更新するヘルパーメソッド"""
        app_name = "ここここ"
        self.root.title(app_name)
        for char in self.characters:
            char.ui.title(f"{app_name} - {char.name}")

    def _setup_characters(self):
        """キャラクターのインスタンスを生成し、連携を設定します。position.iniを優先して使用します。"""
        self.characters = []
        self.char1, self.char2 = None, None
        self.is_shutting_down = False

        # --- 使用するコンフィグを選択 ---
        use_pos_config = self.pos_config.has_section('CHARACTER_1')
        main_config = self.pos_config if use_pos_config else self.config
        
        print(f"キャラクター設定の読み込み元: {'position.ini' if use_pos_config else 'config.ini'}")

        # --- キャラクター1の読み込み ---
        try:
            char1_dir = main_config.get('CHARACTER_1', 'DIRECTORY')
            char1_is_flipped = main_config.getboolean('CHARACTER_1', 'IS_FLIPPED' if use_pos_config else 'IS_LEFT_SIDE', fallback=False)
            char1_pos_side = main_config.get('CHARACTER_1', 'POSITION_SIDE', fallback='right')

            self.char1 = CharacterController(
                self.root, self, "1", char1_dir, char1_is_flipped, self.config, char1_pos_side,
                self.input_history_manager
            )
            self.characters.append(self.char1)

        except (NoSectionError, NoOptionError, FileNotFoundError) as e:
            messagebox.showerror("起動エラー", f"キャラクター1の読み込みに失敗しました。\n詳細: {e}")
            self.is_shutting_down = True; self.root.destroy(); return
            
        # --- キャラクター2の読み込み ---
        self.is_char2_enabled = main_config.getboolean('CHARACTER_2', 'ENABLED', fallback=False)
        if self.is_char2_enabled:
            try:
                char2_dir = main_config.get('CHARACTER_2', 'DIRECTORY')
                char2_is_flipped = main_config.getboolean('CHARACTER_2', 'IS_FLIPPED' if use_pos_config else 'IS_LEFT_SIDE', fallback=True)
                char2_pos_side = main_config.get('CHARACTER_2', 'POSITION_SIDE', fallback='left')

                self.char2 = CharacterController(
                    self.root, self, "2", char2_dir, char2_is_flipped, self.config, char2_pos_side,
                    self.input_history_manager
                )
                self.characters.append(self.char2)
            except (NoSectionError, NoOptionError, FileNotFoundError) as e:
                self.is_char2_enabled = False
                print(f"情報: キャラクター2は読み込みませんでした。1人モードで起動します。\n詳細: {e}")

        if self.char1 and self.char2:
            self.char1.set_partner(self.char2); self.char2.set_partner(self.char1)
        elif self.char1:
            self.char1.set_partner(None)

        # 全キャラクターの読み込みが完了したこのタイミングで、マップを構築する
        self._update_all_character_maps()
        self._update_app_title()

    def _update_all_character_maps(self):
        """
        現在のキャラクター構成に基づき、画面上の全キャラクターが持つ
        キャラクターマップを最新の状態に更新・同期します。
        """
        new_map = {'USER': 'ユーザー', 'SYSTEM': 'システム'}
        for char in self.characters:
            if char:
                new_map[char.character_id] = char.name
        
        # 全員のマップを同じものに更新
        for char in self.characters:
            if char:
                char.log_manager.character_map = new_map
        print(f"キャラクターマップを更新しました: {new_map}")

    def _setup_services(self):
        """共有サービス（音声、API、ログ等）を初期化します。"""
        self.voicevox_manager = VoicevoxManager(self.config)
        self.gemini_handler = GeminiAPIHandler(self.config)

        app_titles = [char.ui.title() for char in self.characters]
        self.screenshot_handler = ScreenshotHandler(app_titles)

        character_map = {char.character_id: char.name for char in self.characters if char}
        character_map.update({'USER': 'ユーザー', 'SYSTEM': 'システム'})

    def _log_event_for_all_characters(self, actor_id, target_id, action_type, content):
        """【新設】現在画面にいる全キャラクターのログファイルにイベントを記録します。"""
        for char in self.characters:
            if char:
                char.log_manager.add_entry(actor_id, target_id, action_type, content)

    def _create_tools_config_for_character(self, character):
        """指定されたキャラクターの現在の状態に基づいて、AIのツール設定を動的に生成します。"""
        # 現在の衣装で利用可能な感情の英語名リストを取得
        available_emotions_en = list(character.available_emotions.keys())
        
        function_declarations = [
            {"name": "generate_speech", "description": "キャラクターが話すためのセリフを生成します。", "parameters": {"type": "object", "properties": {"speech_text": {"type": "string", "description": "キャラクターとして発言する、自然で簡潔なセリフ。"}}, "required": ["speech_text"]}},
            {"name": "change_emotion", "description": "生成したセリフの内容に最もふさわしい感情を指定します。", "parameters": {"type": "object", "properties": {"emotion": {"type": "string", "description": "セリフに合わせた感情。", "enum": available_emotions_en}}, "required": ["emotion"]}},
            {
                "name": "change_favorability",
                "description": "ユーザーとの直近の会話を評価し、あなたの好感度をどれだけ変化させるかを決定します。ポジティブな内容なら正の数、ネガティブなら負の数を指定します。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "change_value": {
                            "type": "integer",
                            "description": "好感度の変化量。-25から25の範囲で指定してください。"
                        }
                    },
                    "required": ["change_value"]
                }
            },
            {"name": "change_costume", "description": "キャラクターの衣装を変更します。", "parameters": {"type": "object", "properties": {"costume_id": {"type": "string", "description": "変更したい衣装のID。"}}, "required": ["costume_id"]}}
        ]

        if self.is_char2_enabled:
            function_declarations.append({"name": "pass_turn_to_partner", "description": "相方との会話を続けるかどうかの意思表示をします。", "parameters": {"type": "object", "properties": {"continue_rally": {"type": "boolean", "description": "会話を続ける場合はTrue, 続けない場合はFalse。"}}, "required": ["continue_rally"]}})
        
        return [{"function_declarations": function_declarations}]

    def add_character(self, new_char_dir_name):
        """
        新しいキャラクターを画面に追加し、二人モードに移行します。
        """
        if len(self.characters) >= 2:
            return # 既に二人いる場合は何もしない

        if not self.is_ready or self.is_processing_lock.locked():
            print("他の処理が実行中か、アプリが準備中のため、キャラクター追加を中断しました。")
            if self.char1 and self.char1.ui.winfo_exists():
                 self.char1.ui.output_box.set_text("今は他のことを考えているみたい...")
            return
        
        with self.is_processing_lock:
            print(f"キャラクター '{new_char_dir_name}' を追加します。")

            # 1. 既存キャラクター(char1)がどちら側にいるか判定
            screen_center_x = self.root.winfo_screenwidth() / 2
            
            position_side_for_new_char = 'left' if (self.char1.ui.winfo_x() > screen_center_x) else 'right'
            is_flipped_for_new_char = False

            # 2. 新しいキャラクターを生成
            try:
                self.char2 = CharacterController(
                    self.root, self, '2', new_char_dir_name, is_flipped_for_new_char, self.config, position_side_for_new_char,
                    self.input_history_manager
                )
            except Exception as e:
                messagebox.showerror("キャラクター追加エラー", f"'{new_char_dir_name}'の読み込みに失敗しました。\n{e}")
                self.char2 = None
                return

            # 3. アプリケーションの状態を更新
            self.characters.append(self.char2)
            self.is_char2_enabled = True

            # 4. パートナー情報を再設定
            self.char1.set_partner(self.char2)
            self.char2.set_partner(self.char1)

            # 5. タイトルやハンドラを更新
            self._update_app_title()
            self.screenshot_handler.app_titles = [char.ui.title() for char in self.characters]

            # 追加したキャラクターの表示を確定させる（名前とハートの位置を含む）
            self.root.after(0, self.char2.ui.update_info_display)

            # 6. 新しく登場したキャラクターに挨拶させる
            self.prevent_cool_down_reset = True
            prompt = (f"ユーザーの操作で、隣にいる「{self.char1.name}」さんの相方として登場しました。"
                      f"ユーザーと「{self.char1.name}」さんに向けて、自己紹介を兼ねた短い挨拶をしてください。")
            self.request_speech(self.char2, prompt, "起動挨拶")
            self._update_all_character_maps() 

    def dismiss_character(self, character_to_dismiss):
        """
        指定されたキャラクターをお休みさせます。

        Args:
            character_to_dismiss (CharacterController): お休みさせる対象のキャラクター。
        """
        if len(self.characters) <= 1:
            return # UI側で制御されているはずだが、念のためガード

        if not self.is_ready or self.is_processing_lock.locked():
            print("他の処理が実行中か、アプリが準備中のため、キャラクターのお休みを中断しました。")
            character_to_dismiss.ui.output_box.set_text("今は他のことを考えているみたい...")
            return

        with self.is_processing_lock:
            if character_to_dismiss == self.char1:
                self._promote_char2_to_char1()
            elif character_to_dismiss == self.char2:
                self._dismiss_char2()
            
            # 共通の事後処理
            self.is_char2_enabled = False
            self._update_app_title()
            self.screenshot_handler.app_titles = [char.ui.title() for char in self.characters]
            self.reset_cool_time() # クールタイムをリセット
            print("キャラクターがお休みし、一人モードになりました。")
            self._update_all_character_maps()

    def _dismiss_char2(self):
        """キャラクター2をシンプルにお休みさせる処理です。"""
        print(f"キャラクター '{self.char2.name}' がお休みします。")
        
        # 1. リストから削除してUIを破棄
        self.characters.remove(self.char2)
        self.char2.destroy()
        self.char2 = None

        # 2. 残ったキャラクター1のパートナー情報を更新
        self.char1.set_partner(None)

    def _promote_char2_to_char1(self):
        """キャラクター1をお休みさせ、キャラクター2がその立場を引き継ぐ処理です。"""
        print(f"キャラクター '{self.char1.name}' がお休みし、'{self.char2.name}' が立場を引き継ぎます。")
        
        char1_to_dismiss = self.char1
        char2_to_promote = self.char2

        # 1. 退去するキャラクター1の位置と向きを保存
        original_char1_geometry = char1_to_dismiss.ui.geometry()
        original_char1_is_left = char1_to_dismiss.is_left_side

        # 2. キャラクター1を破棄
        self.characters.remove(char1_to_dismiss)
        char1_to_dismiss.destroy()

        # 3. キャラクター2の内部IDをキャラクター1のものに更新
        char2_to_promote.original_id = '1'
        char2_to_promote.character_id = 'CHAR_1'
        
        # 4. 保存しておいた位置と向きに移動・変身させる
        char2_to_promote.set_position_and_orientation(
            is_left=original_char1_is_left,
            geometry=original_char1_geometry
        )

        # 5. DesktopMascot側の管理情報を更新
        self.char1 = char2_to_promote
        self.char2 = None
        
        # 6. 新しくキャラクター1になったキャラのパートナー情報を更新
        self.char1.set_partner(None)

    def run(self):
        """アプリケーションのメインループを開始します。"""
        if self.is_shutting_down: return
            
        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)
        
        if self.tray_icon:
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

        threading.Thread(target=self.startup_sequence, daemon=True).start()
        self.root.mainloop()

    def _shutdown_voicevox_engine(self):
        """VOICEVOXエンジン(run.exe)を終了させます。"""
        if sys.platform != "win32": return
        try:
            subprocess.run(["taskkill", "/F", "/IM", "run.exe"], capture_output=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
            print("VOICEVOXエンジンの終了コマンドを送信しました。")
        except Exception as e:
            print(f"run.exeの終了中にエラーが発生しました: {e}")

    def _shutdown_services(self):
        """アプリケーション終了時に外部プロセスをクリーンアップします。"""
        self._shutdown_voicevox_engine()

    def _save_position_config(self):
        """現在のキャラクターの状態を position.ini に保存します。"""
        print("現在のキャラクター配置を position.ini に保存します...")
        new_pos_config = ConfigParser()

        if self.char1:
            # 画面中央より左にあれば 'left', 右にあれば 'right' とする
            char1_x_pos = self.char1.ui.winfo_x()
            screen_center_x = self.root.winfo_screenwidth() / 2
            position_side1 = 'left' if char1_x_pos < screen_center_x else 'right'
            
            new_pos_config['CHARACTER_1'] = {
                'DIRECTORY': os.path.basename(self.char1.character_dir),
                'POSITION_SIDE': position_side1,
                'IS_FLIPPED': str(self.char1.is_left_side)
            }

        if self.char2:
            char2_x_pos = self.char2.ui.winfo_x()
            screen_center_x = self.root.winfo_screenwidth() / 2
            position_side2 = 'left' if char2_x_pos < screen_center_x else 'right'

            new_pos_config['CHARACTER_2'] = {
                'ENABLED': 'True',
                'DIRECTORY': os.path.basename(self.char2.character_dir),
                'POSITION_SIDE': position_side2,
                'IS_FLIPPED': str(self.char2.is_left_side)
            }
        else:
            # キャラクター2がいない場合も、その状態を記録
            new_pos_config['CHARACTER_2'] = { 'ENABLED': 'False' }
        
        try:
            with open(self.pos_config_path, 'w', encoding='utf-8') as configfile:
                new_pos_config.write(configfile)
            print("position.ini の保存が完了しました。")
        except Exception as e:
            print(f"position.ini の保存中にエラーが発生しました: {e}")

    #一時封印中！ 安全確保まで絶対に起こすな
    #def restart_app(self):
    #    """アプリケーションを安全に再起動します。"""
    #    if self.is_shutting_down: return
    #    self.is_shutting_down = True
    #    self._save_position_config()
    #    if self.tray_icon: self.tray_icon.stop()
    #    self._shutdown_services()
    #    self.root.after(100, lambda: os.execl(sys.executable, sys.executable, *sys.argv))

    def exit_app(self):
        """アプリケーションを安全に終了します。"""
        if self.is_shutting_down: return
        self.is_shutting_down = True
        self._save_position_config()
        if self.tray_icon: self.tray_icon.stop()
        self._shutdown_services()
        self.root.after(100, self.root.destroy)
    
    def toggle_visibility(self):
        """キャラクターウィンドウの表示/非表示を切り替えます。"""
        if not self.characters: return
        is_visible = self.characters[0].ui.winfo_viewable()
        for char in self.characters:
            if is_visible: char.ui.withdraw()
            else: char.ui.deiconify()
    
    def bring_to_front(self, target_char=None):
        """指定されたキャラクターを最前面に移動させる。"""
        if target_char is None: target_char = self.context_menu_target_char
        if target_char and not self.is_always_on_top.get():
            self.root.after(0, self._bring_ui_to_front, target_char.ui)

    def _bring_ui_to_front(self, char_ui):
        """【UIスレッドで実行】UIウィンドウを一時的に最前面に表示する"""
        char_ui.wm_attributes("-topmost", True)
        char_ui.after(200, lambda: char_ui.wm_attributes("-topmost", False))

    def clear_log_for_character(self, target_char):
        """【新設】指定されたキャラクター一人の会話ログをクリアします。"""
        if not target_char:
            return
            
        target_char.log_manager.clear_log()
        target_char.ui.output_box.set_text("（私の記憶をリセットしました）")
        print(f"キャラクター '{target_char.name}' の会話ログをクリアしました。")

    def clear_all_logs(self):
        """【変更】現在アクティブなキャラクター全員の会話ログをクリアします。"""
        for char in self.characters:
            if char:
                char.log_manager.clear_log()
        
        # UIへの通知はランダムな一体から
        if self.characters:
            char_to_notify = random.choice(self.characters)
            char_to_notify.ui.output_box.set_text("（みんなの記憶をリセットしたよ）")
        print("全キャラクターの会話ログをクリアしました。")

    def show_context_menu(self, event):
        """右クリックイベントをUIManagerに中継します。"""
        self.ui_manager.show_context_menu(event)

    def startup_sequence(self):
        """
        起動時に実行される一連の初期化処理。
        UIの初期配置を最優先で行い、時間のかかる処理はバックグラウンドで続行します。
        """
        # 1. UIの初期配置を最優先でスケジュールする
        #    これにより、VOICEVOXの起動を待たずにキャラクターとハートが正しい位置に表示される
        self.root.after(0, self._apply_initial_settings)

        # 2. 時間のかかるVOICEVOXの起動処理をバックグラウンドで実行する
        if not self.voicevox_manager.ensure_engine_running():
            print("VOICEVOXの起動に失敗。音声なしで続行します。")
        
        # 3. 全てのバックグラウンド準備が整ってから、アプリケーションを「準備完了」状態にする
        #    UIの描画が安定するまで少し待つ
        time.sleep(1) 
        self.is_ready = True
        
        # 4. 準備完了後、起動挨拶と自律行動監視を開始する
        self.greet_on_startup()
        self.behavior_manager.start()
        
    def _apply_initial_settings(self):
        """起動時にconfigから読み込んだ設定をUIに適用します。"""
        self._toggle_always_on_top()
        self._toggle_mute()

        # 全キャラクターの初期位置を確定させる
        for char in self.characters:
            if char and char.ui.winfo_exists():
                char.ui.finalize_initial_position()

    def _toggle_always_on_top(self, *args):
        new_state = self.is_always_on_top.get()
        for char in self.characters:
            char.ui.wm_attributes("-topmost", new_state)

    def _toggle_mute(self, *args):
        self.voicevox_manager.set_mute_state(not self.is_sound_enabled.get())
        
    def _find_current_cool_time_preset(self):
        """現在のクールタイム設定に一致するプリセットのラベルを返します。"""
        for label, (min_val, max_val) in self.cool_time_presets.items():
            if self.cool_time_min == min_val and self.cool_time_max == max_val:
                return label
        return f"カスタム ({self.cool_time_min}～{self.cool_time_max}秒)"

    def _set_cool_time(self, label):
        """選択されたプリセットに応じてクールタイム設定を更新します。"""
        if label in self.cool_time_presets:
            min_val, max_val = self.cool_time_presets[label]
            self.cool_time_min, self.cool_time_max = min_val, max_val
            self.reset_cool_time()

    def _filter_ai_response(self, text):
        """AIが生成したセリフから不要な部分を除去します。"""
        text = re.sub(r'（[^）]*）|\([^)]*\)', '', text)
        common_emoticons = r'[:;=8][\-o\*\']?[\)\]\(\[dDpP/\\]|[\)\]\(\[dDpP/\\][\-o\*\']?[:;=8]'
        text = re.sub(common_emoticons, '', text)
        return text.strip()

    def handle_response_from_character(self, speaker, final_text, detected_function_calls):
        """AIからの応答を解析し、後続処理を実行する中心的なメソッド。"""
        self.current_speaker_on_request, self.last_api_request_time = None, None

        is_speech_call_missing = not any(call['name'] == 'generate_speech' for call in detected_function_calls)
        if (not detected_function_calls or is_speech_call_missing) and final_text and final_text.strip():
            detected_function_calls.append({'name': 'generate_speech', 'args': {'speech_text': final_text}})

        speech_text = ""
        target_emotion_jp = speaker.available_emotions.get('normal', 'normal') # デフォルトはnormal
        pass_turn = False
        print(speaker)
        for call in detected_function_calls:
            if call['name'] == 'generate_speech': 
                speech_text = call['args'].get('speech_text', '')
            elif call['name'] == 'change_emotion': 
                emotion_en = call['args'].get('emotion', 'normal').lower()
                target_emotion_jp = speaker.available_emotions.get(emotion_en, target_emotion_jp)
            elif call['name'] == 'pass_turn_to_partner': 
                pass_turn = call['args'].get('continue_rally', False)
            elif call['name'] == 'change_favorability': # 好感度変更の呼び出しを処理
                change_value_from_ai = call['args'].get('change_value')
                print(change_value_from_ai)
                if change_value_from_ai is not None:
                    try:
                        # 整数に変換を試みる (AIが "10" のように文字列で返しても対応可能)
                        change_int = int(change_value_from_ai)
                        print(change_int)
                        speaker.update_favorability(change_int)
                    except (ValueError, TypeError):
                        # 整数に変換できない不正な値が来た場合はエラーを出力して何もしない
                        print(f"警告: Geminiから不正な好感度変化量の値が返されました: {change_value_from_ai}")
            elif call['name'] == 'change_costume':
                if costume_id := call['args'].get('costume_id'):
                     self.root.after(0, speaker.change_costume, costume_id, False)

        filtered_text = self._filter_ai_response(speech_text)
        if not filtered_text:
            is_costume_change_only = any(call['name'] == 'change_costume' for call in detected_function_calls) and not speech_text
            if is_costume_change_only:
                self.reset_cool_time()
                if self.is_processing_lock.locked(): self.is_processing_lock.release()
                return
            filtered_text = speaker.msg_on_empty_response
            target_emotion_jp = speaker.available_emotions.get('troubled', speaker.available_emotions.get('normal', 'normal'))
            pass_turn = False
        
        target_id_for_log = speaker.partner.character_id if pass_turn and self.is_char2_enabled else 'USER'
        self._log_event_for_all_characters(speaker.character_id, target_id_for_log, 'SPEECH', filtered_text)

        if self.current_rally_count >= self.MAX_RALLY_COUNT: pass_turn = False

        # change_emotionの指定がない場合、Gemmaで感情を分析して補完する
        if target_emotion_jp == speaker.available_emotions.get('normal', 'normal'):
             emotion_percentages = speaker.gemma_api.analyze_emotion(speaker.log_manager.get_formatted_log())
             if emotion_percentages:
                 # Gemmaが返した理想の感情(日本語)を取得
                 gemma_result_jp = speaker.ui.emotion_handler.determine_display_emotion(emotion_percentages)
                 
                 # その感情が現在の衣装で利用可能かチェック
                 jp_to_en_map = {v: k for k, v in speaker.available_emotions.items()}
                 if gemma_result_jp in jp_to_en_map:
                     target_emotion_jp = gemma_result_jp
        
        wav_data = self.voicevox_manager.generate_wav(filtered_text, speaker.speaker_id, target_emotion_jp, speaker.voice_params)
        self.root.after(0, self.perform_synchronized_update, speaker, filtered_text, wav_data, target_emotion_jp, pass_turn)

    def perform_synchronized_update(self, speaker, text, wav_data, emotion_jp, pass_turn):
        """UIの更新と音声再生を同期させて実行します。"""
        # キャラクターがお休みするなどしてUIが破棄された後に、
        # 遅れてきたAPI応答がこの関数を呼び出す可能性があるため、
        # ウィンドウが存在するかを最初に確認します。
        if not speaker.ui.winfo_exists():
            print(f"[{speaker.name}] のUIは既に破棄されているため、UI更新と音声再生をスキップします。")
            # ロックが残っている場合があるので解放しておく
            if self.is_processing_lock.locked():
                self.is_processing_lock.release()
            return
        if self.is_shutting_down: return
        
        if not self.is_always_on_top.get():
             speaker.ui.lift_with_heart() # これにより、下の<FocusIn>イベントがトリガーされる

        speaker.ui.output_box.set_text(text or "...")
        speaker.ui.emotion_handler.update_image(emotion_jp)
        for char in self.characters:
            if char is not speaker: char.ui.emotion_handler.stop_lip_sync()

        def on_finish_callback():
            if self.is_char2_enabled and pass_turn:
                self.is_in_rally, self.current_rally_count = True, self.current_rally_count + 1
                prompt_for_partner = f"「{text}」"
                self.request_speech(speaker.partner, prompt_for_partner, "ラリー", situation="相方からの返答要求")
            else:
                self.is_in_rally = False
                speaker.ui.emotion_handler.stop_lip_sync()
                for char in self.characters:
                    if char is not speaker: char.ui.output_box.set_text("...")
                if self.prevent_cool_down_reset: self.prevent_cool_down_reset = False
                elif self.current_rally_count > 0: self.set_extended_cool_time_after_rally()
                else: self.reset_cool_time()
                self.current_rally_count = 0
                if self.is_processing_lock.locked(): self.is_processing_lock.release()

        if wav_data:
            def on_start_callback(): self.root.after(0, speaker.ui.emotion_handler.start_lip_sync, emotion_jp)
            self.voicevox_manager.play_wav(wav_data, on_start=on_start_callback, on_finish=on_finish_callback)
        else:
            on_finish_callback()

    def greet_on_startup(self):
        """起動時にキャラクターに挨拶をさせます。"""
        if self.is_processing_lock.locked() or not self.characters: return
        with self.is_processing_lock:
            speaker = random.choice(self.characters)
            # 発話者（speaker）自身のログファイルの存在をチェックする
            is_first_time = not os.path.exists(speaker.log_manager.log_file_path)
            if is_first_time:
                script = "「はじめまして。わたしは○○です。ドラッグで移動、右クリックで設定ができます。」"
                prompt = f"あなたは初めて起動しました。{script}を参考に、自己紹介と操作説明をあなたの口調でお願いします。"
            else:
                prompt = "再起動しました。ユーザーに挨拶をしてください。"
            
            if self.is_char2_enabled:
                prompt += "その後、隣にいる相方にも挨拶をして、会話のターンを渡してください(continue_rally=True)。"
                self.is_in_rally = True
                self.current_rally_count = 1
            
            self.request_speech(speaker, prompt, "起動挨拶")

            # 挨拶の5秒後に、今日の終日イベントをチェックする処理を予約
            self.root.after(5000, lambda: self.trigger_daily_events_for_date(datetime.now().date()))

    def trigger_auto_speech(self):
        """BehaviorManagerからのトリガーで自動発話を実行します。"""
        # 'with'文を削除し、手動でロックを取得する。
        # ロックの解放は、一連の処理が完了した後の on_finish_callback で行われる。
        # behavior_manager側でロックチェック済みだが、念のためここでも取得する。
        self.is_processing_lock.acquire()

        try:
            self.reset_cool_time()
            self.is_in_rally, self.current_rally_count = False, 0
            speaker = random.choice(self.characters)

            topics_filepath = self.config.get('UI', 'AUTO_SPEECH_TOPICS_FILE', fallback='')
            topics = []
            if topics_filepath and os.path.exists(topics_filepath):
                with open(topics_filepath, 'r', encoding='utf-8-sig') as f:
                    topics = [line.strip() for line in f if line.strip()]
            
            random_topic = random.choice(topics) if topics else None
            
            if self.is_char2_enabled:
                subjects, weights = ["ユーザーに話しかけてください。", "独り言を言ってください。", "相方に話しかけてください。(continue_rally=True)"], [2, 3, 5]
            else:
                subjects, weights = ["ユーザーに話しかけてください。", "独り言を言ってください。"], [3, 7]
            subject = random.choices(subjects, weights=weights, k=1)[0]
            
            prompt = f"システムからの自動発言要求です。"
            if random_topic: prompt += f"「{random_topic}」というキーワードについて自由に考えて、自然に{subject}"
            else: prompt += f"これまでの会話ログや現在時刻を考慮して、自然に{subject}"
            
            self.request_speech(speaker, prompt, "自動発言")

        except Exception as e:
            # 万が一、リクエスト前の処理でエラーが起きてもロックが解放されるようにする
            print(f"trigger_auto_speech 内で予期せぬエラー: {e}")
            if self.is_processing_lock.locked():
                self.is_processing_lock.release()
            
    def check_schedules(self):
        """10秒ごとにスケジュールをチェックし、リトライと重複実行防止を行う。"""
        # メソッドの冒頭で、スケジュール通知が無効なら全ての処理を中断する。
        if not self.is_schedule_enabled.get():
            return
        
        # 他の処理が実行中、または離席中なら何もしない
        if self.is_user_away or self.is_in_rally or self.is_processing_lock.locked():
            return

        now = datetime.now()
        
        # 古い実行記録を掃除する
        self._cleanup_old_schedule_records(now)

        # 実行すべきスケジュールを検索
        schedule_to_run = None
        for minute_offset in range(self.SCHEDULE_RETRY_MINUTES + 1):
            check_time = now - timedelta(minutes=minute_offset)
            
            due_schedules = self.schedule_manager.get_due_schedules(check_time)
            if not due_schedules:
                continue

            # この時刻に実行すべき未実行のスケジュールを見つける
            found = False
            for schedule in due_schedules:
                execution_key = schedule.get_execution_key(check_time)
                if execution_key not in self.executed_schedule_keys:
                    schedule_to_run = schedule
                    self.target_execution_time = check_time # 本来の実行時刻を保持
                    found = True
                    break
            if found:
                break
        
        if not schedule_to_run:
            return

        # ロックを取得して、見つけた1つのスケジュールを処理する
        if self.is_processing_lock.acquire(blocking=False):
            try:
                self.prevent_cool_down_reset = True
                speaker = random.choice(self.characters)
                schedule = schedule_to_run
                
                # 遅延リトライの場合の追加プロンプトを生成
                delay_minutes = (now - self.target_execution_time).total_seconds() / 60
                situation_prompt = "システムからのスケジュール通知要求です。"
                if delay_minutes > 1:
                    situation_prompt = f"システムからの遅延スケジュール通知要求です。約{int(delay_minutes)}分遅れです。"
                    if not self.is_schedule_enabled.get():
                         situation_prompt = "システムからのスケジュール通知要求です。ユーザーが通知をオフにしていた間の予定です。"


                prompt = (f"{situation_prompt}"
                          f"本来の予定時刻は{self.target_execution_time.strftime('%Y年%m月%d日 %H時%M分')}です。"
                          f"「{schedule.content}」という予定の通知を、状況に合わせてあなたの口調で発言してください。")

                if self.is_char2_enabled:
                    prompt += "もし相方にも話しかけたければ、ターンを渡してください(continue_rally=True)。"

                self._log_event_for_all_characters('SYSTEM', 'ALL', 'SCHEDULE', f"「{schedule.content}」の時刻です。")
                self.request_speech(speaker, prompt, "スケジュール通知")

                # 実行済みとして記録
                execution_key = schedule.get_execution_key(self.target_execution_time)
                self.executed_schedule_keys[execution_key] = now
                self.schedule_manager.mark_as_notified(schedule)

            except Exception as e:
                # 予期せぬエラー発生時は、必ずロックを解放してフリーズを防ぐ
                print(f"スケジュール処理中に予期せぬエラーが発生しました: {e}")
                if self.is_processing_lock.locked():
                    self.is_processing_lock.release()
        else:
            print("他の処理が実行中のため、スケジュール通知をスキップしました。")

    def _cleanup_old_schedule_records(self, now):
        """古くなった実行済みスケジュール記録を辞書から削除する。"""
        cutoff_time = now - timedelta(minutes=self.SCHEDULE_RETRY_MINUTES + 5)
        keys_to_delete = [
            key for key, exec_time in self.executed_schedule_keys.items()
            if exec_time < cutoff_time
        ]
        for key in keys_to_delete:
            del self.executed_schedule_keys[key]

    def check_for_date_change(self):
        """【新設】日付の変更を検知し、終日イベントの通知をトリガーする。"""
        today = datetime.now().date()
        if today != self.current_app_date:
            print(f"日付が {self.current_app_date} から {today} に変わりました。")
            self.current_app_date = today
            # 日付が変わったので、その日の終日イベントをチェック
            self.trigger_daily_events_for_date(today)

    def trigger_daily_events_for_date(self, target_date):
        """【新設】指定された日付の終日イベントを1つ見つけて通知する。"""
        if self.is_user_away or self.is_in_rally or self.is_processing_lock.locked():
            return
        
        daily_events = self.schedule_manager.get_daily_events(target_date)
        if not daily_events:
            return

        # 実行すべき未実行の終日イベントを1つ探す
        event_to_run = None
        for event in daily_events:
            exec_key = f"daily-{target_date.strftime('%Y-%m-%d')}-{event.content}"
            if exec_key not in self.executed_schedule_keys:
                event_to_run = event
                break
        
        if not event_to_run:
            return
            
        if self.is_processing_lock.acquire(blocking=False):
            try:
                self.prevent_cool_down_reset = True
                speaker = random.choice(self.characters)
                
                prompt = (f"システムからの今日の予定通知要求です。"
                          f"今日（{target_date.strftime('%Y年%m月%d日')}）は「{event_to_run.content}」の日です。"
                          f"このことについて、ユーザーに楽しく話しかけてください。")

                if self.is_char2_enabled:
                    prompt += "もし相方にも話しかけたければ、ターンを渡してください(continue_rally=True)。"

                self._log_event_for_all_characters('SYSTEM', 'ALL', 'DAILY_EVENT', f"今日は「{event_to_run.content}」の日です。")
                self.request_speech(speaker, prompt, "今日の予定通知")

                # 実行済みとして記録
                exec_key = f"daily-{target_date.strftime('%Y-%m-%d')}-{event_to_run.content}"
                self.executed_schedule_keys[exec_key] = datetime.now()
                self.schedule_manager.mark_as_notified(event_to_run)
            except Exception as e:
                print(f"終日イベントの処理中に予期せぬエラーが発生しました: {e}")
                if self.is_processing_lock.locked():
                    self.is_processing_lock.release()

    def open_api_settings_editor(self):
        """API設定ウィンドウを開く。"""
        # 既にウィンドウが開いている場合は、新しく開かずに最前面に表示する
        if self.api_settings_window and self.api_settings_window.winfo_exists():
            self.api_settings_window.lift()
            return
        
        # 右クリックされたキャラクターのウィンドウを親に設定
        parent_window = self.context_menu_target_char.ui if self.context_menu_target_char and self.context_menu_target_char.ui.winfo_exists() else self.root
        
        # メインコントローラー(self)を渡してウィンドウを生成
        self.api_settings_window = ApiSettingsEditorWindow(self.context_menu_target_char, parent_window, self)

    def open_schedule_editor(self):
        """スケジュール管理ウィンドウを開く。"""
        # 既にウィンドウが開いている場合は、新しく開かずに最前面に表示する
        if self.schedule_editor_window and self.schedule_editor_window.winfo_exists():
            self.schedule_editor_window.lift()
            return
        
        # 右クリックされたキャラクターを基準にする
        target_char_for_theme = self.context_menu_target_char if self.context_menu_target_char else self.char1
        parent_window = target_char_for_theme.ui if target_char_for_theme and target_char_for_theme.ui.winfo_exists() else self.root
        
        # self.schedule_editor_window = ScheduleEditorWindow(parent_window, self.schedule_manager, self)
        # 最後の引数に character_controller を追加
        self.schedule_editor_window = ScheduleEditorWindow(parent_window, self.schedule_manager, self, target_char_for_theme)
        
    def check_api_timeout(self):
        """APIリクエストのタイムアウトを監視します。"""
        if self.current_speaker_on_request and self.last_api_request_time:
            if time.time() - self.last_api_request_time > self.API_TIMEOUT_SECONDS:
                speaker = self.current_speaker_on_request
                self.current_speaker_on_request, self.last_api_request_time = None, None
                if self.is_processing_lock.locked(): self.is_processing_lock.release()
                
                error_text = speaker.msg_on_api_timeout
                emotion_jp = speaker.available_emotions.get('troubled', 'normal')
                wav_data = self.voicevox_manager.generate_wav(error_text, speaker.speaker_id, emotion_jp, speaker.voice_params)
                self.root.after(0, self.perform_synchronized_update, speaker, error_text, wav_data, emotion_jp, False)
    
    def request_speech(self, speaker, text, message_type, situation=None):
        """AIに応答生成をリクエストするプロンプトを組み立て、APIに送信します。"""
        self.last_api_request_time = time.time()
        self.current_speaker_on_request = speaker
        
        base_text = f"[{situation}] テキスト: {text}" if situation else text
        costume_info = speaker.costumes[speaker.current_costume_id]
        available_costumes_str = ", ".join([f"'{info['name']}' (id: {cid})" for cid, info in speaker.costumes.items()])
        user_recognition = speaker.get_user_recognition_status()
        costume_prompt = (f"【あなたの現在の状態】\n"
                          f"- あなたから見たユーザーへの認識: 『{user_recognition}』 (現在の好感度: {speaker.favorability})\n"
                          f"- 現在の衣装: 「{costume_info['name']}」(id: {speaker.current_costume_id})\n"
                          f"- 利用可能な衣装リスト: [{available_costumes_str}]\n"
                          f"- 現在時刻: {time.strftime('%H:%M:%S')}")
        print(costume_prompt)
        image_to_send, final_prompt_text = None, base_text
        if self.is_screenshot_mode.get() and self.screenshot_handler.is_available:
            selected_key = self.selected_capture_target_key.get()
            target_info = next((t for t in self.capture_targets_cache if (t.get('title') or t.get('name')) == selected_key), None)
            if target_info and (image_to_send := self.screenshot_handler.capture(target_info)):
                final_prompt_text += "\n\n【追加指示】添付されたスクリーンショットの内容を認識し、コメントが必要であればセリフに含めてください。"
        
        prompt = f"{costume_prompt}\n\n【指示】\n{final_prompt_text}"
        
        # このキャラクターの現在の状態で利用可能なツール設定を生成
        tools_config = self._create_tools_config_for_character(speaker)

        model_key_map = {
            "応答": 'pro' if self.is_pro_mode.get() else 'flash',
            "タッチ反応": 'flash-2',
            "衣装変更反応": 'flash-2',
            "スケジュール通知": 'flash',
            "今日の予定通知": 'flash'
            }
        model_key = model_key_map.get(message_type, 'flash-lite')
        
        self.gemini_handler.generate_response(
            prompt, speaker, message_type, model_key, tools_config,
            speaker.log_manager.get_formatted_log(), image=image_to_send
        )
    
    def set_extended_cool_time_after_rally(self):
        """会話ラリーの後はクールタイムを延長します。"""
        base_cool_time = self.generate_cool_time()
        self.auto_speech_cool_time = base_cool_time + (self.current_rally_count * 90)
        self.last_interaction_time = time.time()

    def reset_cool_time(self):
        """クールタイムをランダムに再設定します。"""
        self.auto_speech_cool_time = self.generate_cool_time()
        self.last_interaction_time = time.time()

    def generate_cool_time(self): 
        return random.randint(self.cool_time_min, self.cool_time_max)
    
    def reload_config_and_services(self):
        """
        再起動を避け、config.iniから設定を再読み込みして各サービスに反映させる。
        """
        print("設定を再読み込みしています...")
        if self.is_shutting_down: return

        try:
            # 1. configファイルを再読み込み
            self.config.read('config.ini', encoding='utf-8-sig')

            # 2. メインクラスが持つ設定値を更新
            self._load_config_values()

            # 3. 新しい設定でGeminiAPIHandlerを再生成して差し替える
            #    APILogManagerなども内部で再初期化されるため、これが最も安全。
            self.gemini_handler = GeminiAPIHandler(self.config)
            print("GeminiAPIHandlerを再初期化しました。")

            # 4. 各キャラクターが持つGemmaAPIを再生成させる
            for char in self.characters:
                if char:
                    char.reload_api_settings(self.gemma_api_key, self.gemma_model_name, self.gemma_test_mode)
            
            # 5. 新しい設定でVoicevoxManagerを更新
            new_exe_path = self.config.get('VOICEVOX', 'exe_path')
            new_api_url = self.config.get('VOICEVOX', 'api_url')
            # VoicevoxManagerに新しい設定を渡して、内部状態を更新させる
            self.voicevox_manager.reload_settings(new_exe_path, new_api_url)

            # 6. UIの表示を更新
            self.ui_manager.update_api_status_menu()
            
            print("設定の再読み込みが完了しました。")
            
            # ユーザーにフィードバックを返す
            char_to_notify = self.char1 if self.char1 and self.char1.ui.winfo_exists() else None
            if char_to_notify:
                char_to_notify.ui.output_box.set_text("APIの設定を更新したよ！")

        except Exception as e:
            print(f"設定の再読み込み中にエラーが発生しました: {e}")
            messagebox.showerror("再読み込みエラー", f"設定の反映中にエラーが発生しました:\n{e}")

    def set_theme(self, theme_name):
        """
        指定されたカラーテーマを適用し、UIを再読み込みします。
        """
        print(f"カラーテーマを '{theme_name or 'デフォルト'}' に変更します。")
        
        # 1. config.ini の設定値をメモリ上で更新
        self.config.set('UI', 'theme', theme_name)
        
        config_path = 'config.ini'
        
        try:
            # --- コメントを保持したままファイルを更新する処理 ---
            with open(config_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()

            new_lines = []
            current_section = ""
            
            for line in lines:
                stripped_line = line.strip()
                # セクション行を判定
                if stripped_line.startswith('[') and stripped_line.endswith(']'):
                    current_section = stripped_line[1:-1]
                
                # [UI]セクション内で、行頭が'theme'で始まる行を探す
                if current_section == 'UI' and stripped_line.lower().startswith('theme'):
                    # 元のインデントを保持して行を再構築
                    indentation = line[:line.lower().find('theme')]
                    new_lines.append(f"{indentation}theme = {theme_name}\n")
                else:
                    new_lines.append(line)
            
            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

        except Exception as e:
            messagebox.showerror("設定保存エラー", f"config.iniの保存中にエラーが発生しました:\n{e}")
            return
            
        # 2. ColorThemeManagerに新しいテーマファイルを読み込ませる
        self.theme_manager.load_theme()
        
        # 3. UIの再描画をトリガー
        self._reload_ui_theme()

    def _reload_ui_theme(self):
        """
        現在表示されている全てのUIコンポーネントのテーマを再適用します。
        """
        # 1. 各キャラクターのUIテーマを更新
        for char in self.characters:
            if char and char.ui.winfo_exists():
                char.reload_theme()
        
        # 2. スケジュールエディタが開いていれば、そちらも更新
        if self.schedule_editor_window and self.schedule_editor_window.winfo_exists():
            self.schedule_editor_window.reload_theme()
            
        # 3. API設定エディタが開いていれば、そちらも更新
        if self.api_settings_window and self.api_settings_window.winfo_exists():
            self.api_settings_window.reload_theme()
            
        print("UIテーマの再読み込みが完了しました。")
