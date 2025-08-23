# main.py

import os
import sys
from src.desktop_mascot import DesktopMascot

# --- アプリケーションのルートディレクトリを最初に定義 ---
# このスクリプト(main.py)があるディレクトリを基準に、
# 設定ファイルや画像ファイルなどを相対パスで正しく参照するために使用します。
if getattr(sys, 'frozen', False):
    # exe化されている場合、実行ファイルのパスを取得
    APP_ROOT_DIR = os.path.dirname(sys.executable)
else:
    # スクリプトとして実行されている場合、スクリプトのパスを取得
    APP_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- アプリケーションのエントリーポイント ---
if __name__ == "__main__":
    # 作業ディレクトリをスクリプトのルートに変更します。
    # これにより、設定ファイル等が相対パスで正しく読み込まれるようになります。
    os.chdir(APP_ROOT_DIR)
    
    # アプリケーションのメインクラスをインスタンス化します。
    # ルートディレクトリのパスを渡して、内部でのパス解決に使います。
    app = DesktopMascot(app_root_dir=APP_ROOT_DIR)
    
    # アプリケーションを実行します。
    app.run()