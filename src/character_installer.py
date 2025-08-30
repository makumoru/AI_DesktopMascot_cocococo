# src/character_installer.py

import tkinter as tk
from tkinter import messagebox, filedialog
import zipfile
import json
import os
import shutil

class CharacterInstaller:
    """
    キャラクターZIPファイルを解析し、charactersフォルダにインストールするクラス。
    """
    def __init__(self, parent: tk.Tk, characters_dir: str):
        self.parent = parent
        self.characters_dir = characters_dir

    def install_from_zip(self, zip_path: str):
        """ZIPファイルからキャラクターのインストールを開始するエントリーポイント"""
        parent_zip_dir = os.path.dirname(zip_path)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_file:
                # 1. package_info.json の存在確認と読み込み
                if 'package_info.json' not in zip_file.namelist():
                    raise ValueError("キャラクターパッケージ情報(package_info.json)が見つかりません。")
                
                with zip_file.open('package_info.json') as f:
                    package_info = json.load(f)

                # 2. package_infoの内容に基づいて処理を分岐
                package_type = package_info.get('package_type')
                if package_type == 'complete':
                    self._install_complete(zip_file, package_info)
                elif package_type == 'split':
                    self._handle_split_package(zip_file, package_info, initial_dir=parent_zip_dir)
                else:
                    raise ValueError(f"不明なパッケージタイプです: {package_type}")

        except zipfile.BadZipFile:
            messagebox.showerror("エラー", "ZIPファイルが破損しているか、無効な形式です。", parent=self.parent)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            messagebox.showerror("インストールエラー", str(e), parent=self.parent)
        except Exception as e:
            messagebox.showerror("予期せぬエラー", f"インストール中に予期せぬエラーが発生しました:\n{e}", parent=self.parent)

    def _prepare_target_directory(self, character_id: str) -> str | None:
        """
        インストール先のディレクトリを準備する。
        既存の場合は上書き確認を行い、ユーザーがキャンセルした場合はNoneを返す。
        """
        target_path = os.path.join(self.characters_dir, character_id)
        if os.path.exists(target_path):
            if not messagebox.askyesno("上書き確認", 
                f"キャラクター '{character_id}' は既に存在します。\n"
                "上書きしてよろしいですか？ (既存のデータは完全に削除されます)",
                parent=self.parent):
                return None # ユーザーがキャンセル
            
            print(f"既存のフォルダを削除します: {target_path}")
            shutil.rmtree(target_path)
        
        os.makedirs(target_path)
        return target_path

    def _install_complete(self, zip_file: zipfile.ZipFile, package_info: dict):
        """単独のZIPファイルをインストールする"""
        character_id = package_info['character_id']
        print(f"単独パッケージ '{character_id}' のインストールを開始します。")

        target_path = self._prepare_target_directory(character_id)
        if target_path is None:
            messagebox.showinfo("中止", "インストールを中止しました。", parent=self.parent)
            return

        zip_file.extractall(path=target_path)
        messagebox.showinfo("成功", f"キャラクター '{character_id}' のインストールが完了しました。", parent=self.parent)

    def _handle_split_package(self, zip_file: zipfile.ZipFile, package_info: dict, initial_dir: str):
        """分割ZIPファイルを処理する"""
        role = package_info.get('package_role')
        if role == 'parent':
            self._install_split_parent(zip_file, package_info, initial_dir=initial_dir)
        elif role == 'child':
            parent_part = package_info.get('parent_part', '不明')
            base_id = package_info.get('base_id', '不明')
            raise ValueError(
                "これは子ファイルです。先に親ファイルをインストールしてください。\n\n"
                f"親ファイル: {base_id}_{parent_part}.zip"
            )
        else:
            raise ValueError(f"不明なパッケージロールです: {role}")

    def _install_split_parent(self, zip_file: zipfile.ZipFile, package_info: dict, initial_dir: str):
        """分割ZIPの親ファイルをインストールし、続けて子ファイルのインストールを促す"""
        character_id = package_info['character_id']
        child_parts = package_info.get('child_parts', [])
        
        print(f"分割パッケージ(親) '{character_id}' のインストールを開始します。")
        target_path = self._prepare_target_directory(character_id)
        if target_path is None:
            messagebox.showinfo("中止", "インストールを中止しました。", parent=self.parent)
            return

        # まず親ファイルの内容を解凍
        zip_file.extractall(path=target_path)
        print(f"親ファイル '{character_id}' を解凍しました。")

        # 続けて子ファイルのインストールを促す
        for part_name in child_parts:
            child_zip_filename = f"{character_id}_{part_name}.zip"
            
            # ファイル選択ダイアログを表示
            child_zip_path = filedialog.askopenfilename(
                title=f"子ファイルの選択: {part_name}",
                initialfile=child_zip_filename,
                initialdir=initial_dir,
                filetypes=[("ZIP files", "*.zip")],
                parent=self.parent
            )

            if not child_zip_path: # ユーザーがダイアログをキャンセル
                shutil.rmtree(target_path) # 中途半端なインストールなのでフォルダを削除
                messagebox.showwarning("中止", "子ファイルの選択がキャンセルされたため、インストールを中断しました。", parent=self.parent)
                return

            # 選択された子ファイルを検証して解凍
            try:
                with zipfile.ZipFile(child_zip_path, 'r') as child_zip:
                    if 'package_info.json' not in child_zip.namelist():
                        raise ValueError("子ファイルにpackage_info.jsonが見つかりません。")
                    with child_zip.open('package_info.json') as f:
                        child_info = json.load(f)
                    
                    # 検証
                    if not (child_info.get('base_id') == character_id and child_info.get('part_name') == part_name):
                        raise ValueError(f"選択されたZIPは要求された '{part_name}' ではありません。")

                    # 検証OKなら解凍
                    child_zip.extractall(path=target_path)
                    print(f"子ファイル '{part_name}' を解凍しました。")

            except Exception as e:
                shutil.rmtree(target_path) # エラー時もフォルダを削除
                messagebox.showerror("エラー", f"'{part_name}'の処理中にエラーが発生しました。\nインストールを中断します。\n\n詳細: {e}", parent=self.parent)
                return
        
        messagebox.showinfo("成功", f"キャラクター '{character_id}' (分割)のインストールが完了しました。", parent=self.parent)