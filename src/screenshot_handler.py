# screenshot_handler.py

from PIL import Image
import time  # timeをインポート

# 依存ライブラリのインポート試行
try:
    import mss
    import pygetwindow as gw
except ImportError:
    print("警告: スクリーンショット機能に必要なライブラリがありません。")
    print("コマンドプロンプトで 'pip install mss pygetwindow' を実行してください。")
    mss = None
    gw = None

class ScreenshotHandler:
    """
    スクリーンショットの取得と、キャプチャ対象の管理を行うクラス。
    """
    def __init__(self, app_titles):
        """
        コンストラクタ。
        
        Args:
            app_titles (list): キャプチャ対象から除外するウィンドウタイトルのリスト。
                               (マスコット自身のウィンドウなど)
        """
        if not mss or not gw:
            self.is_available = False
            return
            
        self.is_available = True
        self.sct = mss.mss()
        self.app_titles = app_titles

    def get_capture_targets(self):
        """
        キャプチャ可能なディスプレイとウィンドウのリストを取得する。

        Returns:
            list: キャプチャ対象の辞書を含むリスト。
        """
        if not self.is_available:
            return []

        targets = []
        # 1. ディスプレイを追加
        for i, monitor in enumerate(self.sct.monitors[1:], 1): # 0番目は全画面なので除外
            name = f"ディスプレイ {i} ({monitor['width']}x{monitor['height']})"
            targets.append({'type': 'display', 'id': i, 'name': name, 'monitor_info': monitor})
            
        # 2. ウィンドウを追加
        all_windows = gw.getAllWindows()
        for window in all_windows:
            # 最小化、非表示、タイトルなし、除外対象のウィンドウはスキップ
            if window.isMinimized or not window.visible or not window.title or window.title in self.app_titles:
                continue
            
            full_title = window.title
            display_title = full_title
            if len(display_title) > 50:
                display_title = display_title[:47] + "..."
            
            name = f"ウィンドウ: {display_title}"
            targets.append({
                'type': 'window',
                'name': name,           # メニュー表示用の名前
                'title': full_title,    # 再検索のキーとなる完全なタイトル
                'monitor_info': None
            })

        return targets

    def capture(self, target):
        """
        指定された対象のスクリーンショットを撮影し、PIL.Imageオブジェクトとして返す。

        Args:
            target (dict): get_capture_targets()で取得した対象の辞書。

        Returns:
            PIL.Image or None: 撮影したスクリーンショットの画像データ。
        """
        if not self.is_available or not target:
            return None

        try:
            if target['type'] == 'display':
                # ディスプレイをキャプチャ (変更なし)
                monitor = target['monitor_info']
                sct_img = self.sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                return img
                
            elif target['type'] == 'window':
                target_title = target.get('title')
                if not target_title:
                    print("エラー: ターゲット情報にタイトルキーがありません。")
                    return None

                windows = gw.getWindowsWithTitle(target_title)
                if not windows:
                    print(f"警告: ウィンドウ '{target_title}' が見つかりませんでした。")
                    return None

                # 複数見つかった場合、可視で最小化されていないものを優先して選択
                window_to_capture = None
                for w in reversed(windows):  # 一般的にリストの後ろの方が手前にあるウィンドウ
                    if w.visible and not w.isMinimized:
                        window_to_capture = w
                        break
                
                if not window_to_capture:
                    print(f"警告: ウィンドウ '{target_title}' は現在キャプチャできません（非表示または最小化）。")
                    return None

                window = window_to_capture
                
                # ウィンドウをアクティブにして最前面に持ってくる (ベストエフォート)
                try:
                    if window.isMinimized: window.restore()
                    window.activate()
                    time.sleep(0.2) # activate()が反映されるのを少し待つ
                except Exception:
                    pass
                
                # サイズが0以下の無効なウィンドウはキャプチャしない
                if window.width <= 0 or window.height <= 0:
                    print(f"警告: ウィンドウ '{target_title}' のサイズが不正です。")
                    return None

                bbox = (window.left, window.top, window.right, window.bottom)
                sct_img = self.sct.grab(bbox)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                return img

        except Exception as e:
            print(f"スクリーンショットの撮影に失敗しました: {e}")
            return None
        
        return None