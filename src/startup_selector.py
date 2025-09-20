# src/startup_selector.py

import tkinter as tk
from tkinter import ttk, messagebox
from configparser import ConfigParser
import os

class StartupCharacterSelector(tk.Toplevel):
    """
    アプリケーション起動時に表示されるキャラクター選択ダイアログ。
    """
    def __init__(self, parent, project_manager, theme_manager, font_normal, font_title, padding_normal):
        super().__init__(parent)
        self.project_manager = project_manager
        self.theme_manager = theme_manager
        self.font_normal = font_normal
        self.selected_characters = None # 最終的に選択されたキャラクターのディレクトリ名リスト

        # ウィンドウ設定
        self.title("起動キャラクターの選択")
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.resizable(False, False)

        self.configure(bg=self.theme_manager.get('bg_main'))
        
        # スタイルの設定
        style = ttk.Style(self)
        style.configure("Selector.TFrame", background=self.theme_manager.get('bg_main'))
        style.configure("Selector.TLabel", background=self.theme_manager.get('bg_main'), foreground=self.theme_manager.get('bg_text'), font=self.font_normal)
        style.configure("Selector.TRadiobutton", background=self.theme_manager.get('bg_main'), foreground=self.theme_manager.get('bg_text'), font=self.font_normal)
        style.configure("Selector.TButton", font=self.font_normal)

        main_frame = ttk.Frame(self, padding=padding_normal, style="Selector.TFrame")
        main_frame.pack(expand=True, fill="both")
        
        # モード選択
        self.mode_var = tk.StringVar(value="single")
        mode_frame = ttk.Frame(main_frame, style="Selector.TFrame")
        mode_frame.pack(anchor="w", pady=(0, padding_normal))
        
        ttk.Radiobutton(mode_frame, text="1人で起動", variable=self.mode_var, value="single", command=self._update_selection_mode, style="Selector.TRadiobutton").pack(side="left", padx=padding_normal)
        ttk.Radiobutton(mode_frame, text="2人で起動", variable=self.mode_var, value="dual", command=self._update_selection_mode, style="Selector.TRadiobutton").pack(side="left", padx=padding_normal)

        # キャラクターリスト
        self.instruction_label = ttk.Label(main_frame, text="", style="Selector.TLabel")
        self.instruction_label.pack(anchor="w")

        list_frame = ttk.Frame(main_frame, style="Selector.TFrame")
        list_frame.pack(fill="both", expand=True, pady=padding_normal)

        self.listbox = tk.Listbox(
            list_frame,
            selectmode="browse",
            font=self.font_normal,
            bg=self.theme_manager.get('output_bg'),
            fg=self.theme_manager.get('output_text'),
            selectbackground=self.theme_manager.get('selected_bg'),
            selectforeground=self.theme_manager.get('selected_text'),
            highlightthickness=1,
            highlightbackground=self.theme_manager.get('border_normal')
        )

        self.listbox.pack(side="left", fill="both", expand=True)

        # ダブルクリックイベントを_on_launchメソッドにバインド
        self.listbox.bind("<Double-Button-1>", self._on_launch)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
        self._populate_character_list()
        self._update_selection_mode()

        # ボタン
        button_frame = ttk.Frame(main_frame, style="Selector.TFrame")
        button_frame.pack(fill="x", pady=(padding_normal, 0))
        
        ttk.Button(button_frame, text="起動", command=self._on_launch, style="Selector.TButton").pack(side="right")
        ttk.Button(button_frame, text="キャンセル", command=self._on_cancel, style="Selector.TButton").pack(side="right", padx=padding_normal)
        
        # ウィンドウ表示
        self.update_idletasks()
        x = parent.winfo_screenwidth() // 2 - self.winfo_width() // 2
        y = parent.winfo_screenheight() // 2 - self.winfo_height() // 2
        self.geometry(f"+{x}+{y}")
        
        # 一時的にウィンドウを最前面に固定
        self.wm_attributes("-topmost", True)
        # 0.1秒後に最前面固定を解除
        self.after(100, lambda: self.wm_attributes("-topmost", False))

        self.wait_window()

    def _get_character_display_name(self, char_dir):
        """ディレクトリ名から表示名を取得する"""
        char_ini_path = os.path.join(self.project_manager.characters_dir, char_dir, 'character.ini')
        if os.path.exists(char_ini_path):
            try:
                config = ConfigParser()
                config.read(char_ini_path, encoding='utf-8')
                return config.get('INFO', 'CHARACTER_NAME', fallback=char_dir)
            except Exception:
                pass
        return char_dir

    def _populate_character_list(self):
        """リストボックスにキャラクター名を表示する"""
        self.char_map = {} # 表示名とディレクトリ名のマッピング
        char_dirs = self.project_manager.list_projects()
        
        display_names = []
        for char_dir in char_dirs:
            display_name = self._get_character_display_name(char_dir)
            # 万が一表示名が重複した場合、(フォルダ名)を追記
            if display_name in self.char_map:
                display_name_with_dir = f"{display_name} ({char_dir})"
                self.char_map[display_name_with_dir] = char_dir
                display_names.append(display_name_with_dir)
            else:
                self.char_map[display_name] = char_dir
                display_names.append(display_name)
        
        for name in sorted(display_names):
            self.listbox.insert(tk.END, name)

    def _update_selection_mode(self):
        """起動モードに応じてリストボックスの選択モードと説明文を切り替える"""
        self.listbox.selection_clear(0, tk.END)

        # 説明ラベルの表示/非表示と内容の更新
        if self.mode_var.get() == "single":
            self.listbox.config(selectmode="browse") # 単一選択
            self.instruction_label.pack_forget() # 説明を隠す
        else: # dual
            self.listbox.config(selectmode="multiple") # クリックで複数選択
            self.instruction_label.config(text="（2体のキャラクターをクリックで選択してください）")
            self.instruction_label.pack(anchor="w", before=self.listbox.master) # 説明を表示

    def _on_launch(self, event=None):
        """起動ボタンが押されたとき、またはダブルクリックされたときの処理"""
        selected_indices = self.listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("選択エラー", "キャラクターを選択してください。", parent=self)
            return

        mode = self.mode_var.get()
        if mode == "single" and len(selected_indices) != 1:
            messagebox.showwarning("選択エラー", "「1人で起動」モードでは、1体のキャラクターを選択してください。", parent=self)
            return
        
        if mode == "dual" and len(selected_indices) > 2:
            messagebox.showwarning("選択エラー", "「2人で起動」モードでは、最大2体のキャラクターまで選択できます。", parent=self)
            return
            
        if mode == "dual" and len(selected_indices) != 2:
            messagebox.showwarning("選択エラー", "「2人で起動」モードでは、2体のキャラクターを選択してください。", parent=self)
            return

        # 選択された表示名からディレクトリ名を取得
        selected_display_names = [self.listbox.get(i) for i in selected_indices]
        self.selected_characters = [self.char_map[name] for name in selected_display_names]
        
        self.destroy()

    def _on_cancel(self):
        """キャンセル時やウィンドウが閉じられたときの処理"""
        self.selected_characters = None
        self.destroy()
