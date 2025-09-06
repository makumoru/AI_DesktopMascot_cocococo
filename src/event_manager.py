# src/event_manager.py

import os
import json
import threading
from datetime import datetime, timedelta
from configparser import ConfigParser

class EventManager:
    """
    アプリケーション全体のイベントを管理するクラス。
    イベント定義の読み込み、トリガーの監視、進行状況の永続化を行う。
    """

    def __init__(self, mascot_app):
        """
        EventManagerを初期化します。
        
        Args:
            mascot_app (DesktopMascot): アプリケーションのメインインスタンス。
        """
        self.app = mascot_app
        self.events_data = {}
        self.progress_data_map = {}
        self.flag_data_map = {} # {char_id: {flag_name: value}}
        self.lock = threading.RLock()

        # 起動時に全キャラクターの進行状況ファイルをチェック＆ロードする
        for char in self.app.characters:
            if char:
                self._ensure_progress_file_exists(char)
                self.load_character_data(char)
        
        self.load_all_events()

    def _get_progress_file_path(self, character):
        """キャラクターごとの進行状況ファイルのパスを返すヘルパーメソッド。"""
        return os.path.join(character.character_dir, "event_progress.ini")

    def _ensure_progress_file_exists(self, character):
        """キャラクターごとの進行状況ファイルが存在しない場合に空のファイルを作成する。"""
        filepath = self._get_progress_file_path(character)
        if not os.path.exists(filepath):
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    # [Flags]セクションを初期状態で作成しておく
                    f.write('[Flags]\n')
            except Exception as e:
                print(f"イベント進行状況ファイル ({character.name}) の作成に失敗: {e}")

    def load_character_data(self, character):
        """キャラクターごとの進行状況とフラグを読み込む。"""
        with self.lock:
            char_id = character.original_id
            filepath = self._get_progress_file_path(character)
            
            progress_parser = ConfigParser()
            # 大文字と小文字を区別するように設定
            progress_parser.optionxform = str

            progress_parser.read(filepath, encoding='utf-8')
            self.progress_data_map[char_id] = progress_parser
            
            # フラグを読み込む
            flags = {}
            if progress_parser.has_section('Flags'):
                for flag_name, value in progress_parser.items('Flags'):
                    flags[flag_name] = value
            self.flag_data_map[char_id] = flags
            print(f"[{character.name}] のイベント進行状況とフラグを読み込みました。")

    def save_flags(self, character):
        """キャラクターごとのフラグをファイルに書き込む。"""
        with self.lock:
            char_id = character.original_id
            progress_parser = self.progress_data_map.get(char_id)
            if not progress_parser: return

            # 既存のFlagsセクションをクリアして再構築
            if progress_parser.has_section('Flags'):
                progress_parser.remove_section('Flags')
            progress_parser.add_section('Flags')

            for flag_name, value in self.flag_data_map.get(char_id, {}).items():
                progress_parser.set('Flags', flag_name, str(value))
            
            filepath = self._get_progress_file_path(character)
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    progress_parser.write(f)
            except Exception as e:
                print(f"フラグ ({character.name}) の保存に失敗: {e}")

    def set_flag(self, character, flag_name, operator, value):
        """フラグの値を設定・操作する。"""
        with self.lock:
            char_id = character.original_id
            current_flags = self.flag_data_map.setdefault(char_id, {})
            
            try:
                numeric_value = int(value)
                current_numeric_value = int(current_flags.get(flag_name, 0))
                
                if operator == '=':
                    new_value = numeric_value
                elif operator == '+':
                    new_value = current_numeric_value + numeric_value
                elif operator == '-':
                    new_value = current_numeric_value - numeric_value
                else: # 不明なオペレータ
                    return
                
                current_flags[flag_name] = str(new_value)
                self.save_flags(character)
                print(f"フラグ更新: [{character.name}] {flag_name} {operator} {value} -> {new_value}")

            except (ValueError, TypeError):
                print(f"警告: フラグ操作の値が不正です (flag:{flag_name}, value:{value})")

    def evaluate_conditions(self, character, condition_groups) -> bool:
        """
        条件グループ（ORで結合されたAND条件リスト）を評価する汎用メソッド。
        [[A and B], [C and D]] -> (A and B) or (C and D)
        """
        if not condition_groups: return True # 条件がなければ常にTrue

        for group in condition_groups:
            if self._evaluate_condition_group(character, group):
                return True # いずれかのグループがTrueなら全体もTrue
        return False

    def _evaluate_condition_group(self, character, conditions) -> bool:
        """単一の条件グループ（ANDで結合された条件リスト）を評価する。"""
        for cond in conditions:
            if not self._check_single_condition(character, cond):
                return False # 1つでもFalseならグループ全体もFalse
        return True

    def _check_single_condition(self, character, condition) -> bool:
        """単一の条件を評価する。"""
        cond_type = condition.get("type")
        char_flags = self.flag_data_map.get(character.original_id, {})
        try:
            if cond_type == "favorability_above":
                return character.favorability >= int(condition.get("value"))
            if cond_type == "favorability_below":
                return character.favorability <= int(condition.get("value"))
            
            flag_name = condition.get("flag")
            # フラグ名が必須の条件で、フラグ名が指定されていなければFalse
            if not flag_name and cond_type not in ("favorability_above", "favorability_below"):
                 return False

            # 数値比較系
            if cond_type in ("flag_equals", "flag_not_equals", "flag_above", "flag_below"):
                target_value = int(condition.get("value"))
                # フラグが存在しない場合はデフォルト値0として扱う
                current_value = int(char_flags.get(flag_name, "0"))
                if cond_type == "flag_equals": return current_value == target_value
                if cond_type == "flag_not_equals": return current_value != target_value
                if cond_type == "flag_above": return current_value > target_value
                if cond_type == "flag_below": return current_value < target_value
            
            # 存在チェック系
            if cond_type == "flag_exists":
                return flag_name in char_flags
            if cond_type == "flag_not_exists":
                return flag_name not in char_flags

        except (ValueError, TypeError, KeyError):
            # 型変換エラーやキーエラーは条件不一致とみなす
            return False
        # どの条件タイプにも一致しなかった場合
        return False

    def load_all_events(self):
        """全キャラクターのeventsフォルダからイベント定義を読み込む。"""
        with self.lock:
            self.events_data.clear()
            for char in self.app.characters:
                if not char: continue
                
                char_id = char.original_id
                self.events_data[char_id] = {}
                events_dir = os.path.join(char.character_dir, "events")
                
                if not os.path.isdir(events_dir):
                    continue
                
                for filename in os.listdir(events_dir):
                    if filename.endswith(".json"):
                        try:
                            filepath = os.path.join(events_dir, filename)
                            with open(filepath, 'r', encoding='utf-8') as f:
                                event_data = json.load(f)
                                event_id = event_data.get("id")
                                if event_id:
                                    self.events_data[char_id][event_id] = event_data
                        except (json.JSONDecodeError, KeyError) as e:
                            print(f"警告: イベントファイル '{filename}' の読み込みに失敗: {e}")
            print(f"全イベントの読み込み完了。{sum(len(v) for v in self.events_data.values())}件のイベントをロードしました。")

    def load_progress(self, character):
        """キャラクターごとの進行状況ファイルから実行履歴を読み込む。"""
        with self.lock:
            char_id = character.original_id
            filepath = self._get_progress_file_path(character)
            
            progress_parser = ConfigParser()
            progress_parser.read(filepath, encoding='utf-8')
            self.progress_data_map[char_id] = progress_parser

    def save_progress(self, character):
        """キャラクターごとの進行状況をファイルに書き込む。"""
        with self.lock:
            char_id = character.original_id
            filepath = self._get_progress_file_path(character)
            
            if char_id in self.progress_data_map:
                try:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        self.progress_data_map[char_id].write(f)
                except Exception as e:
                    print(f"イベント進行状況 ({character.name}) の保存に失敗: {e}")

    def record_event_completion(self, char_id: str, event_id: str):
        """イベントの完了をキャラクターごとに記録する。"""
        with self.lock:
            # 該当キャラクターのConfigParserを取得
            progress_parser = self.progress_data_map.get(char_id)
            if not progress_parser: return

            # 記録するセクション名はイベントIDだけで良い
            section_name = event_id
            if not progress_parser.has_section(section_name):
                progress_parser.add_section(section_name)
            
            now_iso = datetime.now().isoformat()
            progress_parser.set(section_name, "last_executed", now_iso)

            # DesktopMascotからキャラクターインスタンスを探して保存
            target_char = next((c for c in self.app.characters if c and c.original_id == char_id), None)
            if target_char:
                self.save_progress(target_char)
                print(f"イベント完了を記録: [{target_char.name} - {section_name}]")

    def check_triggers(self):
        """全キャラクターの全イベントトリガーを監視し、条件を満たせばイベントを開始する。"""
        # イベント中や処理中は新たなイベントを開始しない
        if self.app.is_event_running or self.app.is_processing_lock.locked():
            return

        for char in self.app.characters:
            if not char: continue
            
            char_id = char.original_id
            if char_id not in self.events_data: continue

            for event_id, event_data in self.events_data[char_id].items():
                if self._is_event_ready_to_run(char, event_data):
                    # イベントを開始できると判断したら、DesktopMascotに処理を移譲
                    print(f"トリガー検知！ イベント '{event_id}' を開始します。")
                    self.app.start_event(char, event_data)
                    return # 同時に複数のイベントは開始しない

    def _is_event_ready_to_run(self, char, event_data) -> bool:
        """指定されたイベントが現在実行可能かを判定する。"""
        event_id = event_data.get("id")
        trigger_groups = event_data.get("triggers") # 古い "trigger" から "triggers" に変更
        if not self.evaluate_conditions(char, trigger_groups):
            return False
        
        progress_parser = self.progress_data_map.get(char.original_id)
        if not progress_parser: return True

        section_name = event_id
        if not progress_parser.has_section(section_name):
            return True

        if not event_data.get("repeatable", False):
            return False

        try:
            last_executed_str = progress_parser.get(section_name, "last_executed")
            last_executed_time = datetime.fromisoformat(last_executed_str)
            cooldown_delta = self._parse_cooldown(event_data.get("cooldown", "24h"))
            if datetime.now() < (last_executed_time + cooldown_delta):
                return False
        except Exception:
            return False

        return True

    def _parse_cooldown(self, cooldown_str: str) -> timedelta:
        """'24h', '7d', '30m'のような文字列をtimedeltaオブジェクトに変換する。"""
        value_str = cooldown_str[:-1]
        unit = cooldown_str[-1].lower()
        if not value_str.isdigit(): return timedelta(days=9999) # 不正な値
        
        value = int(value_str)
        if unit == 'h': return timedelta(hours=value)
        if unit == 'd': return timedelta(days=value)
        if unit == 'm': return timedelta(minutes=value)
        return timedelta(days=9999)

    def find_ready_event_for_character(self, character):
        """
        指定されたキャラクターについて、現在すぐに実行可能なイベントを1つ探して返す。
        見つからなければNoneを返す。
        """
        if not character: return None
        
        char_id = character.original_id
        if char_id not in self.events_data: return None

        for event_id, event_data in self.events_data[char_id].items():
            if self._is_event_ready_to_run(character, event_data):
                return event_data # 実行可能なイベントが見つかったら即座に返す
        
        return None # 見つからなかった場合