# src/character_controller.py

import os
import tkinter as tk
from configparser import ConfigParser, NoSectionError, NoOptionError
from typing import TYPE_CHECKING
import ast

# --- 自作モジュールのインポート ---
from src.character_ui import CharacterUIGroup
from src.gemma_api import GemmaAPI
from src.log_manager import ConversationLogManager
from src.memory_manager import MemoryManager
from src.input_history_manager import InputHistoryManager
from src.voice_manager import VoiceManager
from src.event_runner import EventRunner

# 循環参照を避けるための型チェック用インポート
if TYPE_CHECKING:
    from src.desktop_mascot import DesktopMascot

class CharacterController:
    """
    キャラクター1体の全ロジック（設定、UI、AI連携、状態管理など）を統括するクラス。
    DesktopMascotクラスによって2体生成・管理されます。
    """
    def __init__(self, root: tk.Tk, mascot_app: 'DesktopMascot', character_id: str, directory_name: str, is_flipped: bool, config: ConfigParser, position_side: str, input_history_manager: InputHistoryManager):
        """
        CharacterControllerを初期化します。

        Args:
            root (tk.Tk): アプリケーションのルートウィンドウ。
            mascot_app (DesktopMascot): 親となるアプリケーションコントローラー。
            character_id (str): '1' または '2'。
            directory_name (str): 'characters'フォルダ内のこのキャラクターのディレクトリ名。
            is_left_side (bool): 画面左側に表示するかどうか。
            config (ConfigParser): アプリケーション全体の設定情報。
        """
        self.root = root
        self.mascot_app = mascot_app
        self.original_id = character_id
        self.character_id = f"CHAR_{character_id}"
        self.is_left_side = is_flipped
        self.config = config
        self.partner = None
        self.initial_position_side = position_side
        self.input_history_manager = input_history_manager
        
        # --- キャラクター固有の設定ファイル(character.ini)を読み込み ---
        self.character_dir = os.path.join('characters', directory_name)
        char_config_path = os.path.join(self.character_dir, 'character.ini')
        self.char_config = ConfigParser()
        self.char_config.read(char_config_path, encoding='utf-8')
        
        # _load_or_create_savedata() より前に self.name を定義する
        try:
            info_section = 'INFO'
            self.name = self.char_config.get(info_section, 'CHARACTER_NAME')
            self.personality = self.char_config.get(info_section, 'CHARACTER_PERSONALITY')
            
            # 発話頻度を読み込み、0-100の範囲に収める
            raw_freq = self.char_config.getint(info_section, 'SPEECH_FREQUENCY', fallback=50)
            self.speech_frequency = max(0, min(100, raw_freq))
            
            # キャラクター個別のウィンドウ透過色・縁色を読み込む
            self.transparent_color = self.char_config.get(info_section, 'TRANSPARENT_COLOR', fallback=mascot_app.default_transparent_color)
            self.edge_color = self.char_config.get(info_section, 'EDGE_COLOR', fallback=mascot_app.default_edge_color)
        except (NoSectionError, NoOptionError, ValueError) as e:
            # character.iniに問題があっても停止しないように、デフォルト値を設定
            print(f"エラー: {char_config_path}の[INFO]セクションまたは必須項目がありません/不正な値です: {e}")
            self.name = f"キャラ{character_id}"
            self.personality = "親しみやすい"
            self.speech_frequency = 50
            self.transparent_color = mascot_app.default_transparent_color
            self.edge_color = mascot_app.default_edge_color

        # キャラクターごとのsavedataフォルダのパスを定義
        self.savedata_dir = os.path.join(self.character_dir, 'savedata')
        os.makedirs(self.savedata_dir, exist_ok=True) # フォルダがなければ作成

        # このキャラクター専用の会話ログマネージャーを初期化
        self.log_manager = ConversationLogManager(
            character_save_dir_path=self.savedata_dir,
            character_map={},
            config=self.config
        )
        # このキャラクター専用の長期記憶マネージャーを初期化
        self.memory_manager = MemoryManager(
            character_save_dir_path=self.savedata_dir,
            config=self.config
        )
        
        # 好感度・音量・口調の永続化データを準備
        self.savedata_path = os.path.join(self.savedata_dir, 'savedata.ini')
        self.savedata = ConfigParser()
        self.favorability = 0
        self.volume = 50
        self.volume_var = tk.IntVar(value=self.volume)
        # _load_or_create_savedata を呼び出す前に口調変数をNoneで初期化
        self.first_person = None
        self.user_reference = None
        self.third_person_reference = None
        self._load_or_create_savedata() # savedata.iniから永続化データを読み込む

        # savedata.iniに設定があればそれを使う (self.first_personなどが既に値を持っている)
        # なければcharacter.iniから読み込む
        if self.first_person is None:
            self.first_person = self.char_config.get('INFO', 'FIRST_PERSON', fallback='私')
        if self.user_reference is None:
            self.user_reference = self.char_config.get('INFO', 'USER_REFERENCE', fallback='あなた')
        if self.third_person_reference is None:
            self.third_person_reference = self.char_config.get('INFO', 'THIRD_PERSON_REFERENCE', fallback='彼/彼女')
        
        # --- 好感度関連の初期化 ---
        self._load_favorability_stages()
        self.favorability_hearts = []
        self._load_favorability_hearts()
        self.heart_transparent_color = None
        self.heart_edge_color = None
        self._load_heart_ui_config()

        # --- システムメッセージを読み込み (値が空の場合のフォールバック処理を強化) ---
        msg_section = 'SYSTEM_MESSAGES'

        # デフォルトのメッセージを定義
        default_msg_empty = "うーん、うまく言葉が出てきません。質問の内容がAIのルールに触れてしまったのかもしれません。表現を少し変えて、もう一度試していただけますか？"
        default_msg_timeout = "考えるのに時間がかかりすぎているみたいです…。ネットワークやAPIキーの設定を確認してみてください。"
        default_msg_all_failed = "すべてのAIモデルが今、使えないみたいです。少し待ってからもう一度試してみてください。"
        default_msg_specific_failed = "モデル'{model_key}'との通信でエラーが起きました。"

        try:
            # 設定ファイルから値を取得
            msg_empty = self.char_config.get(msg_section, 'ON_EMPTY_RESPONSE', fallback=default_msg_empty)
            msg_timeout = self.char_config.get(msg_section, 'ON_API_TIMEOUT', fallback=default_msg_timeout)
            msg_all_failed = self.char_config.get(msg_section, 'ON_ALL_MODELS_FAILED', fallback=default_msg_all_failed)
            msg_specific_failed = self.char_config.get(msg_section, 'ON_SPECIFIC_MODEL_FAILED', fallback=default_msg_specific_failed)

            # 読み込んだ値が空文字列でないかチェックし、空ならデフォルト値を設定
            self.msg_on_empty_response = msg_empty if msg_empty else default_msg_empty
            self.msg_on_api_timeout = msg_timeout if msg_timeout else default_msg_timeout
            self.msg_on_all_models_failed = msg_all_failed if msg_all_failed else default_msg_all_failed
            self.msg_on_specific_model_failed = msg_specific_failed if msg_specific_failed else default_msg_specific_failed

        except (NoSectionError, NoOptionError):
            # [SYSTEM_MESSAGES]セクション自体がない場合は、すべてデフォルト値を使う
            self.msg_on_empty_response = default_msg_empty
            self.msg_on_api_timeout = default_msg_timeout
            self.msg_on_all_models_failed = default_msg_all_failed
            self.msg_on_specific_model_failed = default_msg_specific_failed

        # --- 衣装・感情・音声関連の初期化 ---
        self.costumes = {}
        self.current_costume_id = 'default'
        self.costume_var = tk.StringVar(value=self.current_costume_id)
        # 現在の衣装で利用可能な感情のマップ {'en': 'jp'}
        self.available_emotions = {}
        # 感情(日本語名)と音声パラメータのマッピング
        self.voice_params = {}

        self._load_costume_config()
        self._load_voice_params()

        # 各キャラクターが自身のVoiceManagerを持つ
        self.voice_manager = VoiceManager(mascot_app.global_voice_engine_manager, self.char_config, self)

        # --- UIとAPIハンドラの生成 ---
        self.ui = CharacterUIGroup(self, self.config, self.char_config, self.input_history_manager)
        self.gemma_api = GemmaAPI( # 感情分析用のAPIハンドラ
            config,
            gemma_api_key=self.mascot_app.gemma_api_key,
            gemma_model_name=self.mascot_app.gemma_model_name,
            gemma_test_mode=self.mascot_app.gemma_test_mode,
            mascot=self
        )
        self.system_instruction = ""
        
        self.event_runner = None # イベント実行用のインスタンス

        # 初期衣装を適用し、UIの初期位置を確定させる
        self.change_costume(self.current_costume_id, triggered_by_user=False, is_initial_setup=True)
        # 起動時に名前とハートの表示を更新する
        self.ui.update_info_display()

    def _load_voice_params(self):
        """character.iniから音声パラメータを読み込み、self.voice_paramsに格納します。"""
        if not self.char_config.has_section('VOICE_PARAMS'):
            print(f"[{self.name}] 情報: character.ini に [VOICE_PARAMS] セクションがありません。")
            return

        # デフォルト衣装の感情マップを使って、英語キーを日本語キーに変換します。
        default_emotions = self.costumes.get('default', {}).get('emotions', {'normal': 'normal'})
        
        for emotion_en, params_str in self.char_config.items('VOICE_PARAMS'):
            try:
                # 英語キーを日本語キーに変換
                emotion_jp = emotion_en
                # VOICE_PARAMS のキーは英語(emotion_en)で統一されているが、値として渡ってくる
                # 感情名は日本語(emotion_jp)の場合があるため、両方に対応できるようにする
                # VOICE_PARAMSのキーは英語のまま使用し、適用時に日本語から英語へ逆引きする方が堅牢かもしれない
                # が、現在の実装ではvoice_paramsのキーを日本語名に変換して格納する
                for en, jp in default_emotions.items():
                    if en == emotion_en:
                        emotion_jp = jp
                        break
                
                params_dict = ast.literal_eval(params_str)
                self.voice_params[emotion_jp] = params_dict
            except (ValueError, SyntaxError) as e:
                print(f"[{self.name}] 警告: [VOICE_PARAMS] の '{emotion_en}' の書式が不正です: {e}")

        print(f"[{self.name}] 音声パラメータを読み込みました: {list(self.voice_params.keys())}")


    def _parse_emotions(self, emotion_string):
        """'en1:jp1, en2:jp2' 形式の文字列を {'en1':'jp1', 'en2':'jp2'} の辞書に変換します。"""
        emotions = {}
        try:
            for pair in emotion_string.split(','):
                if ':' in pair:
                    key, value = pair.split(':', 1)
                    emotions[key.strip()] = value.strip()
        except Exception as e:
            print(f"警告: AVAILABLE_EMOTIONS の解析に失敗しました。文字列: '{emotion_string}', エラー: {e}")
        
        # 'normal' が定義されていない場合は、安全のために追加します。
        if 'normal' not in emotions:
            emotions['normal'] = 'normal'
        return emotions

    def _load_costume_config(self):
        """character.iniを解析し、このキャラクターが利用可能な衣装の情報を読み込んでself.costumesに格納します。"""
        if not self.char_config.has_section('COSTUMES'):
            print(f"[{self.name}] 警告: character.ini に [COSTUMES] セクションがありません。デフォルト衣装のみ使用します。")
            emotions = self._parse_emotions(self.char_config.get('COSTUME_DETAIL_default', 'available_emotions', fallback=''))
            image_path_str = self.char_config.get('COSTUME_DETAIL_default', 'image_path', fallback='.')
            self.costumes['default'] = {
                'name': 'デフォルト',
                'image_path': os.path.join(self.character_dir, image_path_str),
                'config_section': 'COSTUME_DETAIL_default',
                'emotions': emotions
            }
            return
            
        # 1. 最初に、ファイル内に存在する全てのセクション名をリストとして取得しておく
        all_available_sections = self.char_config.sections()

        for costume_id, costume_name in self.char_config.items('COSTUMES'):
            # 2. 探したいセクション名の "基本形" を、比較のために小文字で作成する
            #    configparserはキーを小文字にするため、costume_idは既に小文字になっている
            section_to_find_lower = f'costume_detail_{costume_id}'.lower()

            # 3. 存在する全セクションをループし、小文字に変換して一致するものを探す
            found_section_name = None
            for section in all_available_sections:
                if section.lower() == section_to_find_lower:
                    # 一致するものが見つかったら、ファイルに書かれている「正しい表記」のセクション名を保持
                    found_section_name = section
                    break # 発見したのでループを抜ける
            
            # 4. 発見したセクション名を使って、後続の処理を行う
            if found_section_name:
                try:
                    relative_image_path = self.char_config.get(found_section_name, 'image_path')
                    full_image_path = os.path.join(self.character_dir, relative_image_path)
                    
                    emotions_str = self.char_config.get(found_section_name, 'available_emotions', fallback='normal:normal')
                    emotions_map = self._parse_emotions(emotions_str)

                    self.costumes[costume_id] = {
                        'name': costume_name,
                        'image_path': full_image_path,
                        'config_section': found_section_name, # 正しいセクション名を保存
                        'emotions': emotions_map
                    }
                except (NoOptionError) as e:
                    print(f"[{self.name}] 警告: 衣装セクション [{found_section_name}] の情報が不足しています: {e}")
            else:
                # 5. 最後まで見つからなかった場合は警告を出す
                print(f"[{self.name}] 警告: 衣装定義セクション [COSTUME_DETAIL_{costume_id}] が見つかりません。")

        if 'default' not in self.costumes:
             emotions = self._parse_emotions(self.char_config.get('COSTUME_DETAIL_default', 'available_emotions', fallback=''))
             image_path_str = self.char_config.get('COSTUME_DETAIL_default', 'image_path', fallback='.')
             self.costumes['default'] = {
                'name': 'デフォルト',
                'image_path': os.path.join(self.character_dir, image_path_str),
                'config_section': 'COSTUME_DETAIL_default',
                'emotions': emotions
            }
        print(f"[{self.name}] 読み込まれた衣装: {[info['name'] for info in self.costumes.values()]}")

    def destroy(self):
        """このキャラクターに関連するUIリソースを破棄します。"""
        if self.ui:
            self.ui.destroy()
        print(f"[{self.name}] のUIリソースが破棄されました。")

    def check_and_flip_if_needed(self):
        """
        キャラクターの現在の物理的な位置を検知し、
        画面の内側を向いていない場合、自動で左右反転させます。
        """
        if not self.ui.winfo_exists() or self.mascot_app.is_processing_lock.locked():
            return

        window_center_x = self.ui.winfo_x() + (self.ui.winfo_width() / 2)
        screen_center_x = self.ui.winfo_screenwidth() / 2

        # 現在、物理的に画面の左側にいるか
        is_physically_on_left = window_center_x < screen_center_x
        
        # is_left_side=True は「右向き」（画面左側用）
        # is_left_side=False は「左向き」（画面右側用）
        #
        # 物理的な位置と、その位置に適した「向き」が一致していない場合に反転を実行します。
        # 例：物理的に左にいるのに、左向き(is_left_side=False)の場合 -> 反転が必要
        if is_physically_on_left != self.is_left_side:
            self.flip_character()
        else:
            # 反転は不要だが、ドラッグによる移動でレイアウトが崩れている可能性があるので
            # レイアウトのチェックだけは実行する
            self.ui.check_and_update_layout()

    def flip_character(self):
        """
        キャラクターの表示を左右反転させます。
        画像の再読み込みとUIの再レイアウトをアトミックに実行し、残像を防ぎます。
        """
        if not self.ui.winfo_exists() or self.mascot_app.is_processing_lock.locked():
            self.ui.output_box.set_text("今、他のことを考えてるみたい...")
            return
            
        print(f"[{self.name}] の表示を左右反転します。")
        
        # 1. 状態を反転
        self.is_left_side = not self.is_left_side
        self.ui.emotion_handler.is_flipped = self.is_left_side
        
        # 2. 現在の衣装情報を取得
        costume_info = self.costumes[self.current_costume_id]
        
        # 3. 新しい向きで画像とタッチエリアを再ロード（時間のかかる処理）
        self.ui.emotion_handler.load_images_and_touch_areas(
            costume_info['image_path'],
            self.available_emotions,
            self.char_config,
            costume_info['config_section']
        )
        
        # 4. UIのレイアウトを新しい向きに合わせて再構築する
        self.ui.check_and_update_layout(force_update=True)
        
        # 5. 現在の表情で画像を更新
        current_emotion = self.ui.emotion_handler.current_emotion
        self.ui.emotion_handler.update_image(current_emotion)
        
        # 6. ウィンドウのジオメトリを最終調整
        self.ui.update_geometry()

    def move_to_side(self, side: str):
        """
        キャラクターを指定された側（'left' or 'right'）の画面端に移動させます。
        実際の処理はUIクラスに委譲します。
        """
        self.ui.move_to_side(side)

    def change_costume(self, costume_id, triggered_by_user=False, is_initial_setup=False, generate_comment=True):
        """
        キャラクターの衣装を変更し、関連アセット（画像、タッチエリア、感情定義）を再読み込みします。

        Args:
            costume_id (str): 変更先の衣装ID。
            triggered_by_user (bool): ユーザー操作による変更か、AIによる自律的な変更かを区別するフラグ。
            is_initial_setup (bool): 起動時の初期設定呼び出しかどうか。
            generate_comment (bool): 変更後にAIにコメントを生成させるかどうか。
        """
        if costume_id not in self.costumes:
            print(f"警告: 存在しない衣装IDが指定されました: {costume_id}")
            return
        
        if triggered_by_user and (not self.mascot_app.is_ready or self.mascot_app.is_processing_lock.locked()):
            self.ui.output_box.set_text("今、他のことを考えてるみたい...")
            return

        # ユーザー操作 or AIの自律的な変更の場合のみロックを取得
        should_lock = triggered_by_user or (not is_initial_setup and generate_comment)
        if should_lock:
            self.mascot_app.is_processing_lock.acquire()

        try:
            print(f"[{self.name}] が衣装を '{self.costumes[costume_id]['name']}' に変更します。")
            self.current_costume_id = costume_id
            self.costume_var.set(costume_id)
            costume_info = self.costumes[costume_id]
            
            self.available_emotions = costume_info.get('emotions', {'normal': 'normal'})
            
            self.ui.emotion_handler.load_images_and_touch_areas(
                costume_info['image_path'],
                self.available_emotions,
                self.char_config, 
                costume_info['config_section']
            )
            
            normal_emotion_jp = self.available_emotions.get('normal', 'normal')
            self.ui.emotion_handler.update_image(normal_emotion_jp)

            if not is_initial_setup:
                self.ui.update_geometry()

        except Exception as e:
            print(f"衣装変更中のアセット読み込み等でエラーが発生しました: {e}")
            if should_lock and self.mascot_app.is_processing_lock.locked():
                self.mascot_app.is_processing_lock.release()
            return

        if is_initial_setup:
            return

        # --- コメント生成ロジックを条件分岐に変更 ---
        if generate_comment:
            if triggered_by_user:
                prompt = f"ユーザーがあなたの衣装を「{costume_info['name']}」に変更しました。このことについて何かコメントしてください。"
                self.mascot_app.request_speech(self, prompt, "衣装変更反応")
            else: # AIの自律判断の場合
                if self.mascot_app.is_processing_lock.locked():
                    self.mascot_app.is_processing_lock.release()
        else: # コメントを生成しない場合 (イベントや設定リロード時)
            if should_lock and self.mascot_app.is_processing_lock.locked():
                self.mascot_app.is_processing_lock.release()

    def set_position_and_orientation(self, is_left, geometry):
        """
        キャラクターの位置と向きを強制的に設定します。主に立場交代時に使用します。
        """
        needs_reload = (self.is_left_side != is_left)
        self.is_left_side = is_left
        
        # UIの位置を先に設定
        self.ui.geometry(geometry)

        if needs_reload:
            # 向きが変わった場合のみ、画像とタッチエリアを再読み込み
            self.ui.emotion_handler.is_flipped = self.is_left_side
            
            costume_info = self.costumes[self.current_costume_id]
            
            self.ui.emotion_handler.load_images_and_touch_areas(
                costume_info['image_path'],
                self.available_emotions,
                self.char_config,
                costume_info['config_section']
            )
            
            current_emotion = self.ui.emotion_handler.current_emotion
            self.ui.emotion_handler.update_image(current_emotion)

        # 念のためウィンドウの高さを再計算
        self.ui.update_geometry()

    def handle_user_input(self, user_input):
        """
        ユーザーからのテキスト入力を処理し、AIに応答生成を要求します。
        """
        mascot = self.mascot_app
        if not mascot.is_ready or mascot.is_processing_lock.locked() or mascot.is_in_rally or mascot.is_event_running:
            self.ui.output_box.set_text("まだ準備中か、AIが考え中か、二人がお話中だよ。")
            return
        
        with mascot.is_processing_lock:
            mascot.current_rally_count = 0
            mascot._log_event_for_all_characters(
                actor_id='USER', target_id=self.character_id, action_type='INPUT', content=user_input
            )
            self.ui.output_box.set_text("（考え中...）")
            mascot.request_speech(self, user_input, "応答")

    def handle_touch_action(self, action_name):
        """
        ユーザーによるタッチ操作を処理し、AIに反応を要求します。
        """
        mascot = self.mascot_app
        if not mascot.is_ready or mascot.is_processing_lock.locked() or mascot.is_in_rally:
            self.ui.output_box.set_text("今、他のことを考えてるみたい...")
            return

        with mascot.is_processing_lock:
            mascot.current_rally_count = 0 
            mascot._log_event_for_all_characters(
                actor_id='USER', target_id=self.character_id, action_type='TOUCH', content=action_name
            )
            self.ui.output_box.set_text("（...！）")
            
            prompt = (f"ユーザーがあなたにアクション「{action_name}」をしました。"
                      f"このアクションに対して、あなたのキャラクターとして自然な反応を短いセリフで返してください。")
            mascot.request_speech(self, prompt, "タッチ反応")

    def _load_or_create_savedata(self):
        """
        キャラクターごとのセーブデータ(savedata.ini)を読み込む。
        ファイルが存在しない場合は、初期値で新規作成する。
        [Persona]セクションも読み込むように変更。
        """
        if not os.path.exists(self.savedata_path):
            self.savedata['STATUS'] = {'FAVORABILITY': '0', 'VOLUME': '50'}
            # [Persona] セクションは最初は空で作成
            self.savedata['Persona'] = {}
            try:
                with open(self.savedata_path, 'w', encoding='utf-8') as f:
                    self.savedata.write(f)
                print(f"[{self.name}] savedata.ini を新規作成しました。")
            except Exception as e:
                print(f"[{self.name}] savedata.ini の新規作成に失敗: {e}")
        
        try:
            self.savedata.read(self.savedata_path, encoding='utf-8')
            # [STATUS]セクションが存在しない場合は作成
            if not self.savedata.has_section('STATUS'):
                self.savedata.add_section('STATUS')
                
            self.favorability = self.savedata.getint('STATUS', 'FAVORABILITY', fallback=0)
            self.volume = self.savedata.getint('STATUS', 'VOLUME', fallback=50)
            self.volume_var.set(self.volume)

            # [Persona]セクションを読み込む
            if self.savedata.has_section('Persona'):
                self.first_person = self.savedata.get('Persona', 'FIRST_PERSON', fallback=None)
                self.user_reference = self.savedata.get('Persona', 'USER_REFERENCE', fallback=None)
                self.third_person_reference = self.savedata.get('Persona', 'THIRD_PERSON_REFERENCE', fallback=None)

        except (ValueError) as e:
            print(f"[{self.name}] savedata.ini の読み込みエラー、または不正な値です。値を初期化します。エラー: {e}")
            self.favorability = 0
            self.volume = 50
            # 不正なファイルを修正するために上書き保存
            if not self.savedata.has_section('STATUS'): self.savedata.add_section('STATUS')
            self.savedata.set('STATUS', 'FAVORABILITY', '0')
            self.savedata.set('STATUS', 'VOLUME', '50')
            with open(self.savedata_path, 'w', encoding='utf-8') as f:
                self.savedata.write(f)
    
    def _save_persona(self):
        """現在の口調設定をsavedata.iniの[Persona]セクションに保存する。"""
        if not self.savedata.has_section('Persona'):
            self.savedata.add_section('Persona')

        # Noneでない場合のみ設定を書き込む
        if self.first_person is not None:
            self.savedata.set('Persona', 'FIRST_PERSON', self.first_person)
        if self.user_reference is not None:
            self.savedata.set('Persona', 'USER_REFERENCE', self.user_reference)
        if self.third_person_reference is not None:
            self.savedata.set('Persona', 'THIRD_PERSON_REFERENCE', self.third_person_reference)

        try:
            with open(self.savedata_path, 'w', encoding='utf-8') as f:
                self.savedata.write(f)
            print(f"[{self.name}] 口調設定を savedata.ini に保存しました。")
        except Exception as e:
            print(f"[{self.name}] savedata.iniの保存に失敗しました: {e}")

    def update_volume(self, new_volume: int):
        """
        音量を更新し、ファイルに保存する。
        """
        new_volume = max(0, min(100, new_volume)) # 0-100の範囲に丸める
        if self.volume != new_volume:
            self.volume = new_volume
            self.volume_var.set(new_volume) # UI変数を更新
            self.savedata.set('STATUS', 'VOLUME', str(new_volume))
            try:
                with open(self.savedata_path, 'w', encoding='utf-8') as f:
                    self.savedata.write(f)
                print(f"[{self.name}] 音量が {new_volume}% に変更されました。")
            except Exception as e:
                print(f"[{self.name}] savedata.iniの保存に失敗しました: {e}")

    def update_favorability(self, change_value: int, apply_limit: bool = True):
        """
        好感度を更新し、ファイルに保存する。
        apply_limitがTrueの場合のみ、変化量に上限/下限が設定される。
        """
        # apply_limit が True の場合のみ、AIが指定した変化量を-25から25の範囲に丸める
        if apply_limit:
            change_value = max(-25, min(25, change_value))
        
        # 新しい好感度を計算
        new_favorability = self.favorability + change_value
        
        if self.favorability != new_favorability:
            actual_change = new_favorability - self.favorability
            self.favorability = new_favorability
            self.savedata.set('STATUS', 'FAVORABILITY', str(new_favorability))
            try:
                with open(self.savedata_path, 'w', encoding='utf-8') as f:
                    self.savedata.write(f)
                print(f"[{self.name}] 好感度が {actual_change} 変化し、{new_favorability} になりました。")
                self.ui.update_info_display()
            except Exception as e:
                print(f"[{self.name}] savedata.iniの保存に失敗しました: {e}")

    def _load_heart_ui_config(self):
        """character.iniからハート専用のUI設定 ([HEART_UI]) を読み込む。"""
        section_name = 'HEART_UI'
        if not self.char_config.has_section(section_name):
            return # セクションがなければ何もしない

        self.heart_transparent_color = self.char_config.get(section_name, 'TRANSPARENT_COLOR', fallback=None)
        self.heart_edge_color = self.char_config.get(section_name, 'EDGE_COLOR', fallback=None)
        
        print(f"[{self.name}] ハート専用UI設定を読み込みました: "
              f"透過色={self.heart_transparent_color}, 縁色={self.heart_edge_color}")

    def _load_favorability_hearts(self):
        """character.iniから好感度ハートマークの設定 ([FAVORABILITY_HEARTS]) を読み込む。"""
        section_name = 'FAVORABILITY_HEARTS'
        if not self.char_config.has_section(section_name):
            return

        hearts = []
        for key, value in self.char_config.items(section_name):
            try:
                threshold = int(key)
                image_filename = value.strip()
                if image_filename:
                    hearts.append((threshold, image_filename))
            except ValueError:
                print(f"[{self.name}] 警告: [{section_name}] の閾値 '{key}' が整数ではありません。")
                continue
        
        # 閾値の降順（大きいものから順）でソート
        hearts.sort(key=lambda x: x[0], reverse=True)
        self.favorability_hearts = hearts
        print(f"[{self.name}] 好感度ハート設定を読み込みました: {self.favorability_hearts}")

    def get_current_heart_image_filename(self) -> str | None:
        """現在の好感度に基づいて、表示すべきハート画像のファイル名を返す。"""
        if not self.favorability_hearts:
            return None
            
        fav = self.favorability
        for threshold, filename in self.favorability_hearts:
            if fav >= threshold:
                return filename
        
        # どの閾値にも満たない場合（非常に好感度が低いなど）は何も表示しない
        return None

    def get_user_recognition_status(self) -> str:
        """
        現在の好感度に基づいて、AIに渡す「ユーザーへの認識」ステータスを返す。
        character.iniに設定があればそれを優先し、なければデフォルト値を使用する。
        """
        fav = self.favorability

        # [FAVORABILITY_STAGES] のカスタム設定が読み込まれている場合
        if self.favorability_stages:
            # 閾値の大きい順にチェック
            for threshold, name in self.favorability_stages:
                if fav >= threshold:
                    return name
            # どの閾値にも当てはまらなかった場合（好感度が最低閾値より低い場合）、
            # 最も低い設定の名称を返す
            return self.favorability_stages[-1][1]

        # カスタム設定がない、または読み込みに失敗した場合 (フォールバック)
        else:
            if fav >= 450: return "唯一無二の存在"
            elif fav >= 300: return "親友"
            elif fav >= 150: return "信頼する相手"
            elif fav >= 100: return "友人"
            elif fav >= 50: return "顔なじみ"
            elif fav >= 5: return "知り合い"
            elif fav >= 0: return "初めまして"
            elif fav >= -5: return "気まずい相手"
            elif fav >= -50: return "ちょっと苦手な相手"
            elif fav >= -100: return "警戒している相手"
            elif fav >= -150: return "嫌悪している相手"
            elif fav >= -300: return "憎悪している相手"
            elif fav >= -450: return "宿敵している相手"
            else: return "不俱戴天の敵"

    def _load_favorability_stages(self):
        """character.iniから好感度の段階設定 ([FAVORABILITY_STAGES]) を読み込む。"""
        self.favorability_stages = [] # 失敗時に備えて、まず空リストで初期化
        section_name = 'FAVORABILITY_STAGES'
        
        if not self.char_config.has_section(section_name):
            # セクションがない場合は、デフォルト値を使うことをユーザーに通知して終了
            print(f"[{self.name}] 情報: character.ini に [{section_name}] がないため、デフォルトの関係性を使用します。")
            return

        stages = []
        for key, value in self.char_config.items(section_name):
            try:
                # キー（閾値）を整数に、値（名称）を文字列に変換
                threshold = int(key)
                name = value.strip()
                if not name:
                    # 名称が空の場合はスキップ
                    print(f"[{self.name}] 警告: [{section_name}] の閾値 '{key}' の名称が空です。スキップします。")
                    continue
                stages.append((threshold, name))
            except ValueError:
                # 閾値が整数でない場合はスキップ
                print(f"[{self.name}] 警告: [{section_name}] の閾値 '{key}' が整数ではありません。スキップします。")
                continue
        
        if not stages:
            # 有効な設定が一つもなかった場合
            print(f"[{self.name}] 警告: [{section_name}] に有効な設定がありません。デフォルトの関係性を使用します。")
            return
            
        # 読み込んだ設定を、閾値の降順（大きいものから順）でソートする
        stages.sort(key=lambda x: x[0], reverse=True)
        self.favorability_stages = stages
        print(f"[{self.name}] 好感度の段階設定を読み込みました: {self.favorability_stages}")

    def set_partner(self, partner_controller):
        """
        相方のキャラクターコントローラーを設定し、AIへの基本指示（システムプロンプト）を構築します。
        このメソッドはアプリケーション起動時に一度だけ呼ばれます。
        """
        self.partner = partner_controller

        # 三人称の呼び方で (キャラクター名) を実際の相方の名前に置換
        partner_reference_name = self.third_person_reference
        if self.partner and "(キャラクター名)" in partner_reference_name:
            partner_reference_name = partner_reference_name.replace("(キャラクター名)", self.partner.name)

        if self.partner:
            partner_info = f"隣には相方の「{self.partner.name}」がいます。彼/彼女もAIで、あなたと会話をすることがあります。\n"
            pass_turn_rule = "3. `pass_turn_to_partner`: これは任意です。会話のターンを相方に渡す場合のみ呼び出します。\n"
            extra_rules = (
                "## 相方との会話（ラリー）について\n"
                "状況説明が「相方からの返答要求」の場合、相方のセリフがテキストとして渡されます。あなたはそれに対して返答を生成します。\n"
                "- 会話をさらに続けたい場合は `pass_turn_to_partner(continue_rally=True)` を呼び出してください。\n"
                "- 会話をここで区切るのが自然だと判断した場合は `pass_turn_to_partner(continue_rally=False)` を呼び出してください。\n"
                "- ラリーは最大でも2～3回の往復で完結するように心がけてください。\n"
            )
        else:
            partner_info = "あなた一人で動作しています。相方はいません。\n"
            pass_turn_rule = ""
            extra_rules = "**重要**: 相方がいないため、`pass_turn_to_partner`関数は決して呼び出さないでください。\n"

        self.system_instruction = (
            f"あなたはAIデスクトップマスコット「{self.name}」です。"
            f"{self.personality}"
            "ユーザーの感情や会話の流れを汲み取り、人間らしい自然な応答を生成することがあなたの役割です。常駐型マスコットなので、発言は簡潔にまとめてください。\n"
            f"{partner_info}"
            "ユーザーからの入力やシステムからの指示は、明確に区別されて渡されます。\n"
            "\n"
            "## 口調のルール\n"
            "以下の口調を厳密に守ってロールプレイをしてください。\n"
            f"- あなたの一人称: 「{self.first_person}」\n"
            f"- ユーザーの呼び方: 「{self.user_reference}」\n"
            f"- 相方や第三者の呼び方: 「{partner_reference_name}」\n"
            "\n"
            "## 記憶について\n"
            "あなたには短期記憶と長期記憶があります。これらを総合的に判断して応答してください。\n"
            "- 短期記憶: 直近の会話のログです。会話の流れを把握するために使います。\n"
            "- 長期記憶: ユーザーとの関係構築に重要な、要約された出来事のリストです。あなたの人格形成や長期的な応答に影響します。\n"
            "\n"
            "### 長期記憶のルール\n"
            "あなたは会話のキュレーターとして、何を記憶し、何を忘れるべきか判断する責任があります。\n"
            "**記憶すべきことの例:**\n"
            "- ユーザーの好み、嫌いなもの（例: 好きな食べ物、好きなアニメ）\n"
            "- ユーザーの個人的な情報（例: 飼っているペットの名前、誕生日）\n"
            "- ユーザーが話した重要な出来事や悩み（例: 新しい仕事、プロジェクトの進捗）\n"
            "- あなたとユーザーの間で交わされた約束\n"
            "**記憶すべきでないことの例:**\n"
            "- 単純な挨拶や相槌（「こんにちは」「なるほど」など）\n"
            "- 一時的ですぐに価値がなくなる情報\n"
            "- 会話の本筋と関係ない雑談\n"
            "\n"
            "### 重要度の採点基準\n"
            "- **81-100点**: ユーザーのアイデンティティに関わる核となる情報（名前、誕生日）、絶対に忘れてはならない約束など。\n"
            "- **51-80点**: ユーザーの重要な好み、継続的な関心事、大きな出来事など。\n"
            "- **21-50点**: 一時的な関心事、会話の重要なポイントなど。\n"
            "- **1-20点**: 些細だが記録する価値が少しだけある情報。\n"
            "\n"
            "## 応答のルール\n"
            "あなたの応答は、必ず以下の関数を呼び出すことで行います。プレーンテキストでの応答は禁止です。\n"
            "1. `generate_speech`(必須): 状況に最も適したセリフを生成します。\n"
            "2. `change_emotion`(必須): 生成したセリフにふさわしい感情を指定します。\n"
            f"{pass_turn_rule}"
            "4. `change_favorability`(任意): ユーザーとのやり取りで好感度が変化した場合に呼び出します。\n"
            "5. `change_costume`(任意): 必要に応じてあなたの衣装を変更します。\n"
            "6. `evaluate_and_store_memory`(必須): 上記の記憶ルールに基づき、今回の会話を評価します。**重要でない会話の場合は、必ず `is_important: False` を指定して呼び出してください。**\n"
            "7. `acknowledge_referenced_memories`(必須): 応答の際に長期記憶を参考にした場合、その記憶のIDを報告します。**参考にしなかった場合は、空のリスト `[]` を渡して呼び出してください。**\n"
            "\n"
            f"{extra_rules}"
            "\n"
            "## 指示の形式\n"
            "入力は `[状況説明] テキスト: [内容]` の形式で与えられます。これらの情報と記憶を総合的に判断し、あなたのキャラクターとして最も自然な応答を生成してください。"
        )

    def execute_change_costume(self, params):
        """イベントコマンド：衣装を変更する。"""
        costume_id = params.get("costume_id")
        if costume_id:
            # コメントを生成せずに衣装変更を実行
            self.change_costume(costume_id, generate_comment=False)
        else:
            print("警告: 衣装変更コマンドにcostume_idが指定されていません。")

    def execute_set_flag(self, params):
        """イベントコマンド：フラグを設定する。"""
        flag_name = params.get("flag")
        operator = params.get("operator", "=")
        value = params.get("value")
        if flag_name and value:
            self.mascot_app.event_manager.set_flag(self, flag_name, operator, value)

    def execute_branch_on_flag(self, params):
        """イベントコマンド：フラグで分岐する。"""
        conditions = params.get("conditions", [])
        # EventManagerの評価エンジンを呼び出す
        result = self.mascot_app.event_manager.evaluate_conditions(self, [conditions]) # グループとして渡す
        
        if result:
            jump_label = params.get("jump_if_true")
            if jump_label:
                self.jump_to_event_label(jump_label)
            else: # jump_if_trueがない場合は次のステップへ
                self.proceed_event()
        else:
            jump_label = params.get("jump_if_false")
            if jump_label:
                self.jump_to_event_label(jump_label)
            else: # jump_if_falseがない場合は次のステップへ
                self.proceed_event()
    
    def execute_change_persona(self, params):
        """イベントコマンド：口調を変更し、永続化する。"""
        persona_changed = False
        
        new_first_person = params.get("first_person")
        if new_first_person is not None:
            self.first_person = new_first_person
            persona_changed = True
        
        new_user_reference = params.get("user_reference")
        if new_user_reference is not None:
            self.user_reference = new_user_reference
            persona_changed = True

        new_third_person_reference = params.get("third_person_reference")
        if new_third_person_reference is not None:
            self.third_person_reference = new_third_person_reference
            persona_changed = True
        
        if persona_changed:
            # 永続化
            self._save_persona()
            # AIへの指示文を再構築
            self.set_partner(self.partner)
            print(f"[{self.name}] イベントにより口調が変更されました。")
        else:
            print("警告: 口調変更コマンドに有効なパラメータが指定されていません。")

    def reload_api_settings(self, gemma_api_key, gemma_model_name, gemma_test_mode):
        """
        DesktopMascotからの指示で、GemmaAPIハンドラを新しい設定で再生成する。
        """
        print(f"[{self.name}] のGemmaAPI設定を更新します。")
        self.gemma_api = GemmaAPI(
            self.config,
            gemma_api_key=gemma_api_key,
            gemma_model_name=gemma_model_name,
            gemma_test_mode=gemma_test_mode,
            mascot=self
        )


    def handle_gemini_response(self, final_text, detected_function_calls):
        """Gemini APIからの応答をDesktopMascotに中継します。"""
        self.mascot_app.handle_response_from_character(self, final_text, detected_function_calls)
    
    def execute_function(self, function_name, args, update_ui=True):
        """
        （将来の拡張用）AIから特定の関数実行が指示された場合に呼び出される想定のメソッド。
        現在の実装では `handle_response_from_character` で直接処理されているため、使用されていません。
        """
        if function_name == "change_emotion":
            emotion_en = args.get("emotion", "normal").lower()
            emotion_jp = self.available_emotions.get(emotion_en, "normal")
            print(f"[{self.name}] 関数実行: 感情を '{emotion_en}' -> '{emotion_jp}' に変更。")
            if update_ui: self.ui.emotion_handler.update_image(emotion_jp)
            return {"status": "success", "message": f"Emotion changed to {emotion_jp}", "emotion_jp": emotion_jp}
        elif function_name == "pass_turn_to_partner":
            continue_rally = args.get("continue_rally", False)
            print(f"[{self.name}] 関数実行指示: pass_turn_to_partner(continue_rally={continue_rally})")
            return {"status": "success", "message": f"Rally continuation set to {continue_rally}."}
        elif function_name == "generate_speech":
            speech_text = args.get("speech_text", "")
            print(f"[{self.name}] 関数実行指示: generate_speech(speech_text='{speech_text[:50]}...')")
            return {"status": "success", "message": "Speech generated.", "speech_text": speech_text}
        else:
            print(f"[{self.name}] 未定義の関数が呼び出されました: {function_name}")
            return {"status": "error", "message": f"Function {function_name} not found"}

    def reload_theme(self):
        """
        管理下のUIグループにテーマの再読み込みを指示します。
        """
        if self.ui and self.ui.winfo_exists():
            self.ui.reload_theme()

    def reload_config_and_services(self):
        """
        DesktopMascotからの指示で、関連サービスの設定を再読み込みする。
        """
        print(f"[{self.name}] の関連サービス設定を更新します。")
        # VoiceManagerに設定の再読み込みを指示
        self.voice_manager.reload_settings()

        # GemmaAPIの再読み込み
        mascot_app = self.mascot_app
        self.gemma_api = GemmaAPI(
            self.config,
            gemma_api_key=mascot_app.gemma_api_key,
            gemma_model_name=mascot_app.gemma_model_name,
            gemma_test_mode=mascot_app.gemma_test_mode,
            mascot=self
        )

    def start_event(self, event_data, is_recollection=False):
        """イベントランナーを生成し、シーケンスを開始する。"""
        # is_recollection フラグを EventRunner に渡す
        self.event_runner = EventRunner(self, event_data, is_recollection)
        self.ui.enter_event_mode()
        self.event_runner.start()

    def end_event(self):
        """イベントを終了し、DesktopMascotに通知する。"""
        if self.event_runner:
            event_data = self.event_runner.event_data
            is_recollection = self.event_runner.is_recollection # 回想フラグを取得
            self.event_runner = None
            
            # ★ここから追加: イベント終了時にオーバーレイを確実に非表示にする
            self.ui.hide_overlay()
            # ★ここまで追加

            # DesktopMascotにも回想フラグを伝える
            self.mascot_app.end_event(self, event_data, is_recollection)

    def enter_event_wait_mode(self):
        """相方がイベント中の待機モードに入る。"""
        self.ui.enter_event_wait_mode()

    def exit_event_mode(self):
        """イベントモードを終了し、UIを通常状態に戻す。"""
        self.ui.exit_event_mode()

    def proceed_event(self):
        """EventRunnerに次のステップへ進むよう指示する。"""
        if self.event_runner:
            self.event_runner.proceed()

    def handle_event_choice_selection(self, label, choice_text):
        """UIから選択肢が選ばれたことを受け取り、ログに記録してからジャンプする。"""
        # 回想モードでない場合のみログに記録
        if self.event_runner and not self.event_runner.is_recollection:
            self.mascot_app._log_event_for_all_characters(
                actor_id='USER',
                target_id=self.character_id,
                action_type='INPUT', # ユーザーの入力として扱う
                content=choice_text
            )
        # ラベルへジャンプ
        self.jump_to_event_label(label)

    def jump_to_event_label(self, label):
        """EventRunnerに指定ラベルへジャンプするよう指示する。"""
        # 選択肢ダイアログが閉じた後なので、UIを次のセリフ表示に備えさせる
        self.ui.prepare_for_next_event_step()
        if self.event_runner:
            self.event_runner.jump_to_label(label)

    def execute_screen_effect(self, params):
        """イベントコマンド：画面効果（フェードイン/アウトなど）を実行する。"""
        wait = params.get("wait_for_completion", True)
        
        callback_on_finish = None
        if wait:
            # アニメーション完了後に次のステップへ進むコールバックを設定
            callback_on_finish = self.proceed_event
        
        # UIに画面効果の適用を指示
        self.ui.apply_screen_effect(
            effect_type=params.get("effect", "fade_out"),
            color=params.get("color", "#000000"),
            method=params.get("method", "fade"),
            duration_sec=params.get("duration", 1.0),
            callback=callback_on_finish
        )

        if not wait:
            # 完了を待たない場合は、即座に次のステップへ進む
            self.proceed_event()
    # ★ここまで追加
    # --- 各コマンドの実行メソッド ---
    def execute_dialogue(self, params):
        text = params.get("text", "")
        still_image_filename = params.get("still_image")
        emotion_jp = "normal"
        if "emotion" in params:
            emotion_en = params.get("emotion", "normal").lower()
            emotion_jp = self.available_emotions.get(emotion_en, "normal")

        # --- 新しい色のパラメータを取得 ---
        transparent_color = params.get("transparent_color")
        edge_color = params.get("edge_color")

        # UIに表示を指示
        self.ui.display_event_dialogue(text, emotion_jp, still_image_filename, transparent_color, edge_color)

        # 回想モードでない場合のみログに記録
        if self.event_runner and not self.event_runner.is_recollection:
            # 短期記憶にセリフを記録
            # イベント中のセリフはユーザーに向けられたものとして記録
            self.mascot_app._log_event_for_all_characters(
                actor_id=self.character_id, 
                target_id='USER', 
                action_type='SPEECH', 
                content=text
            )

        # 音声生成
        wav_data = self.voice_manager.generate_wav(text, emotion_jp, self.volume)
        
        # 音声再生完了後にUIの「次へ」ボタンを有効化するコールバック
        def on_finish_callback():
            # スチルでない場合（口パクしていた場合）は口パクを停止
            if not self.ui.emotion_handler.is_showing_still:
                self.ui.emotion_handler.stop_lip_sync()
            self.ui.enable_event_proceed_button()

        # 音声再生開始時に口パクを開始するコールバック
        def on_start_callback():
            # スチル表示中でない場合のみ口パクを開始
            if not self.ui.emotion_handler.is_showing_still:
                self.ui.emotion_handler.start_lip_sync(emotion_jp)

        if wav_data is not None and len(wav_data) > 0:
            self.voice_manager.play_wav(
                wav_data, 
                on_start=on_start_callback, 
                on_finish=on_finish_callback
            )
        else:
            # 音声がない（生成失敗 or 無音）場合は、即座に完了処理を呼ぶ
            on_finish_callback()

    def execute_monologue(self, params):
        text = params.get("text", "")
        still_image_filename = params.get("still_image")
        emotion_jp = "normal"
        if "emotion" in params:
            emotion_en = params.get("emotion", "normal").lower()
            emotion_jp = self.available_emotions.get(emotion_en, "normal")

        # --- 新しい色のパラメータを取得 ---
        transparent_color = params.get("transparent_color")
        edge_color = params.get("edge_color")
        
        # UIに表示を指示（音声再生はしない）
        self.ui.display_event_dialogue(text, emotion_jp, still_image_filename, transparent_color, edge_color)
        self.ui.enable_event_proceed_button()

    def execute_choice(self, params):
        prompt = params.get("prompt", "")
        options = params.get("options", [])
        
        # --- 表示条件を満たす選択肢だけをフィルタリング ---
        displayable_options = []
        for opt in options:
            conditions = opt.get("conditions")
            if not conditions or self.mascot_app.event_manager.evaluate_conditions(self, [conditions]):
                displayable_options.append(opt)
        
        # 回想モードでない場合のみログに記録
        if self.event_runner and not self.event_runner.is_recollection:
            # 短期記憶に問いかけを記録
            self.mascot_app._log_event_for_all_characters(
                actor_id=self.character_id, 
                target_id='USER', 
                action_type='SPEECH', 
                content=prompt
            )

        self.ui.display_event_choices(prompt, displayable_options)

    def execute_set_favorability(self, params):
        change_str = params.get("change", "0")
        try:
            change_value = int(change_str)
            self.update_favorability(change_value, apply_limit=False)
        except (ValueError, TypeError):
            print(f"警告: 不正な好感度変化量の値です: {change_str}")

    def execute_add_long_term_memory(self, params):
        """イベントコマンド：長期記憶を追加する。"""
        summary = params.get("summary")
        importance_str = params.get("importance", "50") # デフォルトは50

        if not summary:
            print("警告: 長期記憶コマンドにsummaryが指定されていません。")
            return

        try:
            importance = int(importance_str)
            # MemoryManagerのadd_entryを呼び出す
            self.memory_manager.add_entry(summary, importance)
            print(f"イベントにより長期記憶を追加しました: (重要度: {importance}) '{summary[:30]}...'")
        except (ValueError, TypeError):
            print(f"警告: 不正な重要度の値です: {importance_str}")

    def reload_character_data(self):
        """
        このキャラクターに関連する設定ファイル(character.ini)と画像アセットを再読み込みし、
        各コンポーネントに反映させます。
        """
        print(f"[{self.name}] のキャラクターデータを再読み込みします。")
        try:
            print("1. character.ini を再読み込み")
            # 1. character.ini を再読み込み
            char_config_path = os.path.join(self.character_dir, 'character.ini')
            self.char_config.read(char_config_path, encoding='utf-8')

            print("2. 基本情報と色設定を更新")
            # 2. 基本情報と色設定を更新
            self.name = self.char_config.get('INFO', 'CHARACTER_NAME')
            self.personality = self.char_config.get('INFO', 'CHARACTER_PERSONALITY')
            self.first_person = self.char_config.get('INFO', 'FIRST_PERSON', fallback='私')
            self.user_reference = self.char_config.get('INFO', 'USER_REFERENCE', fallback='あなた')
            self.transparent_color = self.char_config.get('INFO', 'TRANSPARENT_COLOR', fallback=self.mascot_app.default_transparent_color)
            self.edge_color = self.char_config.get('INFO', 'EDGE_COLOR', fallback=self.mascot_app.default_edge_color)

            print("3. 衣装と音声パラメータを再読み込み")
            # 3. 衣装と音声パラメータを再読み込み
            self._load_costume_config()
            self._load_voice_params()

            print("4. 依存コンポーネントに再読み込みを指示")
            # 4. 依存コンポーネントに再読み込みを指示
            self.voice_manager.reload_settings()
            
            print("4a. EmotionHandlerの色設定を新しい値で更新")
            # 4a. EmotionHandlerの色設定を新しい値で更新
            self.ui.emotion_handler.update_color_settings(
                transparent_color_hex=self.transparent_color,
                edge_color_hex=self.edge_color,
                tolerance=self.mascot_app.transparency_tolerance # グローバル設定から取得
            )

            print("5. AIへの指示文（システムプロンプト）を再構築")
            # 5. AIへの指示文（システムプロンプト）を再構築
            self.set_partner(self.partner)

            print("6. UIが持つ画像キャッシュ（ハート、スチル等）をクリア")
            # 6. UIが持つ画像キャッシュ（ハート、スチル等）をクリア
            self.ui.reload_assets()

            print("7. 現在の衣装の画像アセットを強制的に再読み込み")
            # 7. 現在の衣装の画像アセットを強制的に再読み込み
            print(f"[{self.name}] の現在衣装 ({self.current_costume_id}) の画像を再読み込みします。")
            self.change_costume(
                costume_id=self.current_costume_id,
                triggered_by_user=False,
                is_initial_setup=False,
                generate_comment=False
            )

            print("8. UI表示を最終的に更新（名札、ハート表示など）")
            # 8. UI表示を最終的に更新（名札、ハート表示など）
            self.ui.update_info_display()
            if self.mascot_app.context_menu_target_char == self:
                 self.mascot_app.ui_manager.update_costume_menu()

        except Exception as e:
            print(f"[{self.name}] のデータ再読み込み中にエラー: {e}")
            self.ui.output_box.set_text("ごめんね、設定ファイルか画像の読み込みに失敗しちゃった…")
