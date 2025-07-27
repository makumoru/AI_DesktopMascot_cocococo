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
from datetime import datetime

# --- 自作モジュールのインポート ---
from src.log_manager import ConversationLogManager
from src.character_controller import CharacterController
from src.voicevox_player import VoicevoxManager
from src.gemini_api_handler import GeminiAPIHandler
from src.screenshot_handler import ScreenshotHandler
from src.ui_manager import UIManager
from src.behavior_manager import BehaviorManager

class DesktopMascot:
    """
    アプリケーション全体を制御するメインクラス。
    UIや自律行動の管理は専門クラスに委譲し、自身は各コンポーネントの統括と
    AIとの対話フローの中心的な制御に責任を持つ。
    """
    MAX_RALLY_COUNT = 3
    API_TIMEOUT_SECONDS = 30

    def __init__(self, app_root_dir: str):
        """DesktopMascotを初期化し、アプリケーションの全コンポーネントを準備します。"""
        self.app_root_dir = app_root_dir
        
        self.root = tk.Tk()
        self.root.withdraw() 
        
        self.config = ConfigParser()
        self.config.read('config.ini', encoding='utf-8')
        
        self._load_config_values()

        self._setup_characters()
        if self.is_shutting_down: return

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
        self.is_sound_enabled = tk.BooleanVar(value=self.config.getboolean('UI', 'ENABLE_SOUND', fallback=True))
        
        self.cool_time_presets = {
            "短い (30～90秒)": (30, 90), "普通 (90～300秒)": (90, 300),
            "長い (300～900秒)": (300, 900), "無口 (900～1800秒)": (900, 1800)
        }
        self.cool_time_setting_var = tk.StringVar(value=self._find_current_cool_time_preset())
        self.selected_capture_target_key = tk.StringVar() 
        
        self.is_always_on_top.trace_add("write", self._toggle_always_on_top)
        self.is_sound_enabled.trace_add("write", self._toggle_mute)

    def _setup_characters(self):
        """キャラクターのインスタンスを生成し、連携を設定します。"""
        self.characters = []
        self.char1, self.char2 = None, None
        self.is_shutting_down = False

        try:
            directory = self.config.get('CHARACTER_1', 'DIRECTORY')
            is_left = self.config.getboolean('CHARACTER_1', 'IS_LEFT_SIDE', fallback=False)
            self.char1 = CharacterController(self.root, self, "1", directory, is_left, self.config)
            self.characters.append(self.char1)
        except (NoSectionError, NoOptionError, FileNotFoundError) as e:
            messagebox.showerror("起動エラー", f"キャラクター1の読み込みに失敗しました。\n詳細: {e}")
            self.is_shutting_down = True
            self.root.destroy()
            return
            
        self.is_char2_enabled = self.config.getboolean('CHARACTER_2', 'ENABLED', fallback=False)
        if self.is_char2_enabled:
            try:
                directory = self.config.get('CHARACTER_2', 'DIRECTORY')
                is_left = self.config.getboolean('CHARACTER_2', 'IS_LEFT_SIDE', fallback=True)
                self.char2 = CharacterController(self.root, self, "2", directory, is_left, self.config)
                self.characters.append(self.char2)
            except (NoSectionError, NoOptionError, FileNotFoundError) as e:
                self.is_char2_enabled = False
                print(f"情報: キャラクター2は読み込みませんでした。1人モードで起動します。\n詳細: {e}")

        if self.char1 and self.char2:
            self.char1.set_partner(self.char2); self.char2.set_partner(self.char1)
        elif self.char1:
            self.char1.set_partner(None)
        
        # アプリケーション名を定義
        app_name = "ここここ"
        
        # メインの非表示ウィンドウにもタイトルを設定
        self.root.title(app_name)
        
        # 各キャラクターのウィンドウにタイトルを設定
        for char in self.characters:
            # 例: 「ここここ - ジェミー」のように表示されます
            char.ui.title(f"{app_name} - {char.name}")

    def _setup_services(self):
        """共有サービス（音声、API、ログ等）を初期化します。"""
        self.voicevox_manager = VoicevoxManager(self.config)
        self.gemini_handler = GeminiAPIHandler(self.config)

        app_titles = [char.ui.title() for char in self.characters]
        self.screenshot_handler = ScreenshotHandler(app_titles)

        character_map = {char.character_id: char.name for char in self.characters}
        character_map.update({'USER': 'ユーザー', 'SYSTEM': 'システム'})
        self.log_manager = ConversationLogManager('logs', character_map)
        
    def _create_tools_config_for_character(self, character):
        """指定されたキャラクターの現在の状態に基づいて、AIのツール設定を動的に生成します。"""
        # 現在の衣装で利用可能な感情の英語名リストを取得
        available_emotions_en = list(character.available_emotions.keys())
        
        function_declarations = [
            {"name": "generate_speech", "description": "キャラクターが話すためのセリフを生成します。", "parameters": {"type": "object", "properties": {"speech_text": {"type": "string", "description": "キャラクターとして発言する、自然で簡潔なセリフ。"}}, "required": ["speech_text"]}},
            {"name": "change_emotion", "description": "生成したセリフの内容に最もふさわしい感情を指定します。", "parameters": {"type": "object", "properties": {"emotion": {"type": "string", "description": "セリフに合わせた感情。", "enum": available_emotions_en}}, "required": ["emotion"]}},
            {"name": "change_costume", "description": "キャラクターの衣装を変更します。", "parameters": {"type": "object", "properties": {"costume_id": {"type": "string", "description": "変更したい衣装のID。"}}, "required": ["costume_id"]}}
        ]
        if self.is_char2_enabled:
            function_declarations.append({"name": "pass_turn_to_partner", "description": "相方との会話を続けるかどうかの意思表示をします。", "parameters": {"type": "object", "properties": {"continue_rally": {"type": "boolean", "description": "会話を続ける場合はTrue, 続けない場合はFalse。"}}, "required": ["continue_rally"]}})
        
        return [{"function_declarations": function_declarations}]

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

    def restart_app(self):
        """アプリケーションを安全に再起動します。"""
        if self.is_shutting_down: return
        self.is_shutting_down = True
        if self.tray_icon: self.tray_icon.stop()
        self._shutdown_services()
        self.root.after(100, lambda: os.execl(sys.executable, sys.executable, *sys.argv))

    def exit_app(self):
        """アプリケーションを安全に終了します。"""
        if self.is_shutting_down: return
        self.is_shutting_down = True
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

    def clear_conversation_log(self):
        """会話ログをクリアします。"""
        self.log_manager.clear_log()
        char = random.choice(self.characters)
        char.ui.output_box.set_text("（記憶をリセットしたよ）")
    
    def show_context_menu(self, event):
        """右クリックイベントをUIManagerに中継します。"""
        self.ui_manager.show_context_menu(event)

    def startup_sequence(self):
        """起動時に実行される一連の初期化処理。"""
        if not self.voicevox_manager.ensure_engine_running():
            print("VOICEVOXの起動に失敗。音声なしで続行します。")
        time.sleep(1) 
        self.is_ready = True
        
        self.root.after(0, self._apply_initial_settings)
        self.greet_on_startup()
        self.behavior_manager.start()
        
    def _apply_initial_settings(self):
        """起動時にconfigから読み込んだ設定をUIに適用します。"""
        self._toggle_always_on_top()
        self._toggle_mute()

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
        
        for call in detected_function_calls:
            if call['name'] == 'generate_speech': speech_text = call['args'].get('speech_text', '')
            elif call['name'] == 'change_emotion': 
                emotion_en = call['args'].get('emotion', 'normal').lower()
                target_emotion_jp = speaker.available_emotions.get(emotion_en, target_emotion_jp)
            elif call['name'] == 'pass_turn_to_partner': pass_turn = call['args'].get('continue_rally', False)
            elif call['name'] == 'change_costume':
                if costume_id := call['args'].get('costume_id'):
                     self.root.after(0, speaker.change_costume, costume_id, False)

        filtered_text = self._filter_ai_response(speech_text)
        if not filtered_text:
            is_costume_change_only = any(call['name'] == 'change_costume' for call in detected_function_calls) and not speech_text
            if is_costume_change_only:
                if self.is_processing_lock.locked(): self.is_processing_lock.release()
                return
            filtered_text = "うーん、うまく言葉が出てきません。"
            target_emotion_jp = speaker.available_emotions.get('troubled', speaker.available_emotions.get('normal', 'normal'))
            pass_turn = False
        
        target_id_for_log = speaker.partner.character_id if pass_turn and self.is_char2_enabled else 'USER'
        self.log_manager.add_entry(speaker.character_id, target_id_for_log, 'SPEECH', filtered_text)

        if self.current_rally_count >= self.MAX_RALLY_COUNT: pass_turn = False

        # change_emotionの指定がない場合、Gemmaで感情を分析して補完する
        if target_emotion_jp == speaker.available_emotions.get('normal', 'normal'):
             emotion_percentages = speaker.gemma_api.analyze_emotion(self.log_manager.get_formatted_log())
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
        if self.is_shutting_down: return
        
        if not self.is_always_on_top.get():
             speaker.ui.wm_attributes("-topmost", True); speaker.ui.wm_attributes("-topmost", False)

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
            is_first_time = not os.path.exists(self.log_manager.log_file_path)
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

    def trigger_auto_speech(self):
        """BehaviorManagerからのトリガーで自動発話を実行します。"""
        with self.is_processing_lock:
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
            
    def trigger_time_signal(self):
        """BehaviorManagerからのトリガーで時報を実行します。"""
        with self.is_processing_lock:
            self.prevent_cool_down_reset = True
            if self.is_char2_enabled:
                self.is_in_rally, self.current_rally_count = True, 1
            
            speaker = random.choice(self.characters)
            hour = time.localtime().tm_hour
            self.last_time_signal_hour = hour
            
            prompt = f"システムからの時報要求です。現在の時刻は{hour}時です。時報をあなたの口調で発言し、その時間帯に合ったコメントをしてください。"
            if self.is_char2_enabled:
                prompt += "もし相方にも話しかけたければ、ターンを渡してください(continue_rally=True)。"
            
            self.log_manager.add_entry('SYSTEM', 'ALL', 'INFO', f"{hour}時の時報です。")
            self.request_speech(speaker, prompt, "時報")

    def check_api_timeout(self):
        """APIリクエストのタイムアウトを監視します。"""
        if self.current_speaker_on_request and self.last_api_request_time:
            if time.time() - self.last_api_request_time > self.API_TIMEOUT_SECONDS:
                speaker = self.current_speaker_on_request
                self.current_speaker_on_request, self.last_api_request_time = None, None
                if self.is_processing_lock.locked(): self.is_processing_lock.release()
                
                error_text = "考えるのに時間がかかりすぎているみたいです…。ネットワークやAPIキーの設定を確認してみてください。"
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
        costume_prompt = (f"【あなたの現在の状態】\n"
                          f"- 現在の衣装: 「{costume_info['name']}」(id: {speaker.current_costume_id})\n"
                          f"- 利用可能な衣装リスト: [{available_costumes_str}]\n"
                          f"- 現在時刻: {time.strftime('%H:%M:%S')}")

        image_to_send, final_prompt_text = None, base_text
        if self.is_screenshot_mode.get() and self.screenshot_handler.is_available:
            selected_key = self.selected_capture_target_key.get()
            target_info = next((t for t in self.capture_targets_cache if (t.get('title') or t.get('name')) == selected_key), None)
            if target_info and (image_to_send := self.screenshot_handler.capture(target_info)):
                final_prompt_text += "\n\n【追加指示】添付されたスクリーンショットの内容を認識し、コメントが必要であればセリフに含めてください。"
        
        prompt = f"{costume_prompt}\n\n【指示】\n{final_prompt_text}"
        
        # このキャラクターの現在の状態で利用可能なツール設定を生成
        tools_config = self._create_tools_config_for_character(speaker)

        model_key_map = { "応答": 'pro' if self.is_pro_mode.get() else 'flash', "タッチ反応": 'flash-2', "衣装変更反応": 'flash-2' }
        model_key = model_key_map.get(message_type, 'flash-lite')
        
        self.gemini_handler.generate_response(prompt, speaker, message_type, model_key, tools_config, self.log_manager.get_formatted_log(), image=image_to_send)
    
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