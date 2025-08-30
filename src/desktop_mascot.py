# src/desktop_mascot.py

import tkinter as tk
from tkinter import messagebox, ttk, font
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
import urllib.request
import urllib.error
import json
import webbrowser

# --- 自作モジュールのインポート ---
from src.log_manager import ConversationLogManager
from src.input_history_manager import InputHistoryManager
from src.character_controller import CharacterController
from src.gemini_api_handler import GeminiAPIHandler
from src.screenshot_handler import ScreenshotHandler
from src.ui_manager import UIManager
from src.behavior_manager import BehaviorManager
from src.schedule_manager import ScheduleManager
from src.schedule_editor import ScheduleEditorWindow
from src.api_settings_editor import ApiSettingsEditorWindow
from src.color_theme_manager import ColorThemeManager
from src.log_viewer import ConversationLogViewer
from src.memory_manager import MemoryManager
from src.global_voice_engine_manager import GlobalVoiceEngineManager
from src.project_manager import ProjectManager 
from src.character_installer import CharacterInstaller

class RecommendationNotificationDialog(tk.Toplevel):
    """新しい推奨モデルを通知し、ユーザーの選択肢を提示するカスタムダイアログ"""
    def __init__(self, parent, app, recommendations: list):
        super().__init__(parent)
        self.app = app
        self.recommendations = recommendations
        
        self.transient(parent)
        self.grab_set()
        self.title("新しい推奨モデルのお知らせ")
        
        theme = self.app.theme_manager
        self.configure(bg=theme.get('bg_main'))
        
        # --- スタイルの設定 ---
        style = ttk.Style(self)
        style.configure("Dialog.TFrame", background=theme.get('bg_main'))
        style.configure("Dialog.TLabel", background=theme.get('bg_main'), foreground=theme.get('bg_text'), font=app.font_normal)
        style.configure("Dialog.TButton", font=app.font_normal)

        main_frame = ttk.Frame(self, padding=app.padding_large, style="Dialog.TFrame")
        main_frame.pack(expand=True, fill="both")
        
        # --- メッセージの組み立て ---
        message = "新しい、またはより適したモデルが利用可能です。\n設定を変更しますか？\n"
        for rec in self.recommendations:
            message += f"\n・{rec['role']}用モデル:\n　現在: {rec['current']} → 推奨: {rec['new']}"
            
        ttk.Label(main_frame, text=message, style="Dialog.TLabel", justify="left").pack(pady=(0, app.padding_large))
        
        # --- ボタンフレーム ---
        button_frame = ttk.Frame(main_frame, style="Dialog.TFrame")
        button_frame.pack(fill="x", pady=(app.padding_normal, 0))

        btn_ignore = ttk.Button(button_frame, text="この更新を無視", command=self._ignore_and_close, style="Dialog.TButton")
        btn_ignore.pack(side="right", padx=app.padding_normal)

        btn_later = ttk.Button(button_frame, text="後で", command=self.destroy, style="Dialog.TButton")
        btn_later.pack(side="right")
        
        btn_open = ttk.Button(button_frame, text="設定を開く", command=self._open_settings, style="Dialog.TButton")
        btn_open.pack(side="right", padx=app.padding_normal)
        
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_x()+50}+{parent.winfo_y()+50}") # 親ウィンドウの近くに表示
        
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _open_settings(self):
        # メインスレッドから安全に呼び出す
        self.app.root.after(0, self.app.open_api_settings_editor)
        self.destroy()

    def _ignore_and_close(self):
        try:
            config = ConfigParser()
            config.read(self.app.recommendation_log_path, encoding='utf-8')

            if not config.has_section('Ignored'):
                config.add_section('Ignored')

            for rec in self.recommendations:
                # 無視リストには新しい推奨モデル名を記録
                config.set('Ignored', rec['new'], 'True')

            with open(self.app.recommendation_log_path, 'w', encoding='utf-8') as f:
                config.write(f)
            
            print(f"推奨モデル {', '.join([r['new'] for r in self.recommendations])} を無視リストに追加しました。")

        except Exception as e:
            print(f"推奨無視リストの保存に失敗: {e}")
        finally:
            self.destroy()

