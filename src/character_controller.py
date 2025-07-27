# src/character_controller.py

import os
import tkinter as tk
from configparser import ConfigParser, NoSectionError, NoOptionError
from typing import TYPE_CHECKING
import ast

# --- 自作モジュールのインポート ---
from src.character_ui import CharacterUIGroup
from src.gemma_api import GemmaAPI

# 循環参照を避けるための型チェック用インポート
if TYPE_CHECKING:
    from src.desktop_mascot import DesktopMascot

class CharacterController:
    """
    キャラクター1体の全ロジック（設定、UI、AI連携、状態管理など）を統括するクラス。
    DesktopMascotクラスによって2体生成・管理されます。
    """
    def __init__(self, root: tk.Tk, mascot_app: 'DesktopMascot', character_id: str, directory_name: str, is_left_side: bool, config: ConfigParser):
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
        self.is_left_side = is_left_side
        self.config = config # アプリ全体のconfig
        self.partner = None
        
        # --- キャラクター固有の設定ファイル(character.ini)を読み込み ---
        self.character_dir = os.path.join('characters', directory_name)
        char_config_path = os.path.join(self.character_dir, 'character.ini')
        self.char_config = ConfigParser()
        self.char_config.read(char_config_path, encoding='utf-8')

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
        self.ui = CharacterUIGroup(self.root, self, self.config, self.char_config)
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
        
        if triggered_by_user and self.mascot_app.is_processing_lock.locked():
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

            # 画像がロードされ、ラベルのサイズが確定した後にウィンドウのジオメトリを更新
            self.ui.update_geometry(is_initial=is_initial_setup)

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
            mascot.log_manager.add_entry(
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
            mascot.log_manager.add_entry(
                actor_id='USER', target_id=self.character_id, action_type='TOUCH', content=action_name
            )
            self.ui.output_box.set_text("（...！）")
            
            prompt = (f"ユーザーがあなたにアクション「{action_name}」をしました。"
                      f"このアクションに対して、あなたのキャラクターとして自然な反応を短いセリフで返してください。")
            mascot.request_speech(self, prompt, "タッチ反応")

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
            "4. `change_costume`: 必要に応じてあなたの衣装を変更します。これは任意です。\n"
            "\n"
            "## 指示の形式\n"
            "入力は `[状況説明] テキスト: [内容]` の形式で与えられます。\n"
            "- **[状況説明]** は、あなたがどのような状況で発言を求められているかを示します。（例: ユーザーからの入力、システムからの時報要求など）\n"
            "- **テキスト** は、具体的な発言内容や情報です。\n"
            "あなたはこれらの情報と、プロンプトで与えられる「あなたの現在の状態」を総合的に判断し、あなたのキャラクターとして最も自然な応答となるように、上記関数全てに必ず適切な引数を設定して呼び出してください。\n"
            f"{extra_rules}"
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