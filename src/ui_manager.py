# src/ui_manager.py

import tkinter as tk
from tkinter import messagebox
import threading
import os
import webbrowser

from configparser import ConfigParser, NoSectionError, NoOptionError 
try:
    from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayMenuItem
    from PIL import Image
except ImportError:
    TrayIcon, TrayMenu, TrayMenuItem, Image = None, None, None, None

class UIManager:
    """
    UI関連の管理（コンテキストメニュー、タスクトレイ）を専門に担当するクラス。
    """
    def __init__(self, app):
        """
        UIManagerを初期化します。

        Args:
            app (DesktopMascot): 親となるアプリケーションのインスタンス。
        """
        self.app = app
        self.root = app.root
        
        self.context_menu_target_char = None # 右クリックされたキャラクターを保持
        
        self.app.startup_mode_var = tk.StringVar(value=self.app.config.get('UI', 'STARTUP_MODE', fallback='fixed'))

        self._setup_context_menu()
        self._setup_tray_icon()

    def _setup_context_menu(self):
        """右クリックで表示されるコンテキストメニューの項目を定義・設定します。"""
        self.context_menu = tk.Menu(self.root, tearoff=0)

        # --- 機能設定メニュー ---
        self.context_menu.add_command(label="表示/非表示", command=self.app.toggle_visibility)
        self.context_menu.add_checkbutton(label="常に手前に表示", variable=self.app.is_always_on_top)
        self.context_menu.add_command(label="最前列に移動", command=lambda: self.app.bring_to_front())
        self.startup_menu = tk.Menu(self.context_menu, tearoff=0)
        self.startup_menu.add_radiobutton(
            label="前回終了時のキャラクターで起動",
            variable=self.app.startup_mode_var,
            value="fixed",
            command=self._set_startup_mode
        )
        self.startup_menu.add_radiobutton(
            label="毎回キャラクターを選択する",
            variable=self.app.startup_mode_var,
            value="select",
            command=self._set_startup_mode
        )
        self.startup_menu.add_radiobutton(
            label="ランダムなキャラクターで起動",
            variable=self.app.startup_mode_var,
            value="random",
            command=self._set_startup_mode
        )
        self.context_menu.add_cascade(label="起動時のキャラクター設定", menu=self.startup_menu)
        self.theme_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="カラーテーマ", menu=self.theme_menu)

        self.context_menu.add_separator()
        self.context_menu.add_checkbutton(label="自動発話を有効にする", variable=self.app.is_auto_speech_enabled)
        self.cool_time_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="自動発話の間隔", menu=self.cool_time_menu)
        self.context_menu.add_checkbutton(label="スケジュール通知を有効にする", variable=self.app.is_schedule_enabled)
        self.context_menu.add_command(label="スケジュール管理...", command=self.app.open_schedule_editor)
        self.context_menu.add_checkbutton(label="音声再生", variable=self.app.is_sound_enabled)
        self.volume_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="音量調整", menu=self.volume_menu)
        self.context_menu.add_separator()
        
        self.api_status_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="API残回数 (2.5系)", menu=self.api_status_menu)
        self.api_status_menu.add_command(label="Pro: -", state="disabled")
        self.api_status_menu.add_command(label="Flash: -", state="disabled")
        self.api_status_menu.add_command(label="Flash-Lite: -", state="disabled")

        self.api_status_menu_2 = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="API残回数 (2.0系)", menu=self.api_status_menu_2)
        self.api_status_menu_2.add_command(label="Flash: -", state="disabled")
        self.api_status_menu_2.add_command(label="Flash-Lite: -", state="disabled")
        self.context_menu.add_command(label="API接続設定...", command=self.app.open_api_settings_editor)

        self.context_menu.add_separator()
        self.context_menu.add_checkbutton(label="思考モード (Pro使用)", variable=self.app.is_pro_mode)
        
        self.context_menu.add_separator()
        screenshot_state = "normal" if self.app.screenshot_handler.is_available else "disabled"
        self.context_menu.add_checkbutton(label="スクリーンショット添付モード", variable=self.app.is_screenshot_mode, state=screenshot_state)
        self.capture_target_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="キャプチャ対象選択", menu=self.capture_target_menu, state=screenshot_state)
        
        self.context_menu.add_separator()
        self.costume_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="衣装変更", menu=self.costume_menu)
        self.character_change_menu = tk.Menu(self.context_menu, tearoff=0)
        self.position_menu = tk.Menu(self.context_menu, tearoff=0)
        self.position_menu.add_command(label="左に寄せる", command=lambda: self.context_menu_target_char.move_to_side('left'))
        self.position_menu.add_command(label="右に寄せる", command=lambda: self.context_menu_target_char.move_to_side('right'))
        self.position_menu.add_separator()
        self.position_menu.add_command(label="左右反転", command=lambda: self.context_menu_target_char.flip_character())
        self.context_menu.add_cascade(label="位置調整", menu=self.position_menu)
        self.context_menu.add_command(label="お休みさせる", command=lambda: self.app.dismiss_character(self.context_menu_target_char))
        self.context_menu.add_cascade(label="キャラクター変更", menu=self.character_change_menu)
        self.character_add_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="キャラクター追加", menu=self.character_add_menu)
        
        self.context_menu.add_separator()

        self.recollection_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="イベント回想", menu=self.recollection_menu)

        self.context_menu.add_command(label="会話ログを見る", command=lambda: self.app.open_conversation_log_viewer(self.context_menu_target_char))
        self.context_menu.add_command(label="会話ログをクリア", command=lambda: self.app.clear_log_for_character(self.context_menu_target_char))
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="お問い合わせ / 不具合報告 (GitHub)",
            command=lambda: webbrowser.open_new_tab("https://github.com/makumoru/AI_DesktopMascot_cocococo/issues")
        )
        self.context_menu.add_separator()

        # ここここの構造とpyinstallerとの相性が悪すぎるのか何やっても安全な再起動ができなかった。一時封印処置。
        # self.context_menu.add_command(label="再起動", command=self.app.restart_app)
        self.context_menu.add_command(label="設定を再読み込み", command=self.app.reload_all_settings)
        self.context_menu.add_command(label="終了", command=self.app.exit_app)

    def _setup_tray_icon(self):
        """タスクトレイアイコンと右クリックメニューを設定します。"""
        if not TrayIcon:
            return

        icon_image = None
        try:
            icon_path = 'images/app_icon.png'
            icon_image = Image.open(icon_path)
        except FileNotFoundError:
            print(f"警告: タスクトレイのアイコンファイルが見つかりません: {icon_path}")
            icon_image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))

        def create_cool_time_submenu():
            for label in self.app.cool_time_presets.keys():
                yield TrayMenuItem(
                    label,
                    lambda l=label: self.app._set_cool_time(l),
                    checked=lambda item, l=label: self.app.cool_time_setting_var.get() == l,
                    radio=True
                )
        
        def create_bring_to_front_submenu():
            for char in self.app.characters:
                yield TrayMenuItem(
                    char.name,
                    lambda c=char: self.app.bring_to_front(c)
                )

        menu_items = [
            TrayMenuItem('表示/非表示', self.app.toggle_visibility),
            TrayMenuItem(
                '常に手前に表示', 
                lambda: self.app.is_always_on_top.set(not self.app.is_always_on_top.get()), 
                checked=lambda item: self.app.is_always_on_top.get()
            )
        ]
        
        if len(self.app.characters) > 1:
            menu_items.append(TrayMenuItem('最前列に移動', TrayMenu(create_bring_to_front_submenu)))
        elif len(self.app.characters) == 1:
             menu_items.append(TrayMenuItem('最前列に移動', lambda: self.app.bring_to_front(self.app.characters[0])))
        
        menu_items.extend([
            TrayMenu.SEPARATOR,
            TrayMenuItem(
                '自動発話を有効にする',
                lambda: self.app.is_auto_speech_enabled.set(not self.app.is_auto_speech_enabled.get()),
                checked=lambda item: self.app.is_auto_speech_enabled.get()
            ),
            TrayMenuItem('自動発話の間隔', TrayMenu(create_cool_time_submenu)),
            TrayMenuItem(
                'スケジュール通知を有効にする',
                lambda: self.app.is_schedule_enabled.set(not self.app.is_schedule_enabled.get()),
                checked=lambda item: self.app.is_schedule_enabled.get()
            ),
            TrayMenuItem('スケジュール管理...', self.app.open_schedule_editor),
            TrayMenuItem(
                '音声再生',
                lambda: self.app.is_sound_enabled.set(not self.app.is_sound_enabled.get()),
                checked=lambda item: self.app.is_sound_enabled.get()
            ),
            TrayMenu.SEPARATOR,
            TrayMenuItem(
                '思考モード (Pro使用)',
                lambda: self.app.is_pro_mode.set(not self.app.is_pro_mode.get()),
                checked=lambda item: self.app.is_pro_mode.get()
            ),
            TrayMenuItem(
                'スクリーンショット添付モード',
                lambda: self.app.is_screenshot_mode.set(not self.app.is_screenshot_mode.get()),
                checked=lambda item: self.app.is_screenshot_mode.get(),
                enabled=lambda item: self.app.screenshot_handler.is_available
            ),
            TrayMenu.SEPARATOR,
            TrayMenuItem('場の全員の会話ログをクリア', self.app.clear_all_logs),
            TrayMenu.SEPARATOR,
            # ここここの構造とpyinstallerとの相性が悪すぎるのか何やっても安全な再起動ができなかった。一時封印処置。
            # TrayMenuItem('再起動', self.app.restart_app),
            TrayMenuItem('終了', self.app.exit_app)
        ])
        
        menu = TrayMenu(*menu_items)
        self.app.tray_icon = TrayIcon("ここここ", icon_image, "ここここ - AIデスクトップマスコット", menu)

    def show_context_menu(self, event):
        """
        右クリックされた位置にコンテキストメニューを表示します。
        メニューの内容は、クリックされたキャラクターに応じて動的に更新されます。
        """
        if self.app.is_shutting_down: return
        
        clicked_widget = event.widget.winfo_toplevel()
        target_char = None
        for char in self.app.characters:
            if char.ui == clicked_widget:
                target_char = char
                break
        if not target_char: return
        self.context_menu_target_char = target_char
        self.app.context_menu_target_char = target_char # DesktopMascotにも通知
        self.update_theme_menu()

        self.update_api_status_menu()
        self.update_capture_target_menu()
        self.update_costume_menu()
        self.update_cool_time_menu()
        self.update_volume_menu()
        self.update_character_change_menu() 
        self.update_character_add_menu()
        self.update_recollection_menu()
        
        is_single_mode = len(self.app.characters) <= 1
        # bool()でTrue/Falseに変換し、可読性を高める
        available_chars_exist = bool(self.app.get_available_change_characters())

        # 「お休みさせる」は二人モードの時だけ有効
        self.context_menu.entryconfig("お休みさせる", state="normal" if not is_single_mode else "disabled")
        
        # 「キャラクター変更」は交代可能なキャラが存在すれば、常に有効
        self.context_menu.entryconfig("キャラクター変更", state="normal" if available_chars_exist else "disabled")
        
        # 「キャラクター追加」は交代可能なキャラがいて、かつ一人モードの時だけ有効
        can_add = available_chars_exist and is_single_mode
        self.context_menu.entryconfig("キャラクター追加", state="normal" if can_add else "disabled")

        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def update_api_status_menu(self):
        """API残回数メニューの表示を最新の情報に更新します。"""
        remaining = self.app.gemini_handler.log_manager.get_remaining_counts()
        self.api_status_menu.entryconfig(0, label=f"Pro: {remaining.get('pro', 'N/A')}")
        self.api_status_menu.entryconfig(1, label=f"Flash: {remaining.get('flash', 'N/A')}")
        self.api_status_menu.entryconfig(2, label=f"Flash-Lite: {remaining.get('flash-lite', 'N/A')}")
        self.api_status_menu_2.entryconfig(0, label=f"Flash: {remaining.get('flash-2', 'N/A')}")
        self.api_status_menu_2.entryconfig(1, label=f"Flash-Lite: {remaining.get('flash-lite-2', 'N/A')}")

    def update_capture_target_menu(self):
        """スクリーンショットのキャプチャ対象リストを最新の情報に更新します。"""
        if not self.app.screenshot_handler.is_available: return
        
        self.capture_target_menu.delete(0, "end")
        self.app.capture_targets_cache = self.app.screenshot_handler.get_capture_targets()
        
        if not self.app.capture_targets_cache:
            self.capture_target_menu.add_command(label="(対象なし)", state="disabled")
            return

        available_keys = []
        for target in self.app.capture_targets_cache:
            key = target.get('title') or target.get('name')
            available_keys.append(key)
            self.capture_target_menu.add_radiobutton(
                label=target['name'],
                variable=self.app.selected_capture_target_key,
                value=key
            )
        
        current_selection = self.app.selected_capture_target_key.get()
        if not current_selection or current_selection not in available_keys:
            if available_keys:
                self.app.selected_capture_target_key.set(available_keys[0])

    def update_character_add_menu(self):
        """キャラクター追加メニューを動的に生成・更新します。"""
        self.character_add_menu.delete(0, "end")
        
        # 「get_available_change_characters」は「現在画面にいないキャラ」を返すので、この用途に最適
        available_chars = self.app.get_available_change_characters()
        
        if not available_chars:
            return

        for char_dir in available_chars:
            display_name = char_dir
            char_ini_path = os.path.join('characters', char_dir, 'character.ini')
            
            try:
                if os.path.exists(char_ini_path):
                    config = ConfigParser()
                    config.read(char_ini_path, encoding='utf-8')
                    if config.has_section('INFO'):
                        system_name = config.get('INFO', 'SYSTEM_NAME', fallback='').strip()
                        if system_name:
                            display_name = system_name
                        else:
                            character_name = config.get('INFO', 'CHARACTER_NAME', fallback='').strip()
                            if character_name:
                                display_name = character_name
            except Exception as e:
                print(f"警告: {char_ini_path} の読み込み中にエラーが発生しました。: {e}")

            self.character_add_menu.add_command(
                label=display_name,
                command=lambda new_dir=char_dir: self.app.add_character(new_dir)
            )

    def update_character_change_menu(self):
        """キャラクター変更メニューを動的に生成・更新します。"""
        self.character_change_menu.delete(0, "end")
        
        available_chars = self.app.get_available_change_characters()
        target_char = self.context_menu_target_char

        if not available_chars or not target_char:
            return

        for char_dir in available_chars:
            display_name = char_dir  # 最悪の場合のフォールバック名
            char_ini_path = os.path.join('characters', char_dir, 'character.ini')
            
            try:
                if os.path.exists(char_ini_path):
                    config = ConfigParser()
                    config.read(char_ini_path, encoding='utf-8')
                    
                    # [INFO] セクションの存在を確認
                    if config.has_section('INFO'):
                        # 1. SYSTEM_NAME を取得試行（値が空でないかstrip()でチェック）
                        system_name = config.get('INFO', 'SYSTEM_NAME', fallback='').strip()
                        
                        if system_name:
                            display_name = system_name
                        else:
                            # 2. SYSTEM_NAME がない、または空の場合、CHARACTER_NAME を取得
                            character_name = config.get('INFO', 'CHARACTER_NAME', fallback='').strip()
                            if character_name:
                                display_name = character_name
                            # 両方ない、または空の場合は、初期値のディレクトリ名が使われる
            
            except Exception as e:
                # iniファイルの解析中に何か問題があれば警告を出し、ディレクトリ名で続行
                print(f"警告: {char_ini_path} の読み込み中にエラーが発生しました。: {e}")

            self.character_change_menu.add_command(
                label=display_name,
                command=lambda new_dir=char_dir: self.app.change_character(target_char.original_id, new_dir)
            )

    def update_costume_menu(self):
        """右クリックされたキャラクターの衣装変更メニューを動的に生成・更新します。"""
        char = self.context_menu_target_char
        if not char: return
        
        self.costume_menu.delete(0, "end")
        char.costume_var.set(char.current_costume_id)
        
        for costume_id, info in char.costumes.items():
            self.costume_menu.add_radiobutton(
                label=info['name'],
                variable=char.costume_var,
                value=costume_id,
                command=lambda cid=costume_id, c=char: c.change_costume(cid, triggered_by_user=True)
            )
            
    def update_cool_time_menu(self):
        """自動発話間隔の設定メニューを動的に生成・更新します。"""
        self.cool_time_menu.delete(0, "end")
        current_preset_label = self.app._find_current_cool_time_preset()
        self.app.cool_time_setting_var.set(current_preset_label)
        
        for label in self.app.cool_time_presets.keys():
            self.cool_time_menu.add_radiobutton(
                label=label,
                variable=self.app.cool_time_setting_var,
                value=label,
                command=lambda l=label: self.app._set_cool_time(l)
            )

    def update_theme_menu(self):
        """カラーテーマ選択メニューを動的に生成・更新します。"""
        self.theme_menu.delete(0, "end")
        
        # 現在の設定値を更新
        current_theme = self.app.config.get('UI', 'theme', fallback='')
        self.app.theme_setting_var.set(current_theme)

        # 利用可能なテーマリストを取得
        available_themes = self.app.theme_manager.get_available_themes()

        # デフォルトテーマの選択肢を追加
        self.theme_menu.add_radiobutton(
            label="デフォルト (薄黄色)",
            variable=self.app.theme_setting_var,
            value="",
            command=lambda: self.app.set_theme("")
        )
        self.theme_menu.add_separator()

        if not available_themes:
            self.theme_menu.add_command(label="(テーマファイルなし)", state="disabled")
            return

        for theme_name in available_themes:
            self.theme_menu.add_radiobutton(
                label=theme_name,
                variable=self.app.theme_setting_var,
                value=theme_name,
                command=lambda t=theme_name: self.app.set_theme(t)
            )

    def update_volume_menu(self):
        """キャラクターごとの音量調整メニューを動的に生成・更新します。"""
        char = self.context_menu_target_char
        if not char: return
        
        self.volume_menu.delete(0, "end")
        
        # 10%刻みで100%から0%までラジオボタンを追加
        for volume_level in range(100, -1, -10):
            label = f"{volume_level}%"
            if volume_level == 50:
                label += " (デフォルト)"
            if volume_level == 0:
                label += " (ミュート)"

            self.volume_menu.add_radiobutton(
                label=label,
                variable=char.volume_var, # character_controllerが持つIntVarを使用
                value=volume_level,
                command=lambda level=volume_level, c=char: c.update_volume(level)
            )

    def update_recollection_menu(self):
        """イベント回想メニューを動的に生成・更新します。"""
        char = self.context_menu_target_char
        if not char: return

        self.recollection_menu.delete(0, "end")
        
        completed_events = self.app.event_manager.get_completed_events_for_recollection(char)
        
        if not completed_events:
            self.recollection_menu.add_command(label="(まだ見終わったイベントがありません)", state="disabled")
            return

        for event_info in completed_events:
            self.recollection_menu.add_command(
                label=event_info['name'],
                # ラムダ関数で、クリックされた時点のキャラクターとイベントデータを渡す
                command=lambda c=char, e=event_info['data']: self.app.start_event(c, e, is_recollection=True)
            )

    def _set_startup_mode(self):
        """右クリックメニューから起動モードが変更されたときに呼び出される"""
        new_mode = self.app.startup_mode_var.get()
        self.app._update_config_file('UI', 'STARTUP_MODE', new_mode)
