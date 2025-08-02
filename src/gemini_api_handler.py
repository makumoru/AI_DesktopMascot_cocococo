# gemini_api_handler.py

import os
import threading
from datetime import datetime

import google.generativeai as genai
from google.api_core import exceptions
from google.generativeai.types import Tool, HarmCategory, HarmBlockThreshold

class APILogManager:
    """
    APIの使用状況を日単位で記録・管理するクラス。
    config.iniで設定されたモデルごとの使用上限（レートリミット）を管理し、
    使いすぎを防ぎます。
    """
    def __init__(self, config):
        """
        APILogManagerを初期化します。

        Args:
            config (ConfigParser): アプリケーション全体の設定情報。
        """
        self.log_dir = "logs"
        os.makedirs(self.log_dir, exist_ok=True)
        # config.iniから各モデルの日間使用回数上限を読み込みます。
        self.limits = {
            'pro': config.getint('GEMINI', 'PRO_RPD'),
            'flash': config.getint('GEMINI', 'FLASH_RPD'),
            'flash-lite': config.getint('GEMINI', 'FLASH_LITE_RPD'),
            'flash-2': config.getint('GEMINI', 'FLASH_2_RPD', fallback=200),
            'flash-lite-2': config.getint('GEMINI', 'FLASH_LITE_2_RPD', fallback=200),
        }
        self.usage_counts = {key: 0 for key in self.limits.keys()} # 本日の使用回数を保持する辞書
        self.log_file_path = "" # 現在のログファイルのパス
        self.lock = threading.Lock() # スレッドセーフなアクセスのためのロック
        self._load_usage_counts() # 起動時に本日の使用回数を読み込む

    def _get_today_log_path(self):
        """本日の日付に基づいたログファイルのパスを生成します。"""
        return os.path.join(self.log_dir, f"api_usage_{datetime.now().strftime('%Y-%m-%d')}.log")

    def _load_usage_counts(self):
        """
        ログファイルから本日のAPI使用回数を読み込み、メモリにロードします。
        日付が変わった場合は、カウントをリセットし、古いログファイルを削除します。
        """
        with self.lock:
            today_log_path = self._get_today_log_path()
            # 日付が変わったかチェック
            if self.log_file_path != today_log_path:
                print(f"日付が変更されました。ログファイルを切り替えます: {today_log_path}")
                self.log_file_path = today_log_path
                self.usage_counts = {key: 0 for key in self.limits.keys()} # カウントリセット
                self._cleanup_old_logs() # 古いログを掃除

            # 本日のログファイルが存在しない場合は何もしない
            if not os.path.exists(self.log_file_path):
                return
            
            # ログファイルを1行ずつ読み込み、モデルごとの使用回数を集計
            self.usage_counts = {key: 0 for key in self.limits.keys()}
            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split(',')
                    if len(parts) >= 3:
                        model_name = parts[1]
                        if model_name in self.usage_counts:
                            self.usage_counts[model_name] += 1
            print(f"本日のAPI使用回数を読み込みました: {self.usage_counts}")

    def check_limit(self, model_key):
        """
        指定されたモデルが本日の使用上限に達していないか確認します。

        Args:
            model_key (str): 確認するモデルのキー ('pro', 'flash'など)。

        Returns:
            bool: 上限に達していなければTrue、達していればFalse。
        """
        self._load_usage_counts() # チェックの前に最新の状況を読み込む
        with self.lock:
            if self.usage_counts.get(model_key, 0) >= self.limits.get(model_key, float('inf')):
                print(f"警告: モデル '{model_key}' は本日の上限({self.limits.get(model_key)}回)に達しました。")
                return False
            return True

    def record_usage(self, model_key, character_name, message_type):
        """
        APIの使用を記録します。メモリ上のカウントを増やし、ログファイルに追記します。
        """
        with self.lock:
            # メモリ上のカウントをインクリメント
            if model_key in self.usage_counts:
                self.usage_counts[model_key] += 1
            else:
                self.usage_counts[model_key] = 1
            
            # ログファイルにエントリを追記
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_entry = f"{timestamp},{model_key},{character_name},{message_type}\n"
            try:
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    f.write(log_entry)
            except Exception as e:
                print(f"ログの書き込みに失敗しました: {e}")
    
    def get_remaining_counts(self):
        """各モデルの本日分のAPI残り使用可能回数を取得します。"""
        self._load_usage_counts()
        with self.lock:
            remaining = {
                key: self.limits.get(key, 0) - self.usage_counts.get(key, 0)
                for key in self.limits.keys()
            }
            return remaining

    def _cleanup_old_logs(self):
        """昨日以前の古いAPI使用ログファイルを削除します。"""
        for filename in os.listdir(self.log_dir):
            # 今日のログファイル以外を削除
            if filename.startswith("api_usage_") and not filename.endswith(f"{datetime.now().strftime('%Y-%m-%d')}.log"):
                try:
                    os.remove(os.path.join(self.log_dir, filename))
                except Exception as e:
                    print(f"古いログファイルの削除に失敗: {e}")