class DesktopMascot:
    """
    アプリケーション全体を制御するメインクラス。
    UIや自律行動の管理は専門クラスに委譲し、自身は各コンポーネントの統括と
    AIとの対話フローの中心的な制御に責任を持つ。
    """
    MAX_RALLY_COUNT = 3
    API_TIMEOUT_SECONDS = 30
    SCHEDULE_RETRY_MINUTES = 10

    GITHUB_API_URL = "https://api.github.com/repos/makumoru/AI_DesktopMascot_cocococo/releases/latest"
    GITHUB_RELEASES_PAGE_URL = "https://github.com/makumoru/AI_DesktopMascot_cocococo/releases/latest"

    def __init__(self, app_root_dir: str, current_version: str):
        """DesktopMascotを初期化し、アプリケーションの全コンポーネントを準備します。"""
        self.app_root_dir = app_root_dir
        self.current_version = current_version

        self.root = tk.Tk()
        self.root.withdraw() 
        
        self.config = ConfigParser()
        self.config.read('config.ini', encoding='utf-8')

        # GlobalVoiceEngineManagerのインスタンス化
        self.global_voice_engine_manager = GlobalVoiceEngineManager(self.config)

        # ColorThemeManagerをインスタンス化
        self.theme_manager = ColorThemeManager(self.config)
        self.theme_setting_var = tk.StringVar(value=self.config.get('UI', 'theme', fallback=''))

        self.pos_config = ConfigParser()
        self.pos_config_path = 'position.ini'
        self.pos_config.read(self.pos_config_path, encoding='utf-8')

        # 推奨通知の無視リストのパス
        self.recommendation_log_path = 'recommendation_log.ini'

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

        # ProjectManagerは 'characters' フォルダの場所を知るために必要
        self.project_manager = ProjectManager(base_dir=self.app_root_dir)
        # CharacterInstallerのインスタンスを生成
        self.installer = CharacterInstaller(parent=self.root, characters_dir=self.project_manager.characters_dir)

        self._setup_characters()
        if self.is_shutting_down: return

        # --- 起動時に長期記憶の重要度を減衰させる ---
        for char in self.characters:
            if char:
                char.memory_manager.decay_importance()

        self.schedule_manager = ScheduleManager()
        self._setup_services()

        # --- アプリケーションの状態管理変数 ---
        self.is_shutting_down = False
        self.is_ready = False
        self.is_processing_lock = threading.Lock()
        self.last_time_signal_hour = -1
        self.auto_speech_cool_time = self.generate_cool_time()
        self.last_interaction_time = time.time()
        self.is_user_away = False
        self.is_in_rally = False
        self.current_rally_count = 0
        self.prevent_cool_down_reset = False
        # 実行済みスケジュールキーを記録する辞書 {execution_key: execution_time}
        self.executed_schedule_keys = {}
        self.current_app_date = datetime.now().date()
        self.schedule_editor_window = None # スケジュール管理ウィンドウの参照を保持する変数
        self.api_settings_window = None # API設定ウィンドウの参照を保持する変数
        self.log_viewer_windows = {} # キー: character_id, 値: windowインスタンス
        self.executed_schedules_this_minute = []
        self.last_checked_minute = -1
        self._post_speech_callback = None

        self.last_api_request_time = None
        self.current_speaker_on_request = None
        self.capture_targets_cache = []
        self.tray_icon = None
        self.context_menu_target_char = None
        
        self.is_checking_models = threading.Lock()  # モデルチェックが多重実行されるのを防ぐためのロック

        self.ui_manager = UIManager(self)
        self.behavior_manager = BehaviorManager(self)
    
    def _select_speaker_by_frequency(self):
        """
        キャラクターの発話頻度を重みとして、確率的に話し手を一人選びます。
        """
        if not self.characters:
            return None

        # 画面に表示されているキャラクターのみを対象にする
        visible_characters = [c for c in self.characters if c and c.ui.winfo_exists()]
        if not visible_characters:
            return None
        
        if len(visible_characters) == 1:
            return visible_characters[0]
            
        # 各キャラクターの発話頻度を取得
        weights = [char.speech_frequency for char in visible_characters]
        
        # 全員の頻度が0の場合、ランダムに一人選ぶ (完全な沈黙を避ける)
        if all(w == 0 for w in weights):
            return random.choice(visible_characters)

        # 重み付きランダム選択
        # random.choices はリストを返すので、最初の要素を取得する
        selected_char = random.choices(visible_characters, weights=weights, k=1)[0]
        return selected_char

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
        
        # --- 設定変更をconfig.iniに保存するためのコールバックを登録 ---
        self.is_always_on_top.trace_add("write", self._toggle_always_on_top)
        self.is_sound_enabled.trace_add("write", self._toggle_mute)
        self.is_auto_speech_enabled.trace_add("write", lambda *args: self._update_config_file('UI', 'ENABLE_AUTO_SPEECH', self.is_auto_speech_enabled.get()))
        self.is_schedule_enabled.trace_add("write", lambda *args: self._update_config_file('UI', 'ENABLE_SCHEDULES', self.is_schedule_enabled.get()))

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

    def get_character_name_from_dir(self, char_dir_name):
        """
        キャラクターのディレクトリ名から、iniファイルに設定された名前を取得するヘルパーメソッド。
        """
        char_ini_path = os.path.join('characters', char_dir_name, 'character.ini')
        try:
            if os.path.exists(char_ini_path):
                config = ConfigParser()
                config.read(char_ini_path, encoding='utf-8')
                if config.has_section('INFO') and config.has_option('INFO', 'CHARACTER_NAME'):
                    return config.get('INFO', 'CHARACTER_NAME')
        except Exception:
            pass # エラー時はフォールバック
        return char_dir_name # 取得失敗時はディレクトリ名を返す

    def change_character(self, target_char_id, new_char_dir_name):
        """
        キャラクターを交代させる一連のシーケンスを開始します。
        退去挨拶 -> 交代処理 -> 登場挨拶 -> (50%)相方の反応 の順で実行されます。
        """
        if self.is_processing_lock.acquire(blocking=False):
            print(f"キャラクター交代シーケンスを開始します: {target_char_id} -> {new_char_dir_name}")
            
            old_char = self.char1 if target_char_id == '1' else self.char2
            if not old_char:
                print("エラー: 交代対象のキャラクターが見つかりません。")
                if self.is_processing_lock.locked(): self.is_processing_lock.release()
                return

            # --- コールバックチェーンの定義 ---

            # Step 3: (最終処理) ロックを解放してシーケンス完了
            def final_step():
                print("キャラクター交代シーケンス完了。")
                self.reset_cool_time()
                if self.is_processing_lock.locked(): self.is_processing_lock.release()

            # Step 2: 相方の反応
            def react_to_change(new_char, partner_char):
                # 交代後の相方がいて、50%の確率に当選した場合
                if partner_char and random.random() < 0.5:
                    self._post_speech_callback = final_step
                    prompt = f"隣にいた「{old_char.name}」が帰り、代わりに「{new_char.name}」が新しく来ました。この状況について、何か短いコメントをしてください。"
                    self.request_speech(partner_char, prompt, "交代への反応")
                else:
                    final_step() # 反応しない場合は即終了

            # Step 1: 新キャラクターの登場挨拶
            def greet_new_character(new_char, partner_char):
                self._post_speech_callback = lambda: react_to_change(new_char, partner_char)
                prompt = "ユーザーの操作で、交代して新しく登場しました。自己紹介を兼ねた短い挨拶をしてください。"
                self.request_speech(new_char, prompt, "交代挨拶")

            # Step 0: 実際の交代処理と、その後の挨拶トリガー
            def swap_and_greet():
                is_char1 = target_char_id == '1'
                
                # destroy() の前に必要な情報をすべて取得する
                old_char_geometry = old_char.ui.geometry()
                old_char_is_flipped = old_char.is_left_side
                
                # 古いキャラクターを破棄
                self.characters.remove(old_char)
                old_char.destroy()
                if is_char1: self.char1 = None
                else: self.char2 = None


                # 新しいキャラクターを生成
                try:
                    # old_char_is_flipped は True/False なので、そのまま渡す
                    new_char = CharacterController(
                        self.root, self, target_char_id, new_char_dir_name, 
                        old_char_is_flipped, self.config, 'right', # position_sideは一旦仮でOK
                        self.input_history_manager
                    )
                except Exception as e:
                    messagebox.showerror("キャラクター変更エラー", f"'{new_char_dir_name}'の読み込みに失敗しました。\nアプリケーションを終了します。お手数ですが手動で再起動してください。")
                    self.exit_app()
                    return
                
                # UIの位置と状態を確定させる処理を追加
                # 1. まずジオメトリ（位置とサイズ）を設定
                new_char.ui.geometry(old_char_geometry)
                new_char.ui.update_idletasks() # UIの更新を即座に反映させる

                # 2. 最終的な表示を確定させ、その後で挨拶シーケンスを開始する
                def finalize_and_greet():
                    # 2a. 表示を確定（ハートの位置などもここで決まる）
                    new_char.ui.update_info_display()

                    # 2b. アプリケーション内のリストと参照を更新
                    if is_char1:
                        self.char1 = new_char
                        self.characters.insert(0, new_char)
                    else:
                        self.char2 = new_char
                        # 2人目が存在しない場合も考慮してappend
                        if len(self.characters) < 2:
                            self.characters.append(new_char)
                        else:
                            self.characters[1] = new_char # 既存の2人目と入れ替え

                    # 2c. パートナー情報などを再設定
                    if self.is_char2_enabled:
                        if self.char1 and self.char2:
                            self.char1.set_partner(self.char2)
                            self.char2.set_partner(self.char1)
                    else:
                        if self.char1:
                            self.char1.set_partner(None)
                    
                    self._update_app_title()
                    self.screenshot_handler.app_titles = [char.ui.title() for char in self.characters if char]
                    self._update_all_character_maps()

                    # 新しいキャラクターの話者IDを解決する
                    print(f"[{new_char.name}] の話者IDを解決します...")
                    new_char.voice_manager.resolve_speaker_id()

                    # 2d. 挨拶シーケンスの次のステップへ
                    greet_new_character(new_char, new_char.partner)
                
                # after(10)のように少しだけ遅延させることで、UIの描画を確実にする
                self.root.after(10, finalize_and_greet)


            # --- シーケンス開始点 ---
            self._post_speech_callback = swap_and_greet
            new_char_name = self.get_character_name_from_dir(new_char_dir_name)
            farewell_prompt = f"これから「{new_char_name}」さんと交代します。ユーザーに短いお別れの挨拶をしてください。"
            self.request_speech(old_char, farewell_prompt, "退去挨拶")
            
        else:
            # ロック取得失敗時の処理
            print("他の処理が実行中か、アプリが準備中のため、キャラクター変更を中断しました。")
            char_to_notify = self.char1 if self.char1 and self.char1.ui.winfo_exists() else None
            if char_to_notify:
                char_to_notify.ui.output_box.set_text("今は他のことを考えているみたい...")

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
        self.gemini_handler = GeminiAPIHandler(self.config)

        app_titles = [char.ui.title() for char in self.characters]
        self.screenshot_handler = ScreenshotHandler(app_titles)

        character_map = {char.character_id: char.name for char in self.characters if char}
        character_map.update({'USER': 'ユーザー', 'SYSTEM': 'システム'})

    def _log_event_for_all_characters(self, actor_id, target_id, action_type, content):
        """
        現在画面にいる全キャラクターのログファイルにイベントを記録し、
        開いているログビューアーに更新を通知します。
        """
        # 1. 全キャラクターのログファイルに書き込む
        for char in self.characters:
            if char:
                char.log_manager.add_entry(actor_id, target_id, action_type, content)

        # 2. 開かれている全てのログビューアーに更新を通知
        for viewer in self.log_viewer_windows.values():
            if viewer and viewer.winfo_exists():
                # UIの更新はメインスレッドで行う
                self.root.after(0, viewer.update_log_display)

    def _create_tools_config_for_character(self, character):
        """指定されたキャラクターの現在の状態に基づいて、AIのツール設定を動的に生成します。"""
        # 現在の衣装で利用可能な感情の英語名リストを取得
        available_emotions_en = list(character.available_emotions.keys())
        
        function_declarations = [
            {"name": "generate_speech", "description": "キャラクターが話すためのセリフを生成します。", "parameters": {"type": "object", "properties": {"speech_text": {"type": "string", "description": "キャラクターとして発言する、自然で簡潔なセリフ。"}}, "required": ["speech_text"]}},
            {"name": "change_emotion", "description": "生成したセリフの内容に最もふさわしい感情を指定します。", "parameters": {"type": "object", "properties": {"emotion": {"type": "string", "description": "セリフに合わせた感情。", "enum": available_emotions_en}}, "required": ["emotion"]}},
            {
                "name": "change_favorability",
                "description": "ユーザーとの直近のやり取りを評価し、あなたの好感度をどれだけ変化させるかを決定します。ポジティブな内容なら正の数、ネガティブなら負の数を指定します。",
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
            {"name": "change_costume", "description": "キャラクターの衣装を変更します。", "parameters": {"type": "object", "properties": {"costume_id": {"type": "string", "description": "変更したい衣装のID。"}}, "required": ["costume_id"]}},
            {
                "name": "evaluate_and_store_memory",
                "description": "直前の会話を評価し、長期記憶に保存すべきか判断する。ユーザーとの関係を深める重要な情報や、キャラクターの行動に影響を与える事実などが対象となる。単なる挨拶や相槌は保存しないこと。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "is_important": {"type": "boolean", "description": "この会話は長期的に記憶する価値があるか。"},
                        "importance_score": {"type": "integer", "description": "記憶する場合の重要度 (1-100)。数値が高いほど重要。"},
                        "summary": {"type": "string", "description": "記憶すべき内容を、誰が読んでも理解できるように簡潔に要約したテキスト。"}
                    }, "required": ["is_important"]
                }
            },
            {
                "name": "acknowledge_referenced_memories",
                "description": "応答を生成する際に参考にした長期記憶のIDリストを報告する。参考にした記憶がない場合は呼び出さないこと。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_ids": {
                            "type": "array",
                            "items": { "type": "string" },
                            "description": "プロンプトで与えられた長期記憶のうち、今回の応答の参考に利用した記憶エントリのIDのリスト。"
                        }
                    },
                    "required": ["memory_ids"]
                }
            }
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

            print(f"[{self.char2.name}] の話者IDを解決します...")
            self.char2.voice_manager.resolve_speaker_id()

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
        """
        アプリケーションを安全に終了します。
        挨拶の完了を待ち、段階的なタイムアウトでハングを防ぎます。
        """
        if self.is_shutting_down or self.is_processing_lock.locked():
            return
        self.is_shutting_down = True
        print("アプリケーションの終了処理を開始します...")

        # --- ▼▼▼ 修正箇所 ▼▼▼ ---

        # タイムアウトタイマーのIDを保持するためのリスト (クロージャ内で変更するため)
        self.failsafe_timer_id = [None]
        is_final_shutdown_called = False

        def final_shutdown():
            """実際の後片付けとウィンドウ破棄を行う関数。複数回呼ばれるのを防ぐ。"""
            nonlocal is_final_shutdown_called
            if is_final_shutdown_called:
                return
            is_final_shutdown_called = True
            
            # 実行中のタイマーがあればキャンセル
            if self.failsafe_timer_id[0]:
                self.root.after_cancel(self.failsafe_timer_id[0])
                self.failsafe_timer_id[0] = None

            print("最終シャットダウン処理を実行します。")
            self._save_position_config()
            if self.tray_icon:
                self.tray_icon.stop()
            if self.global_voice_engine_manager:
                self.global_voice_engine_manager.shutdown_all()
            self.root.after(200, self.root.destroy)

        # 挨拶が正常に完了した場合のコールバック
        def greeting_complete_callback():
            # 正常完了したので、全てのタイマーをキャンセルして終了処理へ
            if self.failsafe_timer_id[0]:
                self.root.after_cancel(self.failsafe_timer_id[0])
                self.failsafe_timer_id[0] = None
            final_shutdown()

        # 第1段階: API/TTSのハングを検知するタイマー (15秒)
        # このタイマーは、音声再生が始まる前にリセットされる
        self.failsafe_timer_id[0] = self.root.after(15000, final_shutdown)
        
        visible_characters = [c for c in self.characters if c and c.ui.winfo_exists()]
        if visible_characters:
            self._post_speech_callback = greeting_complete_callback
            speaker = random.choice(visible_characters)
            prompt = "アプリケーションを終了します。ユーザーに短いお別れの挨拶をしてください。"
            self.request_speech(speaker, prompt, "終了挨拶")
        else:
            # キャラクターがいない場合は即座に終了
            final_shutdown()
    
    def toggle_visibility(self):
        """キャラクターウィンドウと関連ウィンドウ（ハートなど）の表示/非表示を切り替えます。"""
        if not self.characters: return

        # 最初のキャラクターが表示されているかで現在の状態を判断
        # winfo_viewable() は withdraw() されると 0 (False) を返す
        is_visible = self.characters[0].ui.winfo_viewable()

        for char in self.characters:
            if char and char.ui.winfo_exists():  # キャラクターが存在し、UIが破棄されていないことを確認
                if is_visible:
                    # --- 非表示処理 ---
                    char.ui.withdraw()
                    # ハートウィンドウも非表示にする
                    if char.ui.heart_window.winfo_exists():
                        char.ui.heart_window.withdraw()
                else:
                    # --- 再表示処理 ---
                    char.ui.deiconify()
                    # ハートウィンドウも再表示する (表示可能な場合のみ)
                    if char.ui.heart_window.winfo_exists() and char.get_current_heart_image_filename():
                        char.ui.heart_window.deiconify()
        
        # 再表示した場合、全員を最前面に持ってくる
        if not is_visible:
            self.bring_all_to_front()
    
    def bring_to_front(self, target_char=None):
        """指定されたキャラクターを最前面に移動させる。"""
        if target_char is None: target_char = self.context_menu_target_char
        if target_char and not self.is_always_on_top.get():
            self.root.after(0, self._bring_ui_to_front, target_char.ui)

    def bring_all_to_front(self):
        """
        全てのキャラクターウィンドウと関連ウィンドウ（ハートなど）をペアで最前面に表示します。
        """
        if self.is_always_on_top.get():
            return # 常に手前に表示モードでは不要

        # 表示順を統一するため、まずキャラクター1からリフトする
        if self.char1 and self.char1.ui.winfo_exists():
            self.char1.ui.lift_with_heart()
        if self.char2 and self.char2.ui.winfo_exists():
            self.char2.ui.lift_with_heart()

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

    def _on_voice_engines_ready(self):
        """
        全音声エンジンの準備完了通知を受け取り、各キャラクターの話者ID解決を指示する。
        """
        print("音声エンジンの準備完了通知を受け取りました。キャラクターの話者IDを解決します。")
        for char in self.characters:
            if char and char.voice_manager:
                # UIスレッドから安全に呼び出すために after を使用
                self.root.after(0, char.voice_manager.resolve_speaker_id)
        
        # 準備がすべて整ったので、起動挨拶を実行
        # afterで少し遅延させることで、ID解決処理が先に行われることを期待する
        self.root.after(100, self.greet_on_startup)

    def check_for_updates_async(self):
        """
        アプリケーションの更新を別スレッドで確認します。
        UIが固まるのを防ぎます。
        """
        print("最新バージョンのバックグラウンドチェックを開始します...")
        thread = threading.Thread(target=self._check_updates_worker, daemon=True)
        thread.start()

    def _check_updates_worker(self):
        """
        【ワーカースレッド】GitHub APIにアクセスして最新リリース情報を取得し、
        バージョンを比較する処理の本体。
        """
        try:
            # タイムアウトを10秒に設定
            with urllib.request.urlopen(self.GITHUB_API_URL, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    latest_tag = data.get('tag_name')
                    
                    if latest_tag:
                        print(f"ローカルバージョン: {self.current_version}, 最新リリースバージョン: {latest_tag}")
                        is_new_version_available = self._compare_versions(self.current_version, latest_tag)
                        
                        if is_new_version_available:
                            # UIの更新はメインスレッドで行う
                            self.root.after(0, self._show_update_notification, latest_tag)
                else:
                    print(f"GitHub APIからの応答が不正です。ステータスコード: {response.status}")

        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"ネットワークエラー: 更新の確認に失敗しました。 {e}")
        except Exception as e:
            print(f"更新チェック中に予期せぬエラーが発生しました: {e}")

    def _compare_versions(self, local_ver_str: str, remote_ver_str: str) -> bool:
        """
        'ver1.4.1' のような形式のバージョン文字列を比較します。
        リモート(GitHub)のバージョンが新しければ True を返します。
        """
        try:
            # 'ver' や 'ver.' のプレフィックスを削除
            local_cleaned = re.sub(r'^ver\.?', '', local_ver_str.lower())
            remote_cleaned = re.sub(r'^ver\.?', '', remote_ver_str.lower())
            
            # '.'で分割し、数値のリストに変換
            local_parts = [int(p) for p in local_cleaned.split('.')]
            remote_parts = [int(p) for p in remote_cleaned.split('.')]

            # 各部分を比較
            for i in range(min(len(local_parts), len(remote_parts))):
                if remote_parts[i] > local_parts[i]:
                    return True
                if remote_parts[i] < local_parts[i]:
                    return False
            
            # 1.4 と 1.4.1 のように、共通部分が同じ場合は、部分が多い方が新しい
            if len(remote_parts) > len(local_parts):
                return True

        except (ValueError, TypeError):
            # 数値に変換できないなど、予期せぬ形式の場合は比較を中止
            return False

        return False

    def _show_update_notification(self, latest_version: str):
        """
        【UIスレッド】新しいバージョンが利用可能なことをユーザーに通知するダイアログを表示します。
        """
        message = (
            f"新しいバージョン ({latest_version}) が利用可能です。\n"
            f"現在のバージョンは {self.current_version} です。\n\n"
            "ダウンロードページを開きますか？"
        )
        
        # どのキャラクターが表示されていても、そのウィンドウを親としてダイアログを出す
        parent_window = self._get_visible_parent_window()

        if messagebox.askyesno("新しいアップデートがあります", message, parent=parent_window):
            webbrowser.open_new_tab(self.GITHUB_RELEASES_PAGE_URL)

    def startup_sequence(self):
        """
        起動時に実行される一連の初期化処理。
        UIの初期配置を最優先で行い、時間のかかる処理はバックグラウンドで続行します。
        """
        # 1. UIの初期配置（即時実行）
        self.root.after(0, self._apply_initial_settings)

        # 2. 起動後すぐに初回のモデルチェックと更新チェックを開始
        self.check_model_validity_and_recommendations_async()
        self.check_for_updates_async()

        # 3. 音声エンジンの初期化をバックグラウンドで開始
        #    完了したら _on_voice_engines_ready メソッドが呼ばれる
        self.global_voice_engine_manager.initialize_engines_and_cache_speakers(
            on_complete_callback=self._on_voice_engines_ready
        )
        
        # 4. UIの描画が安定するまで少し待つ
        time.sleep(1) 
        self.is_ready = True
        
        # 5. 自律行動監視を開始
        self.behavior_manager.start()
        
    def _apply_initial_settings(self):
        """起動時にconfigから読み込んだ設定をUIに適用します。"""
        self._toggle_always_on_top()
        self._toggle_mute()

        # 全キャラクターの初期位置を確定させる
        for char in self.characters:
            if char and char.ui.winfo_exists():
                char.ui.finalize_initial_position()

    def _update_config_file(self, section: str, key: str, value):
        """config.iniの指定されたキーの値をコメントを保持しながら更新します。"""
        # メモリ上のConfigParserオブジェクトも更新
        self.config.set(section, key, str(value))
        
        config_path = 'config.ini'
        try:
            with open(config_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()

            new_lines = []
            current_section = ""
            key_found = False
            
            for line in lines:
                stripped_line = line.strip()
                if stripped_line.startswith('[') and stripped_line.endswith(']'):
                    current_section = stripped_line[1:-1]
                
                # 対象セクション内で、キーが完全に一致する場合のみ置換
                if current_section == section:
                    parts = stripped_line.split('=', 1)
                    if len(parts) == 2 and parts[0].strip().lower() == key.lower():
                        indentation = line[:line.lower().find(key.lower())]
                        new_lines.append(f"{indentation}{key} = {value}\n")
                        key_found = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            
            if not key_found:
                # このケースは今回は起こらない想定だが、念のため
                 print(f"警告: config.iniに [{section}]{key} が見つからなかったため、更新できませんでした。")
                 return

            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            print(f"config.iniを更新しました: [{section}] {key} = {value}")

        except Exception as e:
            messagebox.showerror("設定保存エラー", f"config.iniの保存中にエラーが発生しました:\n{e}")

    def _toggle_always_on_top(self, *args):
        new_state = self.is_always_on_top.get()
        for char in self.characters:
            if char and char.ui.winfo_exists():
                char.ui.wm_attributes("-topmost", new_state)
                # ハートウィンドウにも適用
                if char.ui.heart_window.winfo_exists():
                    char.ui.heart_window.wm_attributes("-topmost", new_state)
        # config.iniを更新
        self._update_config_file('UI', 'ALWAYS_ON_TOP', new_state)

    def _toggle_mute(self, *args):
        """ミュート状態が変更された際に、全キャラクターに伝達し、設定を保存する"""
        is_muted = not self.is_sound_enabled.get()
        print(f"グローバルミュート設定が変更されました。Muted: {is_muted}")
        for char in self.characters:
            if char and hasattr(char, 'voice_manager'):
                char.voice_manager.set_mute_state(is_muted)
        # config.iniを更新
        self._update_config_file('UI', 'ENABLE_SOUND', self.is_sound_enabled.get())
        
    def _find_current_cool_time_preset(self):
        """現在のクールタイム設定に一致するプリセットのラベルを返します。"""
        for label, (min_val, max_val) in self.cool_time_presets.items():
            if self.cool_time_min == min_val and self.cool_time_max == max_val:
                return label
        return f"カスタム ({self.cool_time_min}～{self.cool_time_max}秒)"

    def _set_cool_time(self, label):
        """選択されたプリセットに応じてクールタイム設定を更新し、設定を保存します。"""
        if label in self.cool_time_presets:
            min_val, max_val = self.cool_time_presets[label]
            self.cool_time_min, self.cool_time_max = min_val, max_val
            self.reset_cool_time()
            # config.iniを更新
            self._update_config_file('UI', 'COOL_TIME_MIN_SECONDS', min_val)
            self._update_config_file('UI', 'COOL_TIME_MAX_SECONDS', max_val)

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
        target_emotion_jp = speaker.available_emotions.get('normal', 'normal')
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
            elif call['name'] == 'evaluate_and_store_memory':
                if call['args'].get('is_important'):
                    score = call['args'].get('importance_score')
                    summary = call['args'].get('summary')
                    if score is not None and summary:
                        try: speaker.memory_manager.add_entry(summary, int(score))
                        except (ValueError, TypeError): print(f"警告: Geminiから不正な長期記憶データが返されました: {call['args']}")
            elif call['name'] == 'acknowledge_referenced_memories':
                # .get()で取得しただけでは特殊なオブジェクトの場合がある
                raw_memory_ids = call['args'].get('memory_ids')
                print(raw_memory_ids)
                # オブジェクトが存在し、空でないことを確認してからlistに変換する
                if raw_memory_ids:
                    try:
                        # list()でPythonネイティブのリストに変換
                        memory_ids_list = list(raw_memory_ids)
                        # リスト内の要素が文字列であることも念のため確認
                        if all(isinstance(item, str) for item in memory_ids_list):
                            speaker.memory_manager.update_access_times(memory_ids_list)
                        else:
                            print(f"警告: memory_ids のリスト内に文字列でない要素が含まれています: {memory_ids_list}")
                    except TypeError:
                        # list()で変換できないような予期せぬ型だった場合のフォールバック
                        print(f"警告: memory_ids をリストに変換できませんでした: {raw_memory_ids}")

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
        wav_data = speaker.voice_manager.generate_wav(
            filtered_text,
            target_emotion_jp,
            character_volume_percent=speaker.volume
        )
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
        
        # 終了シーケンス中にこの関数が呼ばれた場合、API/TTS処理が成功したことを意味する
        if self.is_shutting_down:
            print("終了シーケンス中に音声データ生成を確認。再生待機タイマーをリセットします。")
            # 第1段階タイマーをキャンセル
            if self.failsafe_timer_id[0]:
                self.root.after_cancel(self.failsafe_timer_id[0])
            
            # 第2段階: 音声再生の完了を待つための、より長いタイマーを設定 (30秒)
            # これにより、長いセリフの再生が途中で打ち切られるのを防ぐ
            self.failsafe_timer_id[0] = self.root.after(30000, self._post_speech_callback)

        if self.is_shutting_down and self._post_speech_callback is None: return
        
        if not self.is_always_on_top.get():
             self.bring_all_to_front()

        speaker.ui.output_box.set_text(text or "...")
        speaker.ui.emotion_handler.update_image(emotion_jp)
        for char in self.characters:
            if char is not speaker: char.ui.emotion_handler.stop_lip_sync()

        def on_finish_callback():
            # 1. 特別なコールバックが設定されていれば、それを最優先で実行
            if callback := self._post_speech_callback:
                self._post_speech_callback = None  # 一度実行したらクリア
                callback()
                return # 特別なコールバック実行後は、以降の通常処理は行わない

            # 2. 通常のラリー処理
            if self.is_char2_enabled and pass_turn:
                self.is_in_rally, self.current_rally_count = True, self.current_rally_count + 1
                prompt_for_partner = f"「{text}」"
                self.request_speech(speaker.partner, prompt_for_partner, "ラリー", situation="相方からの返答要求")
            else:
                # 3. 通常の終了処理 (ラリーでも特別なコールバックでもない場合)
                self.is_in_rally = False
                speaker.ui.emotion_handler.stop_lip_sync()
                for char in self.characters:
                    if char is not speaker: char.ui.output_box.set_text("...")
                
                if self.prevent_cool_down_reset:
                    self.prevent_cool_down_reset = False
                elif self.current_rally_count > 0:
                    self.set_extended_cool_time_after_rally()
                else:
                    self.reset_cool_time()
                
                self.current_rally_count = 0
                if self.is_processing_lock.locked():
                    self.is_processing_lock.release()

        if wav_data:
            def on_start_callback(): self.root.after(0, speaker.ui.emotion_handler.start_lip_sync, emotion_jp)
            speaker.voice_manager.play_wav(wav_data, on_start=on_start_callback, on_finish=on_finish_callback)
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
            speaker = self._select_speaker_by_frequency()
            if not speaker: # 話し手が見つからなかった場合
                if self.is_processing_lock.locked(): self.is_processing_lock.release()
                return

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
        if self.api_settings_window and self.api_settings_window.winfo_exists():
            self.api_settings_window.lift()
            return
        
        # 呼び出し元（右クリック or システム通知）に応じて基準となるキャラクターを選択
        # 右クリック経由ならそのキャラクター、そうでなければキャラクター1を基準にする
        char_for_dialog = self.context_menu_target_char or self.char1
        
        # 基準キャラクターが存在し、UIがあることを確認
        if not char_for_dialog or not char_for_dialog.ui.winfo_exists():
            parent_window = self.root # 最悪の場合のフォールバック
        else:
            parent_window = char_for_dialog.ui
        
        # 基準キャラクターを渡してウィンドウを生成
        self.api_settings_window = ApiSettingsEditorWindow(char_for_dialog, parent_window, self)

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

    def open_conversation_log_viewer(self, target_char):
        """
        指定されたキャラクターの会話ログ閲覧ウィンドウを開きます。
        """
        if not target_char:
            return

        char_id = target_char.original_id
        
        # 既にウィンドウが開いている場合は、新しく開かずに最前面に表示する
        if char_id in self.log_viewer_windows and self.log_viewer_windows[char_id].winfo_exists():
            self.log_viewer_windows[char_id].lift()
            return
        
        # 新しいウィンドウを生成
        parent_window = target_char.ui if target_char.ui.winfo_exists() else self.root
        
        # 新しいConversationLogViewerを生成し、参照を辞書に保存
        viewer = ConversationLogViewer(parent_window, self, target_char)
        self.log_viewer_windows[char_id] = viewer


    def check_api_timeout(self):
        """APIリクエストのタイムアウトを監視します。"""
        if self.current_speaker_on_request and self.last_api_request_time:
            if time.time() - self.last_api_request_time > self.API_TIMEOUT_SECONDS:
                speaker = self.current_speaker_on_request
                self.current_speaker_on_request, self.last_api_request_time = None, None
                if self.is_processing_lock.locked(): self.is_processing_lock.release()
                
                error_text = speaker.msg_on_api_timeout
                emotion_jp = speaker.available_emotions.get('troubled', 'normal')

                wav_data = self.voicevox_manager.generate_wav(
                    error_text, 
                    speaker.speaker_id, 
                    emotion_jp, 
                    speaker.voice_params,
                    character_volume_percent=speaker.volume # speaker.volumeを渡す
                )
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

        # メッセージタイプに応じて使用するモデルを切り替えるマップ
        model_key_map = {
            "応答": 'pro' if self.is_pro_mode.get() else 'flash',
            "タッチ反応": 'flash-2',
            "衣装変更反応": 'flash-2',
            "スケジュール通知": 'flash',
            "今日の予定通知": 'flash',
            "起動挨拶": 'flash-2',
            "退去挨拶": 'flash-2',
            "交代挨拶": 'flash-2',
            "交代への反応": 'flash-2',
            "終了挨拶": 'flash-2'
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
            
            # 5. グローバルな音声エンジン設定を再読み込み
            # GlobalManagerに新しいconfigを渡す
            self.global_voice_engine_manager.global_config = self.config
            
            # 6. 各キャラクターに設定再読み込みを指示 (こちらが正しい処理)
            for char in self.characters:
                if char:
                    char.reload_config_and_services()

            # 7. UIの表示を更新
            self.ui_manager.update_api_status_menu()
            
            print("設定の再読み込みが完了しました。")
            
            # 8. ユーザーにフィードバックを返す
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
        
        # 1. config.ini の設定値を更新
        self._update_config_file('UI', 'theme', theme_name)
            
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
            
        # 4. ログビューアーが開いていれば、そちらも更新
        for viewer in self.log_viewer_windows.values():
            if viewer and viewer.winfo_exists():
                viewer.reload_theme()

        print("UIテーマの再読み込みが完了しました。")

    def check_model_validity_and_recommendations_async(self):
        """モデルの有効性と推奨をチェックする処理を非同期で開始します。"""
        # 既にチェックが実行中であれば、何もしない
        if not self.is_checking_models.acquire(blocking=False):
            print("モデルチェックは既に実行中のため、スキップします。")
            return
        
        print("モデルの有効性と推奨のバックグラウンドチェックを開始します...")
        thread = threading.Thread(target=self._check_models_worker, daemon=True)
        thread.start()

    def _check_models_worker(self):
        """【ワーカースレッド】モデルのチェック処理本体。"""
        try:
            # --- 1. 準備 ---
            # APIキーと現在の設定を取得
            self.config.read('config.ini', encoding='utf-8-sig')
            api_key = self.config.get('GEMINI', 'GEMINI_API_KEY', fallback=None)
            
            # APIから最新のモデルリストを取得
            result = GeminiAPIHandler.list_available_models(api_key)
            status = result.get('status')

            # --- 1a. API呼び出し自体のエラーハンドリング ---
            if status == 'auth_error':
                self.root.after(0, self._show_auth_error_dialog)
                return # チェック処理を中断
            if status == 'connection_error':
                self.root.after(0, self._show_connection_error_dialog)
                return # チェック処理を中断
            if status != 'success':
                # その他の予期せぬエラー
                print(f"モデルリスト取得で不明なエラー: {result.get('error_message')}")
                return

            # --- 1b. 成功した場合の処理 ---
            models_data = result.get('models', {})
            available_gemini = models_data.get('gemini', [])
            available_gemma = models_data.get('gemma', [])

            current_settings = {
                "PRO_MODEL_NAME": self.config.get('GEMINI', 'PRO_MODEL_NAME'),
                "FLASH_MODEL_NAME": self.config.get('GEMINI', 'FLASH_MODEL_NAME'),
                "FLASH_LITE_MODEL_NAME": self.config.get('GEMINI', 'FLASH_LITE_MODEL_NAME'),
                "FLASH_2_MODEL_NAME": self.config.get('GEMINI', 'FLASH_2_MODEL_NAME'),
                "FLASH_LITE_2_MODEL_NAME": self.config.get('GEMINI', 'FLASH_LITE_2_MODEL_NAME'),
                "GEMMA_MODEL_NAME": self.config.get('GEMMA', 'GEMMA_MODEL_NAME'),
            }
            
            ignored_config = ConfigParser()
            ignored_config.read(self.recommendation_log_path, encoding='utf-8')
            ignored_list = ignored_config.options('Ignored') if ignored_config.has_section('Ignored') else []

            # --- 2. 無効なモデルのチェック ---
            invalid_models = []
            for key, model_name in current_settings.items():
                is_gemini = (key != "GEMMA_MODEL_NAME")
                valid_list = available_gemini if is_gemini else available_gemma
                if model_name and model_name not in valid_list:
                    invalid_models.append(model_name)
            
            # --- 3. 新しい推奨モデルのチェック ---
            recommendations = {
                "PRO_MODEL_NAME": ("思考モード", GeminiAPIHandler.recommend_pro_model(available_gemini)),
                "FLASH_MODEL_NAME": ("基本モデル", GeminiAPIHandler.recommend_flash_model(available_gemini)),
                "FLASH_LITE_MODEL_NAME": ("基本(予備)", GeminiAPIHandler.recommend_flash_lite_model(available_gemini)),
                "FLASH_2_MODEL_NAME": ("旧モデル", GeminiAPIHandler.recommend_legacy_flash_model(available_gemini)),
                "FLASH_LITE_2_MODEL_NAME": ("旧(予備)", GeminiAPIHandler.recommend_legacy_flash_lite_model(available_gemini)),
                "GEMMA_MODEL_NAME": ("Gemmaモデル", GeminiAPIHandler.recommend_gemma_model(available_gemma)),
            }
            
            new_recommendations = []
            for key, (role, recommended_model) in recommendations.items():
                current_model = current_settings.get(key)
                # 推奨があり、現在と異なり、無視リストにない場合
                if recommended_model and current_model != recommended_model and recommended_model not in ignored_list:
                    new_recommendations.append({
                        "role": role, "current": current_model, "new": recommended_model
                    })

            # --- 4. 結果をUIスレッドに渡す ---
            if invalid_models or new_recommendations:
                self.root.after(0, self._show_model_check_results, invalid_models, new_recommendations)

        except Exception as e:
            print(f"モデルチェック中にエラーが発生: {e}")
        finally:
            # 最後に必ずロックを解放する
            self.is_checking_models.release()
            print("モデルチェックを完了しました。")

    def _get_visible_parent_window(self):
        """メッセージボックスの親として適切な、現在表示中のウィンドウを返す。"""
        # 右クリックメニューの対象キャラクターがいれば、それを最優先
        if self.context_menu_target_char and self.context_menu_target_char.ui.winfo_viewable():
            return self.context_menu_target_char.ui
        # 表示されているキャラクターを探す
        for char in self.characters:
            if char and char.ui.winfo_viewable():
                return char.ui
        # どのキャラクターも表示されていなければ、ルートウィンドウを返す
        return self.root

    def _show_model_check_results(self, invalid_models, new_recommendations):
        """【UIスレッド】チェック結果をメッセージボックスで通知する。"""
        parent_window = self._get_visible_parent_window()
        
        # 優先度の高い「無効モデル」の通知を先に行う
        if invalid_models:
            # 重複を除外して表示
            unique_invalid = sorted(list(set(invalid_models)))
            message = (f"現在設定されているモデルの一部が利用できませんでした。\n"
                       f"機能が正常に動作しない可能性があります。\n\n"
                       f"無効なモデル:\n・" + "\n・".join(unique_invalid) +
                       f"\n\nOKを押すと設定画面を開きます。")
            
            # メッセージボックスを表示
            messagebox.showerror("モデル設定エラー", message, parent=parent_window)
            
            # メッセージボックスを閉じた後、API設定画面を自動で開く
            self.open_api_settings_editor()
            
            # 無効なモデルがある場合は、推奨通知は次回に回す
            return

        if new_recommendations:
            # カスタムダイアログを開く
            RecommendationNotificationDialog(parent_window, self, new_recommendations)

    def _show_auth_error_dialog(self):
        """【UIスレッド】APIキー不良のエラーダイアログを表示する"""
        parent_window = self._get_visible_parent_window()
        messagebox.showerror(
            "API認証エラー",
            "APIキーが無効か、アクセス権限がないためモデルリストを取得できませんでした。\n"
            "APIキーが正しいか確認してください。\n\n"
            "OKを押すと設定画面を開きます。",
            parent=parent_window
        )
        self.open_api_settings_editor()

    def _show_connection_error_dialog(self):
        """【UIスレッド】接続不良のエラーダイアログを表示する"""
        parent_window = self._get_visible_parent_window()
        should_retry = messagebox.askretrycancel(
            "API接続エラー",
            "モデルリストの取得中に接続エラーが発生しました。\n"
            "インターネット接続を確認するか、しばらく待ってから再試行してください。",
            parent=parent_window
        )
        if should_retry:
            # 5秒後に再試行
            self.root.after(5000, self.check_model_validity_and_recommendations_async)
        else:
            self.exit_app()

    def install_character_from_zip(self, zip_path: str):
        """
        UIからドロップされたZIPファイルをCharacterInstallerに渡してインストール処理を実行する。
        """
        print(f"UIへのドロップを検知。インストール処理を開始します: {zip_path}")
        
        # 実際の処理はインストーラーにすべて委譲
        self.installer.install_from_zip(zip_path)
        
        # ユーザーへのフィードバック
        # インストーラーが成功/失敗メッセージを出すので、ここでは完了後の案内のみ
        # ただし、インストーラーが何らかの理由でメッセージを出せなかった場合を考慮
        if not self.installer.parent.winfo_exists(): # インストーラーの親(root)が健在か
             messagebox.showinfo(
                 "キャラクター追加",
                 "キャラクターファイルの展開が完了しました。\n"
                 "右クリックメニューの「キャラクター追加/変更」から選択してください。",
                 parent=self._get_visible_parent_window()
             )
