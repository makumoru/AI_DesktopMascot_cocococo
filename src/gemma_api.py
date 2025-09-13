# src/gemma_api.py

from google.generativeai.types import HarmCategory, HarmBlockThreshold
from google import genai
import re
import random

class GemmaAPI:
    """
    GoogleのGemmaモデルを使用して、キャラクターの感情分析を行うためのAPIハンドラ。
    会話ログを入力として、キャラクターの感情（喜怒哀楽など）をパーセンテージで出力します。
    """
    # 感情分析で参照する直近の会話ログの最大件数。多すぎると文脈が複雑になりすぎるため制限します。
    CONVERSATION_LOG_LIMIT = 5

    def __init__(self, config, gemma_api_key, gemma_model_name, gemma_test_mode, mascot):
        """
        GemmaAPIを初期化します。

        Args:
            config (ConfigParser): アプリケーション全体の設定情報。
            gemma_api_key (str): Gemma APIの認証キー。
            gemma_model_name (str): 使用するGemmaモデルの名前。
            gemma_test_mode (bool): APIを実際に呼び出すかどうかのテストモードフラグ。
            mascot (CharacterController): このAPIハンドラを使用するキャラクターのコントローラー。
        """
        self.gemma_test_mode = gemma_test_mode
        self.mascot = mascot # ログ出力などでキャラクター名を識別するために使用
        
        # 感情の連続性を表現するため、前回の感情分析結果を保持します。
        # これにより、突然感情がリセットされることなく、滑らかに変化させることができます。
        self.previous_emotion_values = {"喜": 30, "怒": 20, "哀": 10, "楽": 40, "困": 0, "驚": 0, "照": 0, "恥": 0}
        
        self.model_name = gemma_model_name
        self.safety_settings = self._parse_safety_settings(config)
        
        # テストモードでない場合のみ、APIクライアントを初期化します。
        if not self.gemma_test_mode:
            self.client = genai.Client(api_key=gemma_api_key.strip())

    def _parse_safety_settings(self, config):
        """
        config.iniからGemini/Gemma共通の安全設定を読み込み、APIで使える形式に変換します。
        不適切なコンテンツの生成をブロックするレベルを設定します。
        """
        category_map = {
            'SAFETY_HARASSMENT': HarmCategory.HARM_CATEGORY_HARASSMENT,
            'SAFETY_HATE_SPEECH': HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            'SAFETY_SEXUALLY_EXPLICIT': HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            'SAFETY_DANGEROUS_CONTENT': HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT
        }
        threshold_map = {
            'BLOCK_NONE': HarmBlockThreshold.BLOCK_NONE,
            'BLOCK_ONLY_HIGH': HarmBlockThreshold.BLOCK_ONLY_HIGH,
            'BLOCK_LOW_AND_ABOVE': HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            'BLOCK_MEDIUM_AND_ABOVE': HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE
        }
        
        safety_settings = []
        for key, category in category_map.items():
            try:
                threshold_str = config.get('GEMINI', key).upper()
                threshold = threshold_map.get(threshold_str)
                if threshold:
                    safety_settings.append({"category": category, "threshold": threshold})
                else:
                    print(f"警告: config.iniの不正なsafety_settings値です: {key} = {threshold_str}")
            except Exception:
                pass # 設定がない場合はスキップ
        return safety_settings

    def analyze_emotion(self, conversation_log):
        """
        引数で受け取った会話ログをもとに、キャラクターの感情を分析します。
        Geminiが感情を"normal"と指定した場合のフォールバックとして使用されます。

        Args:
            conversation_log (list[str]): main.pyで整形された会話ログのリスト。

        Returns:
            dict: 感情名をキー、パーセンテージを値とする辞書。例: {"喜": 80, "怒": 0, ...}
        """
        # 感情分析では、文脈を絞るために直近のログのみを参照します。
        recent_log = conversation_log[-self.CONVERSATION_LOG_LIMIT:]
        conversation_log_text = "\n".join(recent_log)
        
        # 会話ログが空の場合は、APIを呼び出さずに前回の感情値をそのまま返します。
        if not conversation_log_text.strip():
            print(f"[{self.mascot.name}] 会話ログが空のため、感情分析をスキップ。")
            return self.previous_emotion_values

        # --- Gemmaモデルに渡すプロンプトを構築 ---
        # 役割、目的、入力情報、出力形式を明確に指示します。
        prompt = f"""
            以下の情報をもとに、「前回の感情値」と「会話ログ」の情報から「{self.mascot.name}の最後の発言時の感情」を考察し、
            喜:n% 怒:n% 哀:n% 楽:n% 困:n% 驚:n% 照:n% 恥:n%
            の8パラメータを%表示で出力してください。出力するのは各項目の%のみです。その他の反応は一切出力しないでください。
            ────
            ・前回の感情値: {self.format_emotions(self.previous_emotion_values)}
            ・会話ログ: {conversation_log_text}
            ────
        """
        
        # テストモードが有効な場合、APIを呼び出さずにダミーの感情データを生成します。
        if self.gemma_test_mode:
            print(f"[{self.mascot.name}] [テストモード] 感情分析をシミュレート。")
            test_emotions = {"喜": 0, "怒": 0, "哀": 0, "楽": 0, "困": 0, "驚": 0, "照": 0, "恥": 0}
            random_emotion = random.choice(list(test_emotions.keys()))
            test_emotions[random_emotion] = random.randint(10, 100)
            self.previous_emotion_values = test_emotions
            return test_emotions

        try:
            print(f"[{self.mascot.name}] Gemmaに感情分析をリクエストします...")
            # --- API呼び出し実行 ---
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                # safety_settings=self.safety_settings # 必要に応じて安全設定を有効化
            )
            print(f"[{self.mascot.name}] Gemmaからの生応答: {response.text}")

            # --- 応答の解析と正規化 ---
            # APIからのテキスト応答をパースして辞書形式に変換します。
            emotion_percentages = self.parse_emotion_response(response.text)
            # パースした値の合計が100%になるように正規化（ノーマライズ）します。
            normalized_percentages = self.normalize_emotions(emotion_percentages)
            print(f"[{self.mascot.name}] Gemmaからの正規化後感情分析結果: {normalized_percentages}")

            # 分析結果が有効な場合（合計が0より大きい）、今回の結果を次回のために保存し、値を返します。
            if normalized_percentages and sum(normalized_percentages.values()) > 0:
                self.previous_emotion_values = normalized_percentages
                return normalized_percentages
            else:
                # 分析に失敗した場合は、前回の感情値を返します。
                return self.previous_emotion_values
                
        except Exception as e:
            # API呼び出し中に何らかのエラーが発生した場合は、その旨をログに出力し、前回の感情値を返します。
            print(f"[{self.mascot.name}] Gemma APIでの感情分析に失敗: {e}")
            return self.previous_emotion_values

    def format_emotions(self, emotions):
        """感情の辞書を "喜:30% 怒:20% ..." のような文字列形式に変換します。プロンプト作成時に使用。"""
        return " ".join([f"{key}:{value}%" for key, value in emotions.items()])
    
    def parse_emotion_response(self, text):
        """
        APIからのテキスト応答（例: "喜: 80% 怒: 5%..."）を解析し、
        感情の辞書（例: {"喜": 80, "怒": 5, ...}）に変換します。
        正規表現を使って、多少フォーマットが崩れていても柔軟に値を抽出します。
        """
        emotions = {}
        patterns = {
            "喜": r"喜\s*:\s*(\d+)", 
            "怒": r"怒\s*:\s*(\d+)", 
            "哀": r"哀\s*:\s*(\d+)", 
            "楽": r"楽\s*:\s*(\d+)", 
            "困": r"困\s*:\s*(\d+)", 
            "驚": r"驚\s*:\s*(\d+)",
            "照": r"照\s*:\s*(\d+)",
            "恥": r"恥\s*:\s*(\d+)"
        }
        for emotion, pattern in patterns.items():
            match = re.search(pattern, text)
            # マッチすればその数値を、しなければ0を格納します。
            emotions[emotion] = int(match.group(1)) if match else 0
        return emotions
    
    @staticmethod
    def normalize_emotions(emotions):
        """
        感情の辞書を受け取り、全ての値の合計が100になるように各値を調整（正規化）します。
        これにより、AIが%を厳密に返さなくても、比率を保ったまま合計100のパーセンテージに変換できます。
        """
        total = sum(emotions.values())
        if total == 0:
            return emotions # 合計が0の場合はゼロ除算を避ける
        return {key: round(value / total * 100) for key, value in emotions.items()}