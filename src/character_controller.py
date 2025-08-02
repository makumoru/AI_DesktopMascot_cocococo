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
from src.input_history_manager import InputHistoryManager

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

        # このキャラクター専用の会話ログマネージャーを初期化
        self.log_manager = ConversationLogManager(
            character_dir_path=self.character_dir,
            character_map={} 
        )

        try:
            info_section = 'INFO'
            self.name = self.char_config.get(info_section, 'CHARACTER_NAME')
            self.personality = self.char_config.get(info_section, 'CHARACTER_PERSONALITY')
            self.speaker_id = self.char_config.getint(info_section, 'DEFAULT_SPEAKER_ID')
            # キャラクター個別のウィンドウ透過色・縁色を読み込む
            self.transparent_color = self.char_config.get(info_section, 'TRANSPARENT_COLOR', fallback=mascot_app.default_transparent_color)
            self.edge_color = self.char_config.get(info_section, 'EDGE_COLOR', fallback=mascot_app.default_edge_color)
        except (NoSectionError, NoOptionError) as e:
            # character.iniに問題があっても停止しないように、デフォルト値を設定
            print(f"エラー: {char_config_path}に[INFO]セクションまたは必須項目がありません: {e}")
            self.name = f"キャラ{character_id}"
            self.personality = "親しみやすい"
            self.speaker_id = 1
            self.transparent_color = mascot_app.default_transparent_color
            self.edge_color = mascot_app.default_edge_color
        
        # --- 好感度システムの初期化 ---
        self.savedata_path = os.path.join(self.character_dir, 'favorability.ini')
        self.savedata = ConfigParser()
        self.favorability = 0 # 初期値
        self._load_or_create_savedata()
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
            
        for costume_id, costume_name in self.char_config.items('COSTUMES'):
            section = f'COSTUME_DETAIL_{costume_id}'
            if self.char_config.has_section(section):
                try:
                    relative_image_path = self.char_config.get(section, 'image_path')
                    full_image_path = os.path.join(self.character_dir, relative_image_path)
                    
                    emotions_str = self.char_config.get(section, 'available_emotions', fallback='normal:normal')
                    emotions_map = self._parse_emotions(emotions_str)

                    self.costumes[costume_id] = {
                        'name': costume_name,
                        'image_path': full_image_path,
                        'config_section': section,
                        'emotions': emotions_map
                    }
                except (NoOptionError) as e:
                    print(f"[{self.name}] 警告: 衣装セクション [{section}] の情報が不足しています: {e}")
            else:
                print(f"[{self.name}] 警告: 衣装定義セクション [{section}] が見つかりません。")

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

    def change_costume(self, costume_id, triggered_by_user=False, is_initial_setup=False):
        """
        キャラクターの衣装を変更し、関連アセット（画像、タッチエリア、感情定義）を再読み込みします。

        Args:
            costume_id (str): 変更先の衣装ID。
            triggered_by_user (bool): ユーザー操作による変更か、AIによる自律的な変更かを区別するフラグ。
            is_initial_setup (bool): 起動時の初期設定呼び出しかどうか。
        """
        if costume_id not in self.costumes:
            print(f"警告: 存在しない衣装IDが指定されました: {costume_id}")
            return
        
        if triggered_by_user and (not self.mascot_app.is_ready or self.mascot_app.is_processing_lock.locked()):
            self.ui.output_box.set_text("今、他のことを考えてるみたい...")
            return

        if triggered_by_user:
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
            if triggered_by_user and self.mascot_app.is_processing_lock.locked():
                self.mascot_app.is_processing_lock.release()
            return

        if is_initial_setup:
            return

        if triggered_by_user:
            prompt = f"ユーザーがあなたの衣装を「{costume_info['name']}」に変更しました。このことについて何かコメントしてください。"
            self.mascot_app.request_speech(self, prompt, "衣装変更反応")
        else:
            if self.mascot_app.is_processing_lock.locked():
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
        if not mascot.is_ready or mascot.is_processing_lock.locked() or mascot.is_in_rally:
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
        キャラクターごとのセーブデータ(favorability.ini)を読み込む。
        ファイルが存在しない場合は、初期値で新規作成する。
        """
        if not os.path.exists(self.savedata_path):
            self.savedata['STATUS'] = {'FAVORABILITY': '0'}
            try:
                with open(self.savedata_path, 'w', encoding='utf-8') as f:
                    self.savedata.write(f)
                print(f"[{self.name}] favorability.ini を新規作成しました。")
            except Exception as e:
                print(f"[{self.name}] favorability.ini の新規作成に失敗: {e}")
        
        try:
            self.savedata.read(self.savedata_path, encoding='utf-8')
            self.favorability = self.savedata.getint('STATUS', 'FAVORABILITY')
        except (NoSectionError, NoOptionError, ValueError) as e:
            print(f"[{self.name}] favorability.ini の読み込みエラー、または不正な値です。好感度を0に初期化します。エラー: {e}")
            self.favorability = 0
            # 不正なファイルを修正するために上書き保存
            self.savedata['STATUS'] = {'FAVORABILITY': '0'}
            with open(self.savedata_path, 'w', encoding='utf-8') as f:
                self.savedata.write(f)

    def update_favorability(self, change_value: int):
        """
        好感度を更新し、ファイルに保存する。
        変化量と合計値には上限/下限が設定される。
        """
        print("update_favorability_1")
        # AIが指定した変化量を-25から25の範囲に丸める
        change_value = max(-25, min(25, change_value))
        
        # 新しい好感度を計算
        new_favorability = self.favorability + change_value
        
        # 好感度の総量を-500から500の範囲に丸める
        new_favorability = max(-500, min(500, new_favorability))
        print(f"if([{self.favorability}] != [{new_favorability}])")
        if self.favorability != new_favorability:
            print("update_favorability_2")
            actual_change = new_favorability - self.favorability
            self.favorability = new_favorability
            self.savedata.set('STATUS', 'FAVORABILITY', str(new_favorability))
            print("update_favorability_3")
            try:
                with open(self.savedata_path, 'w', encoding='utf-8') as f:
                    self.savedata.write(f)
                print(f"[{self.name}] 好感度が {actual_change} 変化し、{new_favorability} になりました。")
                self.ui.update_info_display()
            except Exception as e:
                print(f"[{self.name}] favorability.iniの保存に失敗しました: {e}")

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
        
        if self.partner:
            partner_info = f"隣には相方の「{self.partner.name}」がいます。彼/彼女もAIで、あなたと会話をすることがあります。\n"
            pass_turn_rule = "3. `pass_turn_to_partner`: 会話のターンを相方に渡すかどうかを決定します。\n"
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
            "## 応答のルール\n"
            "あなたの応答は、必ず以下の関数を**同時に呼び出す**ことで行います。プレーンテキストでの応答は禁止です。\n"
            "1. `generate_speech`: 状況に最も適したセリフを生成します。これが応答の核となります。\n"
            "2. `change_emotion`: 上記`generate_speech`で生成したセリフの内容に、最もふさわしい感情を指定します。利用可能な感情は、その都度ツール定義で与えられます。\n"
            f"{pass_turn_rule}"
            "4. `change_favorability`: ユーザーとの直近のやり取りを評価し、あなたの好感度がどう変化したかを指定します。必ず-25から25の整数で指定してください。\n" # 好感度関数の説明を追加
            "5. `change_costume`: 必要に応じてあなたの衣装を変更します。これは任意です。\n"
            "\n"
            "## 指示の形式\n"
            "入力は `[状況説明] テキスト: [内容]` の形式で与えられます。\n"
            "- **[状況説明]** は、あなたがどのような状況で発言を求められているかを示します。（例: ユーザーからの入力、システムからの時報要求など）\n"
            "- **テキスト** は、具体的な発言内容や情報です。\n"
            "あなたはこれらの情報と、プロンプトで与えられる「あなたの現在の状態」を総合的に判断し、あなたのキャラクターとして最も自然な応答となるように、上記関数全てに必ず適切な引数を設定して呼び出してください。\n"
            f"{extra_rules}"
        )
    
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