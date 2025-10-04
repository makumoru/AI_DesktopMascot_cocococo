# src/schedule_editor.py

import tkinter as tk
from tkinter import ttk, messagebox, font
import calendar
from datetime import datetime
from typing import TYPE_CHECKING

# 循環参照を避けるための型チェック用インポート
if TYPE_CHECKING:
    from src.character_controller import CharacterController

class ScheduleEditorWindow(tk.Toplevel):
    """スケジュールをGUIで編集するためのメインウィンドウ"""
    def __init__(self, parent, schedule_manager, app, character_controller: 'CharacterController'):
        super().__init__(parent)
        self.schedule_manager = schedule_manager
        self.item_data = {}
        self.app = app # appインスタンスを保持

        self.character_controller = character_controller
        theme = character_controller.mascot_app.theme_manager

        self.title("スケジュール管理")
        # ウィンドウサイズをスクリーンサイズに対する比率で設定
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        win_width = int(screen_width * 0.45)
        win_height = int(screen_height * 0.5)
        self.geometry(f"{win_width}x{win_height}")

        self.transient(parent)
        self.grab_set()

        self.configure(bg=theme.get('bg_main'))

        # --- ttkウィジェットのスタイルを設定 ---
        style = ttk.Style(self)
        
        style.map('Custom.Treeview',
                  background=[('selected', theme.get('selected_bg'))],
                  foreground=[('selected', theme.get('selected_text'))])
        
        # Treeviewのフォントも基準単位で指定
        style.configure("Custom.Treeview", 
                        #background=theme.get('list_bg'), 
                        #fieldbackground=theme.get('list_bg'), 
                        #foreground=theme.get('list_text'),
                        rowheight=int(app.base_font_size * 2),
                        font=app.font_normal)

        # Treeviewのヘッダーのスタイルを基準単位で定義
        heading_font = font.Font(font=app.font_normal)
        heading_font.configure(weight="bold")
        style.configure("Custom.Treeview.Heading", 
                        #background=theme.get('list_header_bg'), 
                        #foreground=theme.get('list_header_text'),
                        font=heading_font)
        
        style.configure("TFrame", background=theme.get('bg_main'))
        style.configure("TButton", 
                        #background=theme.get('list_bg'),
                        #foreground=theme.get('list_text'),
                        font=app.font_normal)
        style.configure("TScrollbar", background=theme.get('bg_accent'))

        # --- Treeview (スケジュール一覧) ---
        tree_frame = ttk.Frame(self)
        tree_frame.pack(expand=True, fill="both", padx=app.padding_normal, pady=app.padding_normal)

        columns = ("year", "month", "day", "hour", "minute", "content")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", style="Custom.Treeview")
        
        self.tree.heading("year", text="年")
        self.tree.heading("month", text="月")
        self.tree.heading("day", text="日")
        self.tree.heading("hour", text="時")
        self.tree.heading("minute", text="分")
        self.tree.heading("content", text="内容")
        
        # カラム幅を基準フォントサイズに合わせて動的に設定
        base_col_width = app.base_font_size * 5
        self.tree.column("year", width=base_col_width, anchor="center", stretch=tk.NO)
        self.tree.column("month", width=base_col_width, anchor="center", stretch=tk.NO)
        self.tree.column("day", width=base_col_width, anchor="center", stretch=tk.NO)
        self.tree.column("hour", width=base_col_width, anchor="center", stretch=tk.NO)
        self.tree.column("minute", width=base_col_width, anchor="center", stretch=tk.NO)
        content_min_width = int(base_col_width * 3)
        self.tree.column("content", width=win_width, minwidth=content_min_width)
        
        self.tree.tag_configure('notified', foreground=theme.get('info_text'))
        
        v_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # --- ボタンフレーム ---
        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x", padx=app.padding_normal, pady=(0, app.padding_normal))
        
        button_padding = app.padding_small
        ttk.Button(button_frame, text="追加", command=self.add_schedule).pack(side="left", padx=button_padding)
        ttk.Button(button_frame, text="編集", command=self.edit_schedule).pack(side="left", padx=button_padding)
        ttk.Button(button_frame, text="削除", command=self.delete_schedule).pack(side="left", padx=button_padding)
        
        ttk.Button(button_frame, text="キャンセル", command=self.destroy).pack(side="right", padx=button_padding)
        ttk.Button(button_frame, text="保存して閉じる", command=self.save_and_close).pack(side="right", padx=button_padding)

        self.populate_tree()

    def _convert_to_display_values(self, original_values):
        """'*'を含むデータを日本語の表示用データに変換する"""
        display = list(original_values)
        # 年, 月, 日
        if display[0] == '*': display[0] = "毎年"
        if display[1] == '*': display[1] = "毎月"
        if display[2] == '*': display[2] = "毎日"
        
        # 時, 分
        is_daily_event = (display[3] == '*' and display[4] == '*')
        if is_daily_event:
            display[3] = "終日"
            display[4] = "" # 分のカラムは空にする
        elif display[3] == '*':
            display[3] = "毎時"
            
        return tuple(display)
   
    def _is_future_event(self, schedule_parts):
        """【新設】指定されたスケジュールが未来の予定か、繰り返し予定かを判定する"""
        # ケース1: 繰り返し予定（年,月,日,時のいずれかが'*'）は、常に「未来の予定」とみなす
        if '*' in schedule_parts[:4]:
            return True

        # ケース2: 特定の日時が指定されている場合
        try:
            now = datetime.now()
            event_time = datetime(
                int(schedule_parts[0]), # 年
                int(schedule_parts[1]), # 月
                int(schedule_parts[2]), # 日
                int(schedule_parts[3]), # 時
                int(schedule_parts[4])  # 分
            )
            # 現在時刻より後であれば「未来の予定」
            return event_time > now
        except (ValueError, TypeError):
            # 不正な値などで日時に変換できない場合は、未来ではないと判断
            return False

    def _convert_to_original_values(self, display_values):
        """【新設】日本語表示を'*'を含む元のデータ形式に逆変換する"""
        original = list(display_values)
        # 年, 月, 日
        if original[0] == "毎年": original[0] = '*'
        if original[1] == "毎月": original[1] = '*'
        if original[2] == "毎日": original[2] = '*'
        
        # 時, 分
        if original[3] == "終日":
            original[3] = '*'
            original[4] = '*'
        elif original[3] == "毎時":
            original[3] = '*'
            
        return tuple(original)

    def populate_tree(self):
        """Treeviewに表示用データ、内部辞書に元データを格納する"""
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.item_data.clear()
            
        schedules = self.schedule_manager._load_schedules()
        for schedule in schedules:
            original_data = schedule.original_parts
            display_values = self._convert_to_display_values(original_data[:-1])
            is_notified = original_data[6].strip().lower() == 'true'
            tag_to_apply = 'notified' if is_notified else ''
            
            # Treeviewに行を追加し、その行のユニークなID (iid) を取得
            item_id = self.tree.insert("", "end", values=display_values, tags=[tag_to_apply])
            # 取得したIDをキーとして、内部辞書に元のデータを保存
            self.item_data[item_id] = original_data

    def add_schedule(self):
        """スケジュール追加後、内部辞書にもデータを追加する"""
        dialog = ScheduleInputDialog(self, self.app, character_controller=self.character_controller)
        if dialog.result:
            new_original_data = dialog.result + ['False'] # notifiedフラグを追加
            display_values = self._convert_to_display_values(dialog.result)

            item_id = self.tree.insert("", "end", values=display_values)
            self.item_data[item_id] = new_original_data


    def edit_schedule(self):
        """編集後のデータに応じて、完了フラグを自動でリセットする"""
        selected_item_id = self.tree.focus()
        if not selected_item_id:
            messagebox.showwarning("警告", "編集するスケジュールを選択してください。", parent=self)
            return
        
        original_data = self.item_data[selected_item_id]
                
        # ダイアログにappインスタンスと初期データを渡す
        dialog = ScheduleInputDialog(self, self.app, initial_data=original_data[:-1], character_controller=self.character_controller)
        
        if dialog.result:
            # 完了フラグのリセット判定
            original_was_notified = original_data[6].strip().lower() == 'true'
            new_data_is_future = self._is_future_event(dialog.result)

            final_notified_flag = original_data[6] # まずは元のフラグを引き継ぐ
            # もし「完了済み」で、かつ編集後のデータが「未来の予定」なら
            if original_was_notified and new_data_is_future:
                final_notified_flag = 'False' # 「未完了」にリセットする
            
            # 編集後のデータを準備
            new_original_data = dialog.result + [final_notified_flag]
            display_values = self._convert_to_display_values(dialog.result)
            
            # 内部辞書とTreeview表示の両方を更新
            self.item_data[selected_item_id] = new_original_data
            self.tree.item(selected_item_id, values=display_values)
            
            # グレーアウト状態も更新
            is_now_notified = final_notified_flag.strip().lower() == 'true'
            self.tree.item(selected_item_id, tags=['notified' if is_now_notified else ''])

    def delete_schedule(self):
        """Treeviewと内部辞書の両方からデータを削除する"""
        selected_item_id = self.tree.focus()
        if not selected_item_id:
            messagebox.showwarning("警告", "削除するスケジュールを選択してください。", parent=self)
            return

        if messagebox.askyesno("確認", "本当にこのスケジュールを削除しますか？", parent=self):
            # 内部辞書から削除
            if selected_item_id in self.item_data:
                del self.item_data[selected_item_id]
            # Treeviewから削除
            self.tree.delete(selected_item_id)
            
    def save_and_close(self):
        """内部辞書の値からファイルに保存する"""
        # 内部辞書に保存されている全データを取得
        new_schedules = list(self.item_data.values())
            
        self.schedule_manager.overwrite_schedules(new_schedules)
        self.destroy()

    def reload_theme(self):
        """
        ウィンドウ全体のテーマカラーを再適用します。
        """
        theme = self.app.theme_manager
        self.configure(bg=theme.get('bg_main'))
        
        style = ttk.Style(self)
        style.map('Custom.Treeview',
                  background=[('selected', theme.get('selected_bg'))],
                  foreground=[('selected', theme.get('selected_text'))])
        style.configure("Custom.Treeview", 
                        foreground=theme.get('list_text'),
                        background=theme.get('list_bg'), 
                        fieldbackground=theme.get('list_bg'))
        style.configure("Custom.Treeview.Heading", 
                        foreground=theme.get('list_header_text'),
                        background=theme.get('list_header_bg'))
        
        style.configure("TFrame", background=theme.get('bg_main'))
        style.configure("TButton", background=theme.get('bg_main'))
        style.configure("TScrollbar", background=theme.get('bg_accent'))
        
        self.tree.tag_configure('notified', foreground=theme.get('info_text'))

