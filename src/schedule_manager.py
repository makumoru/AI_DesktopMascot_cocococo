# src/schedule_manager.py

import os
import csv
from datetime import datetime
import threading

class Schedule:
    """個々のスケジュール情報を保持するデータクラス"""
    def __init__(self, year_str, month_str, day_str, hour_str, minute_str, content, notified_str):
        # 内部的にはワイルドカードを -1 として扱う
        self.year = -1 if year_str == '*' else int(year_str)
        self.month = -1 if month_str == '*' else int(month_str)
        self.day = -1 if day_str == '*' else int(day_str)
        self.hour = -1 if hour_str == '*' else int(hour_str)
        self.minute = -1 if minute_str == '*' else int(minute_str)
        self.content = content
        
        # CSVから読み込んだままの文字列を保持（書き戻し用）
        self.original_parts = [year_str, month_str, day_str, hour_str, minute_str, content, notified_str]
        self.is_wildcard = any(val == -1 for val in [self.year, self.month, self.day, self.hour])

    def is_due(self, now: datetime):
        """現在時刻がこのスケジュールの実行時刻に合致するか判定する"""
        if self.minute != -1 and self.minute != now.minute:
            return False
        if self.hour != -1 and self.hour != now.hour:
            return False
        if self.day != -1 and self.day != now.day:
            return False
        if self.month != -1 and self.month != now.month:
            return False
        if self.year != -1 and self.year != now.year:
            return False
        return True
    
    def get_id(self):
        """スケジュールを一意に識別するためのIDを返す"""
        return f"{self.original_parts[0]}-{self.original_parts[1]}-{self.original_parts[2]}-{self.original_parts[3]}:{self.original_parts[4]}-{self.content}"
    
    def get_execution_key(self, now: datetime):
        """
        ワイルドカードを考慮した、重複実行防止用のキーを生成する。
        例: 毎時0分の時報の場合 -> "2025-07-30-10-時報"
        """
        year = now.year if self.year == -1 else self.year
        month = now.month if self.month == -1 else self.month
        day = now.day if self.day == -1 else self.day
        hour = now.hour if self.hour == -1 else self.hour
        # 分はワイルドカードがない前提だが、念のため
        minute = now.minute if self.minute == -1 else self.minute

        # 最も細かいワイルドカードの単位でキーを生成する
        if self.hour == -1: # 毎時
             return f"key-{year}-{month}-{day}-{now.hour}"
        if self.day == -1: # 毎日
            return f"key-{year}-{month}-{now.day}-{self.hour}"
        if self.month == -1: # 毎月
            return f"key-{year}-{now.month}-{self.day}-{self.hour}"
        if self.year == -1: # 毎年
            return f"key-{now.year}-{self.month}-{self.day}-{self.hour}"
        
        # ワイルドカードがない場合
        return self.get_id()

