# main.py

import os
import sys
from src.desktop_mascot import DesktopMascot

# アプリケーションのバージョン情報 ---
# リリースを更新する際に、このバージョン番号を更新してください。
CURRENT_VERSION = "1.8"

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
    # ルートディレクトリのパスとバージョン情報を渡して、内部でのパス解決や更新チェックに使います。
    app = DesktopMascot(app_root_dir=APP_ROOT_DIR, current_version=CURRENT_VERSION)
    
    # アプリケーションを実行します。
    app.run()