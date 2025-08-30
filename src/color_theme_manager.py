# src/color_theme_manager.py

import os
from configparser import ConfigParser

class ColorThemeManager:
    """
    UIのカラーテーマを管理するクラス。
    config.iniで指定されたテーマファイルを読み込み、色設定を提供する。
    """
    DEFAULT_COLORS = {
        #背景色(メイン)
		'bg_main' : '#fdfbe9',
		#背景色(アクセント)
		'bg_accent' : '#e4e0bd',
		#文字色
		'bg_text' : 'black',
		#ネームプレート背景色
		'nameplate_bg' : '#f8bf6a',
		#ネームプレート文字色
		'nameplate_text' : 'black',
		#AI出力欄背景色
		'output_bg' : '#fdfbe9',
		#AI出力欄文字色
		'output_text' : 'black',
		#テキスト入力欄背景色
		'input_bg' : 'white',
		#テキスト入力欄文字色
		'input_text' : 'black',
		#ボタン背景色
		'button_bg' : '#e4e0bd',
		#ボタン文字色
		'button_text' : 'black',
		#ボタンアクティブ時背景色
		'button_active_bg' : '#9e7941',
		#ボタンアクティブ時文字色
		'button_active_text' : 'black',
		#ボタン文字色
		'button_text' : 'black',
		#表ヘッダー背景色
		#'list_header_bg' : '#fdfbe9',
		#表ヘッダー文字色
		#'list_header_text' : 'black',
		#表背景色
		#'list_bg' : '#fdfbe9',
		#表文字色
		#'list_text' : 'black',
		#入力欄縁色
		'border_normal' : 'black',
		#アクティブ字入力欄縁色
		'border_focus' : '#76bbf8',
		#文字選択時背景色
		'selected_bg' : '#0078d7',
		#文字選択時文字色
		'selected_text' : 'white',
		#リンク文字色
		'link_text' : 'blue',
		#インフォメーション文字色
		'info_text' : '#555555',
		#ツールチップ背景色
		'tooltip_bg' : '#FFFFE0',
		#ツールチップ文字色
		'tooltip_text' : 'black'
    }
    THEMES_DIR = 'colorthemes'

    def __init__(self, app_config: ConfigParser):
        """
        ColorThemeManagerを初期化し、指定されたテーマを読み込む。
        """
        self.app_config = app_config
        self.colors = self.DEFAULT_COLORS.copy()
        self.load_theme()

    def load_theme(self):
        """
        config.iniからテーマ名を取得し、対応するテーマファイルを読み込む。
        """
        self.colors = self.DEFAULT_COLORS.copy() # まずデフォルト色にリセット
        
        try:
            theme_name = self.app_config.get('UI', 'theme', fallback='').strip()
            if not theme_name:
                print("テーマが指定されていないため、デフォルトのカラーテーマを使用します。")
                return

            theme_path = os.path.join(self.THEMES_DIR, f"{theme_name}.ini")
            
            if not os.path.exists(theme_path):
                print(f"警告: テーマファイル '{theme_path}' が見つかりません。デフォルトテーマを使用します。")
                return

            theme_config = ConfigParser()
            theme_config.read(theme_path, encoding='utf-8')

            if 'COLORS' in theme_config:
                for key, value in theme_config.items('COLORS'):
                    self.colors[key] = value
                print(f"カラーテーマ '{theme_name}' を読み込みました。")

        except Exception as e:
            print(f"テーマの読み込み中にエラーが発生しました: {e}")
            self.colors = self.DEFAULT_COLORS.copy() # エラー時はデフォルトに戻す

    def get(self, key: str) -> str:
        """
        指定されたキーに対応する色コードを返す。
        存在しないキーの場合は、デフォルトの黒を返す。
        """
        return self.colors.get(key, '#000000')

    def get_available_themes(self) -> list:
        """
        'colorthemes'フォルダ内にある利用可能なテーマ名のリストを返す。
        """
        if not os.path.isdir(self.THEMES_DIR):
            return []
        
        themes = [
            os.path.splitext(f)[0] for f in os.listdir(self.THEMES_DIR) 
            if f.endswith('.ini')
        ]
        return themes