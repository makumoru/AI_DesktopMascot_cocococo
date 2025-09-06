# src/event_runner.py

class EventRunner:
    """
    単一のイベントシーケンスの進行を管理するクラス。
    """
    def __init__(self, character_controller, event_data):
        """
        EventRunnerを初期化します。
        
        Args:
            character_controller (CharacterController): イベントの主役となるキャラクター。
            event_data (dict): 実行するイベントの定義データ。
        """
        self.char_ctrl = character_controller
        self.event_data = event_data
        self.sequence = event_data.get("sequence", [])
        self.current_step = -1
        
        # ジャンプを高速化するため、ラベルとインデックスの対応表を作成
        self.label_map = {
            cmd.get("label"): i 
            for i, cmd in enumerate(self.sequence) 
            if "label" in cmd
        }

    def start(self):
        """イベントシーケンスの実行を開始する。"""
        print(f"イベント '{self.event_data.get('id')}' のシーケンスを開始します。")
        self.current_step = 0
        self._execute_current_command()

    def proceed(self):
        """次のステップへ進む。通常は「次へ」ボタンから呼び出される。"""
        if self.current_step < 0 or self.current_step >= len(self.sequence):
            self.char_ctrl.end_event()
            return

        current_command = self.sequence[self.current_step]
        
        # 1. ジャンプ先が指定されていれば、そこへ移動
        if "jump_to" in current_command:
            self.jump_to_label(current_command["jump_to"])
            return

        # 2. ジャンプ先がなければ、単純に次のステップへ
        self.current_step += 1
        
        # 3. シーケンスの終端に達したかチェック
        if self.current_step >= len(self.sequence):
            print("シーケンスの終端に到達しました。")
            self.char_ctrl.end_event()
        else:
            self._execute_current_command()

    def jump_to_label(self, label: str):
        """指定されたラベルのステップへジャンプする。"""
        if label in self.label_map:
            self.current_step = self.label_map[label]
            self._execute_current_command()
        else:
            print(f"警告: ジャンプ先のラベル '{label}' が見つかりません。イベントを終了します。")
            self.char_ctrl.end_event()

    def _execute_current_command(self):
        """現在のステップのコマンドを実行する。"""
        if not (0 <= self.current_step < len(self.sequence)):
            print("エラー: 無効なステップです。イベントを終了します。")
            self.char_ctrl.end_event()
            return
            
        command = self.sequence[self.current_step]
        command_type = command.get("type")
        params = command.get("params", {})
        
        # コマンドの種類に応じてCharacterControllerのメソッドを呼び出す
        if command_type == "dialogue":
            self.char_ctrl.execute_dialogue(params)
        elif command_type == "monologue":
            self.char_ctrl.execute_monologue(params)
        elif command_type == "choice":
            self.char_ctrl.execute_choice(params)
        elif command_type == "set_favorability":
            self.char_ctrl.execute_set_favorability(params)
            # このコマンドは自動で次に進む
            self.proceed()
        elif command_type == "add_long_term_memory":
            self.char_ctrl.execute_add_long_term_memory(params)
            # このコマンドも自動で次に進む
            self.proceed()
        elif command_type == "change_costume":
            self.char_ctrl.execute_change_costume(params)
            # このコマンドも自動で次に進む
            self.proceed()
        elif command_type == "set_flag":
            self.char_ctrl.execute_set_flag(params)
            self.proceed()
        elif command_type == "branch_on_flag":
            self.char_ctrl.execute_branch_on_flag(params)
            # このコマンドは内部でジャンプするか次に進むかを決定する
        else:
            print(f"警告: 不明なコマンドタイプ '{command_type}' です。スキップします。")
            self.proceed()
