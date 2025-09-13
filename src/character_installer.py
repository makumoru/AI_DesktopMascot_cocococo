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
                f"親ファイル: {base_id}_{parent_part}.zip (GitHubからは default.zip としてダウンロードされた可能性があります)"
            )
        else:
            raise ValueError(f"不明なパッケージロールです: {role}")


    def _install_split_parent(self, zip_file: zipfile.ZipFile, package_info: dict, initial_dir: str):
        """分割ZIPの親ファイルをインストールし、続けて子ファイルのインストールを順不同で受け付ける"""
        character_id = package_info['character_id']
        required_child_parts = package_info.get('child_parts', [])
        
        print(f"分割パッケージ(親) '{character_id}' のインストールを開始します。")
        target_path = self._prepare_target_directory(character_id)
        if target_path is None:
            messagebox.showinfo("中止", "インストールを中止しました。", parent=self.parent)
            return

        try:
            # まず親ファイルの内容を解凍
            zip_file.extractall(path=target_path)
            print(f"親ファイル '{character_id}' を解凍しました。")

            # インストール済みの子パーツ名を記録するセット
            installed_parts = set()
            
            # 全ての子パーツがインストールされるまでループ
            while len(installed_parts) < len(required_child_parts):
                remaining_parts = set(required_child_parts) - installed_parts
                
                # ファイル選択ダイアログを表示
                child_zip_path = filedialog.askopenfilename(
                    title=f"子ファイルを選択してください (残り: {', '.join(remaining_parts)})",
                    initialdir=initial_dir,
                    filetypes=[("ZIP files", "*.zip")],
                    parent=self.parent
                )

                if not child_zip_path: # ユーザーがダイアログをキャンセル
                    raise InterruptedError("子ファイルの選択がキャンセルされたため、インストールを中断しました。")

                # 選択された子ファイルを検証して解凍
                try:
                    with zipfile.ZipFile(child_zip_path, 'r') as child_zip:
                        if 'package_info.json' not in child_zip.namelist():
                            messagebox.showwarning("検証エラー", "選択されたZIPにはpackage_info.jsonが見つかりません。\n別のファイルを選択してください。", parent=self.parent)
                            continue # ループの先頭に戻り、再度ファイル選択を促す

                        with child_zip.open('package_info.json') as f:
                            child_info = json.load(f)
                        
                        part_name = child_info.get('part_name')

                        # --- 検証ロジック ---
                        if child_info.get('base_id') != character_id:
                            messagebox.showwarning("検証エラー", f"違うキャラクターの子ファイルです。(要求: {character_id}) \n別のファイルを選択してください。", parent=self.parent)
                            continue
                        
                        if child_info.get('package_role') != 'child':
                            messagebox.showwarning("検証エラー", "これは子ファイルではありません。\n別のファイルを選択してください。", parent=self.parent)
                            continue

                        if part_name not in required_child_parts:
                            messagebox.showwarning("検証エラー", f"このキャラクターに不要なパーツです。(パーツ名: {part_name})\n別のファイルを選択してください。", parent=self.parent)
                            continue

                        if part_name in installed_parts:
                            messagebox.showinfo("情報", f"パーツ '{part_name}' は既にインストール済みです。\n別のファイルを選択してください。", parent=self.parent)
                            continue

                        # --- 検証OKなら解凍 ---
                        child_zip.extractall(path=target_path)
                        installed_parts.add(part_name)
                        print(f"子ファイル '{part_name}' を解凍しました。")
                        messagebox.showinfo("成功", f"パーツ '{part_name}' を正常にインストールしました。", parent=self.parent)

                except zipfile.BadZipFile:
                    messagebox.showwarning("ファイルエラー", "選択されたZIPファイルが破損しています。\n別のファイルを選択してください。", parent=self.parent)
                    continue
                except (ValueError, KeyError, json.JSONDecodeError):
                    messagebox.showwarning("ファイルエラー", "選択されたZIPファイルの package_info.json が不正です。\n別のファイルを選択してください。", parent=self.parent)
                    continue

        except (Exception, InterruptedError) as e:
            # エラーや中断が発生した場合、中途半端なインストールにならないようフォルダを削除
            if os.path.exists(target_path):
                shutil.rmtree(target_path)
            messagebox.showerror("インストール中断", f"処理が中断されたため、インストールを取り消しました。\n\n詳細: {e}", parent=self.parent)
            return
        
        messagebox.showinfo("成功", f"キャラクター '{character_id}' (分割)のインストールが完了しました。", parent=self.parent)