class ScheduleManager:
    """schedule.iniの読み書きと、実行すべきスケジュールの管理を行うクラス"""
    SCHEDULE_FILE_NAME = "schedule.ini"
    # デフォルトスケジュールも新しい形式に更新
    DEFAULT_SCHEDULES = [
        ["*", "01", "01", "*", "*", "新年です！「あけましておめでとうございます！今年も素敵な一年になりますように。」といった何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "02", "14", "*", "*", "今日はバレンタインデーです。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "02", "22", "*", "*", "今日は猫の日です。「にゃーん」といった何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "03", "03", "*", "*", "今日は桃の節句、ひな祭りです。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "03", "14", "*", "*", "今日はホワイトデーです。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "04", "01", "*", "*", "今日はエイプリルフールです。何かあなたのキャラクター設定にあった噓をついて、嘘と明かしてください。", "False"],
        ["*", "05", "05", "*", "*", "今日はこどもの日です。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "07", "07", "*", "*", "今日は七夕です。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "09", "09", "*", "*", "今日は重陽の節句、大人の雛祭りの日です。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "10", "01", "*", "*", "そろそろ衣替えの時期です。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "10", "31", "*", "*", "今日はハロウィンです。「トリックオアトリート！」といった何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "11", "03", "*", "*", "今日は文化の日です。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "11", "15", "*", "*", "今日は七五三です。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "12", "13", "*", "*", "そろそろ年末に向けた大掃除の時期です。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "12", "22", "*", "*", "今日は冬至です。「ゆず湯にでも入りましょうか？」といった何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "12", "24", "*", "*", "今日はクリスマスイブです。何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "12", "25", "*", "*", "今日はクリスマスです。「メリークリスマス！」といった何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "12", "31", "*", "*", "今日は大晦日です。「1年間お疲れ様でした。」といった何かあなたのキャラクター設定にあったコメントをしてください。", "False"],
        ["*", "07", "26", "*", "*", "今日は本システム「ここここ」の初リリース記念日であり、ここここ公式キャラ「ジェミー」のお誕生日です。みんなでお祝いしましょう。", "False"],

        ["*", "*", "*", "*", "00", "毎時0分の時報です。", "False"],
        ["*", "*", "*", "07", "01", "おはようございます。今日も一日、元気に過ごしましょう。", "False"],
        ["*", "*", "*", "12", "01", "お昼の時間です。しっかり休憩してくださいね。", "False"],
        ["*", "*", "*", "15", "01", "3時のおやつの時間です。少し休憩しませんか？", "False"],
        ["*", "*", "*", "18", "01", "お疲れ様です。夕方、もう一日も終わりですね。", "False"],
        ["*", "*", "*", "22", "01", "そろそろ夜も更けてきました。ゆっくり休んで、明日に備えましょうね。", "False"]
    ]

    def __init__(self):
        self.file_path = self.SCHEDULE_FILE_NAME
        self.lock = threading.RLock()
        self._ensure_file_exists()
        self.schedules = self._load_schedules()

    def _ensure_file_exists(self):
        """schedule.iniが存在しない場合に、サンプルデータ付きで作成する"""
        if not os.path.exists(self.file_path):
            print(f"'{self.file_path}'が見つかりません。サンプルファイルを作成します。")
            try:
                with open(self.file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    # ファイルに書き込むコメントも修正
                    f.write("# 年,月,日,時,分,内容,通知済みフラグ\n")
                    f.write("# 特定の項目を毎回実行したい場合は、ワイルドカードとして '*' (アスタリスク) を使用してください。\n")
                    f.write("# 例: *,*,*,15,00 は「毎日の15時0分」を意味します。\n")
                    f.write("# 例: 2026,1,1,0,0 は「2026年1月1日 午前0時0分」を意味します。\n")
                    writer.writerows(self.DEFAULT_SCHEDULES)
            except Exception as e:
                print(f"'{self.file_path}'の作成に失敗しました: {e}")

    def _load_schedules(self):
        """schedule.iniからスケジュールを読み込む"""
        schedules = []
        with self.lock:
            try:
                with open(self.file_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(line for line in f if not line.strip().startswith('#'))
                    for i, row in enumerate(reader):
                        if len(row) == 7:
                            # Scheduleクラスに渡す前に、前後の空白を削除
                            cleaned_row = [part.strip() for part in row]
                            schedules.append(Schedule(*cleaned_row))
                        else:
                            print(f"警告: {self.file_path} の {i+1}行目の書式が不正です。無視します: {row}")
            except Exception as e:
                print(f"'{self.file_path}'の読み込みに失敗しました: {e}")
        return schedules

    def get_due_schedules(self, now: datetime):
        """現在時刻に実行すべき未通知のスケジュールリストを返す"""
        self.schedules = self._load_schedules() # 毎回ファイルを読み直して最新の状態を反映
        due_list = []
        for schedule in self.schedules:
            is_notified_str = schedule.original_parts[6].strip().lower()
            is_notified = (is_notified_str == 'true')

            # ワイルドカードでない、かつ通知済みのスケジュールはスキップ
            if not schedule.is_wildcard and is_notified:
                continue

            if schedule.is_due(now):
                due_list.append(schedule)
        return due_list

    def mark_as_notified(self, notified_schedule: Schedule):
        """指定されたスケジュールの通知済みフラグをTrueに更新する"""
        # ワイルドカードを含むスケジュールは「通知済み」にしない
        if notified_schedule.is_wildcard:
            return

        with self.lock:
            # ファイルを直接読み書きして更新する
            all_lines = []
            header_lines = []
            data_lines = []
            
            try:
                # まず全行を読み込む
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    all_lines = f.readlines()

                # ヘッダーとデータ行を分離
                for line in all_lines:
                    if line.strip().startswith('#'):
                        header_lines.append(line)
                    elif line.strip(): # 空行は無視
                        data_lines.append(line)

                # データ行を更新
                updated_data_lines = []
                for line in data_lines:
                    try:
                        parts = [p.strip() for p in line.strip().split(',', 6)]
                        temp_id = f"{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}:{parts[4]}-{parts[5]}"
                        
                        if temp_id == notified_schedule.get_id():
                            parts[6] = 'True'
                            updated_data_lines.append(",".join(parts) + '\n')
                        else:
                            updated_data_lines.append(line)
                    except IndexError:
                        updated_data_lines.append(line) # 不正な行はそのまま

                # ファイルに書き戻す
                with open(self.file_path, 'w', encoding='utf-8') as f:
                    f.writelines(header_lines)
                    f.writelines(updated_data_lines)
                
                print(f"スケジュールを更新しました: {notified_schedule.content}")
            except Exception as e:
                print(f"'{self.file_path}'の書き込みに失敗しました: {e}")
    
    def get_daily_events(self, target_date: datetime.date):
        """
        指定された日付の「終日イベント」（時分がワイルドカード）のリストを返す。
        """
        self.schedules = self._load_schedules() # 最新の情報を読み込む
        daily_event_list = []
        for schedule in self.schedules:
            # 終日イベント（時・分がワイルドカード）でなければスキップ
            if not (schedule.hour == -1 and schedule.minute == -1):
                continue
            
            # 日付が合致するか判定（is_dueを参考に、日付部分のみで判定）
            date_matches = True
            if schedule.day != -1 and schedule.day != target_date.day:
                date_matches = False
            if schedule.month != -1 and schedule.month != target_date.month:
                date_matches = False
            if schedule.year != -1 and schedule.year != target_date.year:
                date_matches = False

            if date_matches:
                is_notified_str = schedule.original_parts[6].strip().lower()
                is_notified = (is_notified_str == 'true')
                # ワイルドカードでない、かつ通知済みの終日イベントはスキップ
                if not schedule.is_wildcard and is_notified:
                    continue
                
                daily_event_list.append(schedule)
                
        return daily_event_list

    def overwrite_schedules(self, new_schedules_data):
        """
        GUIから受け取ったスケジュールデータで schedule.ini を上書きする。
        """
        with self.lock:
            try:
                # 既存のヘッダーコメントを保持
                header_lines = []
                if os.path.exists(self.file_path):
                    with open(self.file_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.strip().startswith('#'):
                                header_lines.append(line)
                            else:
                                break # データ行が始まったら終了

                # ファイルに書き込む
                with open(self.file_path, 'w', newline='', encoding='utf-8') as f:
                    # ヘッダーを書き戻す
                    if header_lines:
                        f.writelines(header_lines)
                    else: # ヘッダーがなかった場合（念のため）
                        f.write("# 年,月,日,時,分,内容,通知済みフラグ\n")

                    writer = csv.writer(f)
                    writer.writerows(new_schedules_data)
                
                print("スケジュールファイルをGUIから更新しました。")
            except Exception as e:
                print(f"スケジュールファイルの上書き保存に失敗しました: {e}")
