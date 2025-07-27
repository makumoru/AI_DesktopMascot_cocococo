# src/ui_manager.py

import tkinter as tk
from tkinter import messagebox
import threading
import os

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
        self._setup_context_menu()
        self._setup_tray_icon()

    def _setup_context_menu(self):
        """右クリックで表示されるコンテキストメニューの項目を定義・設定します。"""
        self.context_menu = tk.Menu(self.root, tearoff=0)

        # --- 機能設定メニュー ---
        self.context_menu.add_command(label="表示/非表示", command=self.app.toggle_visibility)
        self.context_menu.add_checkbutton(label="常に手前に表示", variable=self.app.is_always_on_top)
        self.context_menu.add_command(label="最前列に移動", command=lambda: self.app.bring_to_front())
        self.context_menu.add_separator()
        self.context_menu.add_checkbutton(label="自動発話を有効にする", variable=self.app.is_auto_speech_enabled)
        self.cool_time_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="自動発話の間隔", menu=self.cool_time_menu)
        self.context_menu.add_checkbutton(label="音声再生", variable=self.app.is_sound_enabled)
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
        
        self.context_menu.add_separator()
        self.context_menu.add_command(label="会話ログをクリア", command=self.app.clear_conversation_log)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="再起動", command=self.app.restart_app)
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
            TrayMenuItem('会話ログをクリア', self.app.clear_conversation_log),
            TrayMenu.SEPARATOR,
            TrayMenuItem('再起動', self.app.restart_app),
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
        
        self.update_api_status_menu()
        self.update_capture_target_menu()
        self.update_costume_menu()
        self.update_cool_time_menu()

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