class ScheduleInputDialog(tk.Toplevel):
    """スケジュールを追加・編集するためのダイアログ"""
    def __init__(self, parent, app, initial_data=None, character_controller: 'CharacterController' = None):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self.app = app # appインスタンスを保持

        self.title("スケジュールの追加・編集" if initial_data else "スケジュールの追加")

        # --- character_controller が渡されていることを確認 ---
        if not character_controller:
            # 万が一渡されなかった場合のエラー処理
            raise ValueError("ScheduleInputDialogにはcharacter_controllerが必要です。")
        theme = character_controller.mascot_app.theme_manager        
        self.configure(bg=theme.get('bg_main'))

        style = ttk.Style(self)
        style.configure("TFrame", background=theme.get('bg_main'))
        style.configure("TLabel", background=theme.get('bg_main'), foreground=theme.get('bg_text'), font=app.font_normal)
        style.configure("TButton", font=app.font_normal) # ボタンはテーマから色を取得するのでフォントのみ
        style.configure("TCheckbutton", background=theme.get('bg_main'), foreground=theme.get('bg_text'), font=app.font_normal)
        #style.configure("CustomDialog.TEntry", fieldbackground=theme.get('bg_entry'), foreground=theme.get('bg_text'), insertcolor=theme.get('bg_text'))
        
        # --- 入力フィールド ---
        frame = ttk.Frame(self, padding=app.padding_normal)
        frame.pack(expand=True, fill="both")
        # グリッドの伸縮設定
        frame.grid_columnconfigure(1, weight=1)
        
        time_frame = ttk.Frame(frame, padding=app.padding_small)
        time_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        time_frame.grid_columnconfigure(1, weight=1)

        labels_and_buttons = [
            ("年:", "毎年"), ("月:", "毎月"), ("日:", "毎日"), 
            ("時:", "毎時"), ("分:", None)
        ]
        self.entries = {}
        
        for i, (label_text, btn_text) in enumerate(labels_and_buttons):
            ttk.Label(time_frame, text=label_text).grid(row=i, column=0, padx=(0, app.padding_small), pady=app.padding_small, sticky="e")
            entry = ttk.Entry(time_frame, font=app.font_normal, style="CustomDialog.TEntry")
            entry.grid(row=i, column=1, pady=app.padding_small, sticky="ew") # sticky="ew"で水平に伸ばす
            self.entries[label_text[:-1]] = entry
            
            if btn_text:
                ttk.Button(
                    time_frame, text=btn_text,
                    command=lambda e=entry: e.delete(0, 'end') or e.insert(0, '*')
                ).grid(row=i, column=2, padx=(app.padding_small, 0), pady=app.padding_small, sticky="w")

        # 終日チェックボックスも time_frame 内に配置
        self.is_daily_var = tk.BooleanVar()
        daily_check = ttk.Checkbutton(
            time_frame, text="終日イベントにする", variable=self.is_daily_var,
            command=self.toggle_daily_event
        )
        daily_check.grid(row=3, column=3, padx=(app.padding_large, 0), sticky="w", rowspan=2)

        ttk.Label(frame, text="内容:").grid(row=1, column=0, padx=(0, app.padding_small), pady=(app.padding_normal, 0), sticky="ne")
        self.content_entry = ttk.Entry(frame, font=app.font_normal, style="CustomDialog.TEntry")
        self.content_entry.grid(row=1, column=1, pady=(app.padding_normal, 0), sticky="ew")
        self.entries["内容"] = self.content_entry

        btn_frame = ttk.Frame(self, padding=app.padding_normal)
        btn_frame.pack()
        ttk.Button(btn_frame, text="OK", command=self.on_ok).pack(side="left", padx=app.padding_normal)
        ttk.Button(btn_frame, text="キャンセル", command=self.destroy).pack(side="left", padx=app.padding_normal)
        
        if initial_data:
            keys = ["年", "月", "日", "時", "分", "内容"]
            for key, value in zip(keys, initial_data):
                self.entries[key].insert(0, value)
            
            if initial_data[3] == '*' and initial_data[4] == '*':
                self.is_daily_var.set(True)
                self.toggle_daily_event()

        self.wait_window()
        
    def toggle_daily_event(self):
        """終日チェックボックスの状態に応じて時・分のフィールドを切り替える"""
        if self.is_daily_var.get():
            self.entries["時"].delete(0, 'end')
            self.entries["時"].insert(0, '*')
            self.entries["時"].config(state='disabled')
            self.entries["分"].delete(0, 'end')
            self.entries["分"].insert(0, '*')
            self.entries["分"].config(state='disabled')
        else:
            self.entries["時"].config(state='normal')
            self.entries["時"].delete(0, 'end')
            self.entries["分"].config(state='normal')
            self.entries["分"].delete(0, 'end')

    def on_ok(self):
        """入力値を厳密に検証してダイアログを閉じる"""
        try:
            # --- 各入力値を取得 ---
            validated_parts = {}
            for key in ["年", "月", "日", "時", "分"]:
                val = self.entries[key].get().strip()
                validated_parts[key] = val
            
            # --- 基本的な書式チェック ---
            for key, val in validated_parts.items():
                if val == '*':
                    continue
                if not val:
                    raise ValueError(f"「{key}」が空です。数値を入力するか、ワイルドカードを設定してください。")
                if not val.isdigit():
                    raise ValueError(f"「{key}」には数値を入力してください。")

            # --- 数値に変換 ---
            num_parts = {k: -1 if v == '*' else int(v) for k, v in validated_parts.items()}

            # --- 範囲チェック (単純なものから) ---
            if num_parts["月"] != -1 and not (1 <= num_parts["月"] <= 12):
                raise ValueError("「月」は1～12の間で入力してください。")
            
            if num_parts["時"] != -1 and not (0 <= num_parts["時"] <= 23):
                raise ValueError("「時」は0～23の間で入力してください。")

            if num_parts["分"] != -1 and not (0 <= num_parts["分"] <= 59):
                raise ValueError("「分」は0～59の間で入力してください。")
            
            # 分の単独ワイルドカード禁止チェック
            if num_parts["分"] == -1 and not self.is_daily_var.get():
                raise ValueError("「分」にワイルドカード（*）は使えません。\n（「終日イベント」にチェックを入れた場合を除く）")

            # --- 日付の妥当性チェック (最も複雑な部分) ---
            if num_parts["日"] != -1:
                year = num_parts["年"]
                month = num_parts["月"]
                day = num_parts["日"]

                if month == -1: # 月がワイルドカードの場合、日は31までOK
                    if not (1 <= day <= 31):
                        raise ValueError("「日」は1～31の間で入力してください。")
                else: # 月が指定されている場合
                    # 年がワイルドカードなら、閏年を考慮して最も日数が多い年(例:2024年)で判定
                    check_year = 2024 if year == -1 else year
                    # calendarモジュールでその月の日数を取得
                    days_in_month = calendar.monthrange(check_year, month)[1]
                    
                    if not (1 <= day <= days_in_month):
                        raise ValueError(f"{check_year}年{month}月は{days_in_month}日までです。「日」の値を修正してください。")

            # --- 内容のチェック ---
            content = self.entries["内容"].get().strip()
            if not content:
                raise ValueError("「内容」を入力してください。")

            # --- 全てのチェックを通過したら結果を保存 ---
            self.result = [
                validated_parts["年"], validated_parts["月"], validated_parts["日"],
                validated_parts["時"], validated_parts["分"], content
            ]
            self.destroy()

        except ValueError as e:
            messagebox.showerror("入力エラー", str(e), parent=self)