class GeminiAPIHandler:
    """
    Google Gemini APIとの通信を統括するクラス。
    会話生成、Function Calling、エラーハンドリング、モデルのフォールバックなどを担当します。
    """
    def __init__(self, config):
        """
        GeminiAPIHandlerを初期化します。

        Args:
            config (ConfigParser): アプリケーション全体の設定情報。
        """
        self.test_mode = config.getboolean('GEMINI', 'GEMINI_TEST_MODE')
        api_key = config.get('GEMINI', 'GEMINI_API_KEY')
        
        # config.iniからモデルの内部キーと実際のAPIモデル名の対応を読み込みます。
        self.model_names = {
            'pro': config.get('GEMINI', 'PRO_MODEL_NAME'),
            'flash': config.get('GEMINI', 'FLASH_MODEL_NAME'),
            'flash-lite': config.get('GEMINI', 'FLASH_LITE_MODEL_NAME'),
            'flash-2': config.get('GEMINI', 'FLASH_2_MODEL_NAME', fallback='models/gemini-2.0-flash'),
            'flash-lite-2': config.get('GEMINI', 'FLASH_LITE_2_MODEL_NAME', fallback='models/gemini-2.0-flash-lite'),
        }
        self.log_manager = APILogManager(config)

        if not self.test_mode:
            genai.configure(api_key=api_key)
        
        # APIに送信するコンテンツの安全設定を読み込みます。
        self.safety_settings = self._parse_safety_settings(config)

    def _parse_safety_settings(self, config):
        """config.iniから安全設定を読み込み、APIが要求する形式に変換します。"""
        category_map = { 'SAFETY_HARASSMENT': HarmCategory.HARM_CATEGORY_HARASSMENT, 'SAFETY_HATE_SPEECH': HarmCategory.HARM_CATEGORY_HATE_SPEECH, 'SAFETY_SEXUALLY_EXPLICIT': HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, 'SAFETY_DANGEROUS_CONTENT': HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT }
        threshold_map = { 'BLOCK_NONE': HarmBlockThreshold.BLOCK_NONE, 'BLOCK_ONLY_HIGH': HarmBlockThreshold.BLOCK_ONLY_HIGH, 'BLOCK_LOW_AND_ABOVE': HarmBlockThreshold.BLOCK_LOW_AND_ABOVE, 'BLOCK_MEDIUM_AND_ABOVE': HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE }
        safety_settings = []
        for key, category in category_map.items():
            try:
                threshold_str = config.get('GEMINI', key).upper()
                threshold = threshold_map.get(threshold_str)
                if threshold: safety_settings.append({"category": category, "threshold": threshold})
                else: print(f"警告: config.iniの不正なsafety_settings値です: {key} = {threshold_str}")
            except Exception: pass
        print(f"読み込まれた安全設定: {safety_settings}")
        return safety_settings
        
    def generate_response(self, prompt, character, message_type, requested_model_key, tools_config, conversation_log, image=None):
        """
        AIに応答生成をリクエストします。
        実際のAPI通信は別スレッドで行い、UIのフリーズを防ぎます。
        """
        threading.Thread(
            target=self._generation_thread,
            args=(prompt, character, message_type, requested_model_key, tools_config, conversation_log, image),
            daemon=True
        ).start()

    def _get_fallback_model(self, model_key):
        """
        指定されたモデルが使えない場合に、次に試すべき代替モデル（フォールバック先）を返します。
        例: 'pro'がダメなら'flash'を試す。
        """
        if model_key == 'pro': return 'flash'
        if model_key == 'flash': return 'flash-lite'
        if model_key == 'flash-2': return 'flash-lite-2'
        return None # これ以上フォールバック先がない場合はNone

    def _generation_thread(self, prompt, character, message_type, requested_model_key, tools_config, conversation_log, image=None):
        """
        【別スレッドで実行される】API通信の本体。
        プロンプトを組み立て、APIを呼び出し、結果をキャラクターコントローラーに返します。
        レートリミットやエラー発生時には、自動的に下位モデルに切り替えて再試行します。
        """
        if self.test_mode:
            import random
            print(f"[{character.name}] [テストモード] Gemini API呼び出しをスキップします。")
            
            # ダミーの応答を生成
            final_text = "" # テストモードではFunction Callを使うのでテキストは空
            dummy_speech = f"これはテストモードの応答です。({message_type}だよ)"
            dummy_emotion = random.choice(["joy", "fun", "normal", "troubled"])
            
            function_calls = [
                {"name": "generate_speech", "args": {"speech_text": dummy_speech}},
                {"name": "change_emotion", "args": {"emotion": dummy_emotion}}
            ]
            
            # 2人モードで、起動挨拶や自動発話の場合、ラリーを継続させるテストも入れる
            if character.partner and message_type in ["起動挨拶", "自動発言"]:
                if random.choice([True, False]):
                    print("[テストモード] 相方にターンを渡します。")
                    function_calls.append({"name": "pass_turn_to_partner", "args": {"continue_rally": True}})

            # ダミー応答をキャラクターに渡して処理を完了させる
            character.handle_gemini_response(final_text, function_calls)
            return

        current_model_key = requested_model_key
        
        # 使用可能なモデルがなくなるまでループ
        while current_model_key:
            # 1. 使用回数上限をチェック
            if not self.log_manager.check_limit(current_model_key):
                print(f"モデル '{current_model_key}' の上限超過。フォールバックします。")
                current_model_key = self._get_fallback_model(current_model_key)
                continue # 次のモデルで再試行

            try:
                # 2. プロンプトの組み立て
                model_display_name = self.model_names.get(current_model_key, "不明なモデル")
                print(f"[{character.name}] がモデル '{current_model_key}' ({model_display_name}) を使用します...")
                
                log_text = "\n".join(conversation_log)
                full_prompt_text = ( f"--- 過去の会話ログ ---\n{log_text}\n--- 会話ログここまで ---\n\n"
                                     f"以上の文脈を踏まえて、以下の指示に応答してください。\n{prompt}" )

                # 3. コンテンツの準備（テキスト、画像、ツール）
                contents = []
                if image:
                    print(f"画像情報をプロンプトに添付します (モデル: {model_display_name})")
                    image_instruction = ( "\n\n--- 添付画像について ---\n"
                                          "添付した画像は、ユーザーが見ている現在のPC画面のスクリーンショットです。"
                                          "この視覚情報をあなたの思考と応答に含めてください。" )
                    full_prompt_text += image_instruction
                    contents = [full_prompt_text, image]
                else:
                    contents = [full_prompt_text]

                tools_list = None
                if tools_config and tools_config[0].get('function_declarations'):
                    function_declarations = tools_config[0]['function_declarations']
                    tools_list = [Tool(function_declarations=function_declarations)]

                # 4. APIモデルのインスタンス化
                model = genai.GenerativeModel(
                    model_name=model_display_name,
                    system_instruction=character.system_instruction, # キャラクターの基本設定
                    tools=tools_list, # Function Calling用のツール
                    safety_settings=self.safety_settings
                )
                
                # 5. APIリクエストの実行
                response = model.generate_content(contents)
                
                # 6. レスポンスの解析
                final_text = ""
                function_calls = []
                # 応答が空でないことを確認し、パートごとに解析
                if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        # プレーンテキスト部分があれば取得（Function Callingが正常なら空のはず）
                        if hasattr(part, 'text') and part.text:
                            final_text += part.text
                        # 関数呼び出し部分があれば取得
                        if hasattr(part, 'function_call') and part.function_call:
                            function_calls.append({ "name": part.function_call.name, "args": dict(part.function_call.args) })
                
                print(f"[{character.name}] 応答取得: テキスト='{final_text[:50]}...', 関数呼び出し={len(function_calls)}件")
                
                if(len(function_calls)>0):
                    for item in function_calls:
                        print(item)

                # 7. 成功時の処理
                self.log_manager.record_usage(current_model_key, character.name, message_type)
                # 解析結果をキャラクターコントローラーに渡して後続処理を依頼
                character.handle_gemini_response(final_text, function_calls)
                return # 成功したのでループを抜ける

            except exceptions.ResourceExhausted as e:
                # APIのレートリミットに達した場合のエラー
                print(f"エラー: モデル '{current_model_key}' でリソース上限エラーが発生しました ({e})。フォールバックします。")
                current_model_key = self._get_fallback_model(current_model_key)
            
            except Exception as e:
                # その他の予期せぬエラー
                print(f"致命的なエラー: モデル '{current_model_key}' でのAPI呼び出し中に予期せぬエラーが発生しました: {e}")
                error_message = character.msg_on_specific_model_failed.format(model_key=current_model_key)
                character.handle_gemini_response(error_message, [])
                return # 回復不能なエラーなので処理を終了
        
        # 全てのモデルで失敗した場合
        print("全モデルでエラーまたは上限超過のため、処理を中断します。")
        character.handle_gemini_response(character.msg_on_all_models_failed, [])