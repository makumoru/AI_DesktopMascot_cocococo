# src/emotion_handler.py

import tkinter as tk
from PIL import Image, ImageTk, ImageOps
import numpy as np
import os
import time
import ast

class EmotionHandler:
    """
    キャラクターの画像表示、感情に基づいた表情の切り替え、口パクアニメーション、
    そしてユーザーによるタッチ操作（クリック、ドラッグ、カーソルインタラクション）を
    一手に担うクラス。
    """
    LIP_SYNC_INTERVAL_MS = 250

    def __init__(self, root, toplevel_window, config, char_config, character_controller, window_width, tolerance, edge_color, is_flipped):
        """
        EmotionHandlerを初期化します。

        Args:
            root (tk.Toplevel): このハンドラが属する親ウィンドウ（CharacterUIGroup）。
            config (ConfigParser): 全体設定。
            char_config (ConfigParser): このキャラクター固有の設定情報。
            character_controller (CharacterController): 親となるキャラクターコントローラー。
            window_width (int): キャラクターウィンドウの幅。画像の拡縮率計算に使用。
            tolerance (int): 画像の背景色を透明化する際の色の許容誤差。
            edge_color (str): 透明部分との境界線に描画する色。
            is_flipped (bool): 画像を左右反転するかどうか。
        """
        self.root = root
        self.toplevel_window = toplevel_window # ウィンドウ全体への参照を保持
        self.config = config
        self.character_controller = character_controller
        self.window_width = window_width
        self.tolerance = tolerance
        self.transparent_color_hex = root.cget("bg")
        self.transparent_color_rgb = self._hex_to_rgb(self.transparent_color_hex)
        self.edge_color_rgb = self._hex_to_rgb(edge_color)
        self.base_image_path = "" # load_imagesで設定
        self.is_flipped = is_flipped

        self.image_label = tk.Label(root, bg=self.transparent_color_hex, borderwidth=0, highlightthickness=0)
        
        self.tk_images = {} # 読み込んだPIL.ImageTk.PhotoImageオブジェクトをキャッシュ
        self.current_emotion = "normal"
        self.is_showing_still = False # スチル表示中フラグ

        self.is_lip_syncing = False
        self.lip_sync_job = None

        self.press_time = 0
        self.press_pos = (0, 0)
        self.initial_window_pos = (0, 0)
        self.is_dragging = False
        self.drag_start_side_is_left = None
        self.click_time_threshold = self.config.getint('UI', 'CLICK_TIME_THRESHOLD_MS', fallback=300) / 1000.0
        self.click_move_threshold = self.config.getint('UI', 'CLICK_MOVE_THRESHOLD_PIXELS', fallback=5)
        
        self.char_config = char_config
        self.touch_areas = []
        self.cursor_path = self.config.get('UI', 'CURSOR_IMAGE_PATH', fallback='images/cursors')
        
        self.active_areas = []
        self.selected_index = 0
        self.active_cursor_name = None

        # テーママネージャーを取得
        theme = self.character_controller.mascot_app.theme_manager

        # アクションラベルのフォントを基準単位で指定
        self.action_label = tk.Label(
            self.root, text="", 
            bg=theme.get('tooltip_bg'),
            fg=theme.get('tooltip_text'),
            relief="solid", borderwidth=self.character_controller.mascot_app.border_width_normal, 
            font=self.character_controller.mascot_app.font_small
        )
        
        self.image_label.bind('<Button-1>', self.press_window)
        self.image_label.bind('<B1-Motion>', self.drag_window)
        self.image_label.bind('<ButtonRelease-1>', self.release_window)
        self.image_label.bind('<Motion>', self.check_cursor_change)
        self.image_label.bind('<Leave>', self.reset_cursor)
        self.image_label.bind('<MouseWheel>', self.on_mouse_wheel)

    def _hex_to_rgb(self, hex_color):
        if not hex_color or not hex_color.startswith('#'):
            return (255, 0, 255) # デフォルトのピンクを返す
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i*2:i*2+2], 16) for i in (0, 1, 2))

    def _process_transparency(self, img_pil, transparent_color_rgb, edge_color_rgb):
        """
        指定された背景色を透明化し、境界線を描画します。

        Args:
            img_pil (Image): 処理対象のPIL Imageオブジェクト。
            transparent_color_rgb (tuple): 透過させる色のRGBタプル。
            edge_color_rgb (tuple): 境界線の色のRGBタプル。
        """
        img_rgba = img_pil.convert("RGBA")
        img_np = np.array(img_rgba)
        
        rgb_pixels = img_np[:, :, :3].astype(np.int16)
        target_rgb = np.array(transparent_color_rgb, dtype=np.int16)
        diff = np.abs(rgb_pixels - target_rgb)
        
        # 許容誤差はself.toleranceを使い続ける
        is_transparent_mask = (diff <= self.tolerance).all(axis=2)
        
        dilated_mask = is_transparent_mask.copy()
        dilated_mask[:-1, :] |= is_transparent_mask[1:, :]
        dilated_mask[1:, :]  |= is_transparent_mask[:-1, :]
        dilated_mask[:, :-1] |= is_transparent_mask[:, 1:]
        dilated_mask[:, 1:]  |= is_transparent_mask[:, :-1]
        
        edge_mask = dilated_mask & ~is_transparent_mask
        
        img_np[edge_mask, :3] = edge_color_rgb
        img_np[is_transparent_mask, 3] = 0
        
        return Image.fromarray(img_np)
    
    def _load_single_image(self, path):
        """単一の画像ファイルを読み込み、リサイズと透明化処理を行ってTkinter形式で返します。"""
        try:
            with Image.open(path) as img_pil:
                if self.is_flipped:
                    img_pil = ImageOps.mirror(img_pil)
                aspect_ratio = img_pil.height / img_pil.width
                resized_img = img_pil.resize((self.window_width, int(self.window_width * aspect_ratio)), Image.Resampling.LANCZOS)
                processed_img = self._process_transparency(
                    resized_img, 
                    self.transparent_color_rgb, 
                    self.edge_color_rgb
                )
                return ImageTk.PhotoImage(processed_img)
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"画像読み込み中に予期せぬエラー: {path}, {e}")
            return None

    def load_images_and_touch_areas(self, image_path, available_emotions, char_config, touch_area_section):
        """
        指定されたパスから画像を、設定からタッチエリアを読み込みます。衣装変更時に呼び出されます。
        タッチエリアの読み込みは、デフォルトで 'normal' のものを読み込むように変更します。
        """
        print(f"アセットを読み込みます。画像パス: {image_path}, 利用可能感情: {list(available_emotions.keys())}")
        self.base_image_path = image_path
        self.tk_images.clear()

        # 衣装変更時は、まず基本となる 'normal' のタッチエリアを読み込む
        self.load_touch_areas_for_emotion('normal')

        scale = 1.0
        try:
            base_img_path = os.path.join(self.base_image_path, "normal_close.png")
            if not os.path.exists(base_img_path):
                base_img_path = os.path.join(self.base_image_path, "normal.png")

            with Image.open(base_img_path) as img_pil:
                scale = self.window_width / img_pil.width
                # 拡縮率の計算後、現在のタッチエリア座標を再計算
                self._convert_touch_area_coords(scale)
        except Exception as e:
            print(f"警告: 基準画像の読み込み中にエラー: {e}")

        # normalの画像を最初に読み込み、全感情のフォールバック先として確保する
        normal_jp = available_emotions.get('normal', 'normal')
        
        # 1. normalの各画像（standby, close, open, 無印）を読み込む
        normal_standby_img = self._load_single_image(os.path.join(self.base_image_path, "normal_standby.png"))
        normal_close_img = self._load_single_image(os.path.join(self.base_image_path, "normal_close.png"))
        normal_open_img = self._load_single_image(os.path.join(self.base_image_path, "normal_open.png"))
        normal_base_img = self._load_single_image(os.path.join(self.base_image_path, "normal.png")) # 旧形式
        
        # 2. normalのフォールバック画像を優先順位に従って決定する
        fallback_close = normal_close_img or normal_base_img
        fallback_standby = normal_standby_img or fallback_close
        fallback_open = normal_open_img or fallback_close
        
        if not fallback_standby: # 待機画像が最低一つはないと表示できない
            print(f"致命的エラー: 基準となる待機画像が見つかりません (normal_standby.png, normal_close.png, or normal.png)")
            return
            
        self.tk_images[normal_jp] = {
            'standby': fallback_standby,
            'close': fallback_close,
            'open': fallback_open
        }
        
        # 3. 定義された全感情について画像を読み込む
        for emotion_en, emotion_jp in available_emotions.items():
            if emotion_en == 'normal': continue

            # 各感情の画像パスを定義
            standby_path = os.path.join(self.base_image_path, f"{emotion_en}_standby.png")
            close_path = os.path.join(self.base_image_path, f"{emotion_en}_close.png")
            open_path = os.path.join(self.base_image_path, f"{emotion_en}_open.png")
            base_path = os.path.join(self.base_image_path, f"{emotion_en}.png")

            # 画像を読み込む（存在しなければNone）
            standby_img = self._load_single_image(standby_path)
            close_img = self._load_single_image(close_path)
            open_img = self._load_single_image(open_path)
            base_img = self._load_single_image(base_path)

            # 4. 各画像の最終的な表示物を優先順位に従って決定
            # 口閉じ: _close.png > .png > (normalの口閉じ)
            final_close_img = close_img or base_img or fallback_close
            # 待機: _standby.png > (↑で決まった口閉じ画像) > (normalの待機画像)
            final_standby_img = standby_img or final_close_img or fallback_standby
            # 口開き: _open.png > (↑で決まった口閉じ画像) > (normalの口開き画像)
            final_open_img = open_img or final_close_img or fallback_open

            self.tk_images[emotion_jp] = {
                'standby': final_standby_img,
                'close': final_close_img,
                'open': final_open_img
            }
            print(f"  - 感情 '{emotion_jp}' 読み込み完了 (待機画像分離: {standby_img is not None}, 口パク対応: {final_close_img != final_open_img})")

    def load_touch_areas_for_emotion(self, emotion_en: str):
        """
        指定された感情(英語ID)に対応するタッチエリアを読み込む。
        """
        costume_section = self.character_controller.costumes[self.character_controller.current_costume_id]['config_section']
        
        # CharacterDataから直接ini設定を読み込むのではなく、
        # CharacterControllerを経由して、マスコット本体が保持しているiniパーサーから読み込む
        char_config = self.character_controller.char_config
        
        self.touch_areas = []
        if not char_config.has_section(costume_section):
            print(f"情報: character.iniにタッチエリアセクション [{costume_section}] が見つかりませんでした。")
            return

        import re
        
        # 1. 指定された感情専用のパターン
        emotion_specific_pattern = re.compile(f'^touch_area_{re.escape(emotion_en)}_(\\d+)$')
        # 2. 基本となるnormal用のパターン
        normal_pattern = re.compile(r'^touch_area_(\d+)$')

        def _parse_areas_from_pattern(pattern):
            areas = []
            for key, value in char_config.items(costume_section):
                match = pattern.match(key)
                if match:
                    try:
                        parts = value.rsplit(',', 2)
                        if len(parts) != 3: continue
                        coords_def_str, action_name, cursor_name = [p.strip() for p in parts]
                        rect_list = ast.literal_eval(coords_def_str)
                        for rect in rect_list:
                             areas.append({
                                'original_rect': rect, 'scaled_rect': None,
                                'action': action_name, 'cursor': cursor_name
                            })
                    except (ValueError, SyntaxError, IndexError) as e:
                        print(f"タッチエリアの解析エラー ({key}): {e}")
            return areas

        # 指定された感情のエリアを探す
        parsed_areas = _parse_areas_from_pattern(emotion_specific_pattern)
        
        # 見つからなければ、または 'normal' が要求された場合は、normalのエリアを探す
        if not parsed_areas:
            parsed_areas = _parse_areas_from_pattern(normal_pattern)
            
        self.touch_areas = parsed_areas

    def _convert_touch_area_coords(self, scale):
        """元画像の座標で定義されたタッチエリアを、画面表示サイズに合わせて拡縮・反転します。"""
        for area in self.touch_areas:
            ox1, oy1, ox2, oy2 = area['original_rect']
            sx1, sy1, sx2, sy2 = ox1 * scale, oy1 * scale, ox2 * scale, oy2 * scale
            if self.is_flipped:
                flipped_sx1, flipped_sx2 = self.window_width - sx2, self.window_width - sx1
                area['scaled_rect'] = (flipped_sx1, sy1, flipped_sx2, sy2)
            else:
                area['scaled_rect'] = (sx1, sy1, sx2, sy2)

    def update_image(self, emotion_jp):
        """
        キャラクターの表情を指定された感情に更新します。
        表情が変わるタイミングで、対応するタッチエリアも再読み込みします。
        """
        # 新しい表情に更新する前に、スチル表示フラグをリセット
        self.is_showing_still = False
        
        if self.is_lip_syncing: return

        # 感情が変わる場合のみタッチエリアを再ロード
        if self.current_emotion != emotion_jp:
            self.current_emotion = emotion_jp
            
            # 日本語名から英語IDを逆引き
            jp_to_en_map = {v: k for k, v in self.character_controller.available_emotions.items()}
            emotion_en = jp_to_en_map.get(emotion_jp, 'normal')
            
            print(f"感情が '{emotion_jp}' ({emotion_en}) に変更されたため、タッチエリアを再読み込みします。")
            self.load_touch_areas_for_emotion(emotion_en)
            
            # 新しいタッチエリアに合わせて座標を再計算
            try:
                base_img_path = os.path.join(self.base_image_path, "normal_close.png")
                if not os.path.exists(base_img_path):
                     base_img_path = os.path.join(self.base_image_path, "normal.png")
                with Image.open(base_img_path) as img_pil:
                    scale = self.window_width / img_pil.width
                    self._convert_touch_area_coords(scale)
            except Exception as e:
                print(f"警告: タッチエリア座標の再計算中にエラー: {e}")
        
        # キャッシュから目的の画像を取得
        normal_emotion_jp = self.character_controller.available_emotions.get('normal', 'normal')
        
        # 表示する画像のセットを取得（なければnormalにフォールバック）
        target_image_set = self.tk_images.get(emotion_jp, self.tk_images.get(normal_emotion_jp, {}))
        
        # 待機状態なので 'standby' 画像を表示
        target_image = target_image_set.get('standby')
        
        if target_image:
            self.image_label.config(image=target_image)
        else:
            print(f"エラー: 感情 '{emotion_jp}' の待機画像も、フォールバック先の画像も読み込めませんでした。")

    def start_lip_sync(self, emotion_jp):
        """口パクアニメーションを開始します。"""
        if self.is_lip_syncing: return
        print(f"口パク開始: {emotion_jp}")
        self.is_lip_syncing = True
        self.current_emotion = emotion_jp # 口パク中の感情を保持
        self._animate_lip_sync()

    def stop_lip_sync(self):
        """口パクアニメーションを停止します。"""
        if not self.is_lip_syncing: return
        print("口パク停止")
        self.is_lip_syncing = False
        if self.lip_sync_job:
            self.root.after_cancel(self.lip_sync_job)
            self.lip_sync_job = None
        self.update_image(self.current_emotion)

    def _animate_lip_sync(self, is_open_mouth=True):
        """【再帰的メソッド】口の開閉を交互に繰り返してアニメーションさせます。"""
        if not self.is_lip_syncing: return
        
        state = 'open' if is_open_mouth else 'close'
        normal_emotion_jp = self.character_controller.available_emotions.get('normal', 'normal')
        target_image_set = self.tk_images.get(self.current_emotion, self.tk_images.get(normal_emotion_jp, {}))
        
        target_image = target_image_set.get(state)
        if not target_image: # 万が一stateの画像がない場合はcloseで代用
            target_image = target_image_set.get('close')

        if target_image:
            self.image_label.config(image=target_image)
        
        self.lip_sync_job = self.root.after(self.LIP_SYNC_INTERVAL_MS, self._animate_lip_sync, not is_open_mouth)
        
    def determine_display_emotion(self, emotion_percentages):
        """Gemma APIから受け取った感情のパーセンテージを基に、表示すべき表情（日本語名）を決定します。"""
        if not emotion_percentages: return "normal"
        primary_emotion = max(emotion_percentages, key=emotion_percentages.get)
        value = emotion_percentages[primary_emotion]
        
        # このメソッドは純粋にGemmaの分析結果から最も強い感情を返すことに専念します。
        # その感情が現在のキャラクターで利用可能かどうかの判断は、呼び出し元のDesktopMascotクラスで行います。
        if value < 40: return "normal"
        if primary_emotion == "喜": return "大喜" if value >= 75 else "喜"
        if primary_emotion == "怒": return "大怒" if value >= 75 else "怒"
        if primary_emotion == "哀": return "大哀" if value >= 75 else "哀"
        if primary_emotion == "楽": return "大楽" if value >= 75 else "楽"
        # ユーザーが定義する可能性のある、より単純な感情名
        if primary_emotion in ["照", "恥", "困", "驚"]: return primary_emotion
        return "normal"

    def press_window(self, event):
        """画像上でマウスボタンが押されたときの処理。"""
        self.press_time = time.time()
        self.press_pos = (event.x_root, event.y_root)
        self.initial_window_pos = (self.toplevel_window.winfo_x(), self.toplevel_window.winfo_y())
        self.is_dragging = False
        # ドラッグ開始時のサイドを記録
        screen_center_x = self.toplevel_window.winfo_screenwidth() / 2
        window_center_x = self.toplevel_window.winfo_x() + (self.toplevel_window.winfo_width() / 2)
        self.drag_start_side_is_left = window_center_x < screen_center_x

    def drag_window(self, event):
        """マウスドラッグ中の処理。"""
        self.is_dragging = True
        dx = event.x_root - self.press_pos[0]
        dy = event.y_root - self.press_pos[1]
        new_x = self.initial_window_pos[0] + dx
        new_y = self.initial_window_pos[1] + dy
        self.toplevel_window.move_with_heart(new_x, new_y) # 新しいメソッドを呼び出す

    def release_window(self, event):
        """マウスボタンが離されたときの処理。クリックかドラッグかを判定します。"""
        duration = time.time() - self.press_time
        distance = ((event.x_root - self.press_pos[0])**2 + (event.y_root - self.press_pos[1])**2)**0.5
        
        is_click = duration < self.click_time_threshold and distance < self.click_move_threshold

        if not is_click and self.is_dragging:
            # --- ドラッグ操作が完了したと判断 ---
            # 1. ドラッグ終了時のサイドを計算
            screen_center_x = self.toplevel_window.winfo_screenwidth() / 2
            window_center_x = self.toplevel_window.winfo_x() + (self.toplevel_window.winfo_width() / 2)
            drag_end_side_is_left = window_center_x < screen_center_x
            
            # 2. 開始時と終了時でサイドが変わったか（中央をまたいだか）を判定
            if self.drag_start_side_is_left is not None and self.drag_start_side_is_left != drag_end_side_is_left:
                # 3a. サイドをまたいでいたら、反転処理を呼び出す
                self.character_controller.flip_character()
            else:
                # 3b. サイドをまたいでいなければ、レイアウト更新のみ行う
                self.toplevel_window.check_and_update_layout()

        if is_click:
            # クリックだった場合は、ドラッグ前の位置に戻す
            if self.is_dragging:
                self.toplevel_window.move_with_heart(self.initial_window_pos[0], self.initial_window_pos[1])
            
            # タッチエリアの判定
            if self.active_areas:
                selected_action = self.active_areas[self.selected_index]['action']
                print(f"タッチエリア '{selected_action}' がクリックされました。")
                self.character_controller.handle_touch_action(selected_action)
        
        self.is_dragging = False

    def check_cursor_change(self, event):
        """マウスカーソルが動くたびに呼び出され、タッチエリア上にあるかを確認します。"""
        areas_under_cursor = self._get_all_touch_areas_at(event.x, event.y)

        if areas_under_cursor != self.active_areas:
            self.active_areas = areas_under_cursor
            self.selected_index = 0
            self._update_action_display(event)
        elif self.active_areas:
            # アクションラベルの表示位置を基準単位でオフセット
            app = self.character_controller.mascot_app
            x_offset = app.padding_large
            y_offset = app.padding_normal
            self.action_label.place(x=event.x + x_offset, y=event.y + y_offset)

    def on_mouse_wheel(self, event):
        """マウスホイールが回転したときの処理。重なったタッチエリアの選択を切り替えます。"""
        if len(self.active_areas) <= 1: return

        if event.delta > 0:
            self.selected_index = (self.selected_index - 1 + len(self.active_areas)) % len(self.active_areas)
        else:
            self.selected_index = (self.selected_index + 1) % len(self.active_areas)
        
        self._update_action_display(event)
        
    def _update_action_display(self, event):
        """カーソルとアクション名ラベルの表示を、現在の状態に合わせて更新します。"""
        if not self.active_areas:
            if self.active_cursor_name:
                self.image_label.config(cursor="")
                self.active_cursor_name = None
            self.action_label.place_forget()
            return
        
        self.action_label.lift()
        selected_area = self.active_areas[self.selected_index]
        cursor_name = selected_area['cursor']
        action_name = selected_area['action']

        # 1. action_name内の "\n" を実際の改行文字に置換
        processed_action_name = action_name.replace('\\n', '\n')

        # 2. 表示テキストを作成
        display_text = processed_action_name
        if len(self.active_areas) > 1:
            display_text += f"\n({self.selected_index + 1}/{len(self.active_areas)})"

        # 3. wraplength を計算
        app = self.character_controller.mascot_app
        
        # --- 制約1: 画面右端までの距離 ---
        cursor_x_root = self.image_label.winfo_rootx() + event.x
        screen_width = self.image_label.winfo_screenwidth()
        margin_screen = app.padding_large # 画面端の余白
        available_width_screen = screen_width - cursor_x_root - margin_screen

        # --- 制約2: キャラクターウィンドウ右端までの距離 ---
        # ツールチップのX座標は、キャラクター画像(image_label)の左端からの相対位置
        # event.x がカーソルの相対X座標
        tooltip_x_in_label = event.x + app.padding_large # ツールチップの開始X座標
        label_width = self.image_label.winfo_width()
        margin_window = app.padding_small # ウィンドウ内の余白
        available_width_window = label_width - tooltip_x_in_label - margin_window
        
        # --- 2つの制約のうち、より厳しい方（小さい方）を採用 ---
        wraplength = min(available_width_screen, available_width_window)

        # wraplengthは正の値である必要があるため、0以下にならないようにする
        wraplength = max(1, wraplength)

        # 4. ラベルにテキストとwraplengthを設定
        self.action_label.config(text=display_text, wraplength=wraplength, justify='left')
        
        # アクションラベルの表示位置を基準単位でオフセット
        x_offset = app.padding_large
        y_offset = app.padding_normal
        self.action_label.place(x=event.x + x_offset, y=event.y + y_offset)

        if cursor_name != self.active_cursor_name:
            cursor_file = os.path.join(self.cursor_path, f"{cursor_name}.cur")
            if os.path.exists(cursor_file):
                cursor_file_for_tk = cursor_file.replace('\\', '/')
                self.image_label.config(cursor=f"@{cursor_file_for_tk}")
            else:
                self.image_label.config(cursor="")
            self.active_cursor_name = cursor_name

    def reset_cursor(self, event):
        """マウスカーソルがキャラクターウィンドウから離れたときの処理。"""
        self.active_areas = []
        self.selected_index = 0
        self._update_action_display(event)
    
    def _get_all_touch_areas_at(self, x, y):
        """指定された座標に重なっている全てのタッチエリアをリストとして返します。"""
        overlapping_areas = []
        for area in self.touch_areas:
            if area['scaled_rect']:
                x1, y1, x2, y2 = area['scaled_rect']
                if x1 <= x <= x2 and y1 <= y <= y2:
                    overlapping_areas.append(area)
        return overlapping_areas
    
    def reload_theme(self):
        """
        アクションラベルのテーマカラーを再適用します。
        """
        theme = self.character_controller.mascot_app.theme_manager
        self.action_label.config(
            bg=theme.get('tooltip_bg'),
            fg=theme.get('tooltip_text')
        )
