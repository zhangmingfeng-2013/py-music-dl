#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
音乐下载器 GUI 版
使用 tkinter 构建图形界面
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from music import MusicAPI, MusicDownloader, safe_filename, format_size, DOWNLOAD_DIR


class MusicDownloaderGUI:
    """音乐下载器图形界面主类"""

    def __init__(self, root):
        self.root = root
        self.root.title("🎵 音乐下载器 v1.0")
        self.root.geometry("900x650")
        self.root.resizable(True, True)

        # 核心功能类
        self.music_api = MusicAPI()
        self.downloader = MusicDownloader()

        # 当前搜索结果
        self.search_results = []

        # 下载目录
        self.download_dir = DOWNLOAD_DIR
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

        self._setup_ui()

    def _setup_ui(self):
        """设置界面布局"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)

        # 1. 搜索区域
        search_frame = ttk.LabelFrame(main_frame, text="搜索音乐", padding="10")
        search_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        search_frame.columnconfigure(0, weight=1)

        ttk.Label(search_frame, text="歌曲名：").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.search_entry = ttk.Entry(search_frame, font=("Arial", 12))
        self.search_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        self.search_entry.focus_set()
        self.search_entry.bind("<Return>", lambda e: self._on_search())

        self.search_btn = ttk.Button(search_frame, text="🔍 搜索", command=self._on_search)
        self.search_btn.grid(row=0, column=2, padx=5)

        ttk.Label(search_frame, text="下载目录：").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        self.path_var = tk.StringVar(value=self.download_dir)
        self.path_entry = ttk.Entry(search_frame, textvariable=self.path_var, font=("Arial", 10))
        self.path_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=(10, 0))

        self.browse_btn = ttk.Button(search_frame, text="📂 选择", command=self._browse_dir)
        self.browse_btn.grid(row=1, column=2, padx=5, pady=(10, 0))

        # 2. 进度和状态信息
        self.status_var = tk.StringVar(value="准备就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))

        # 3. 结果表格
        results_frame = ttk.LabelFrame(main_frame, text="搜索结果", padding="10")
        results_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        # 创建表格
        columns = ("index", "title", "artist", "source", "quality")
        self.tree = ttk.Treeview(results_frame, columns=columns, show="headings", height=15)
        
        self.tree.heading("index", text="序号")
        self.tree.heading("title", text="歌曲名")
        self.tree.heading("artist", text="歌手")
        self.tree.heading("source", text="来源")
        self.tree.heading("quality", text="音质")

        self.tree.column("index", width=60, anchor=tk.CENTER)
        self.tree.column("title", width=280)
        self.tree.column("artist", width=180)
        self.tree.column("source", width=100)
        self.tree.column("quality", width=80, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        results_frame.columnconfigure(0, weight=1)

        # 双击下载
        self.tree.bind("<Double-1>", lambda e: self._on_download_selected())

        # 4. 操作按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=1, column=0, columnspan=2, pady=5)

        self.download_btn = ttk.Button(button_frame, text="⬇️ 下载选中歌曲", command=self._on_download_selected, state=tk.DISABLED)
        self.download_btn.grid(row=0, column=0, padx=5)

        ttk.Button(button_frame, text="📁 打开下载目录", command=self._open_download_dir).grid(row=0, column=1, padx=5)

        ttk.Button(button_frame, text="❌ 清空结果", command=self._clear_results).grid(row=0, column=2, padx=5)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="日志", padding="10")
        log_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    def _log(self, message):
        """添加日志"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _browse_dir(self):
        """浏览选择下载目录"""
        dir_path = filedialog.askdirectory(initialdir=self.download_dir)
        if dir_path:
            self.download_dir = dir_path
            self.path_var.set(dir_path)

    def _open_download_dir(self):
        """打开下载目录"""
        if os.path.exists(self.download_dir):
            os.system(f"open '{self.download_dir}'")

    def _clear_results(self):
        """清空搜索结果"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.search_results = []
        self.download_btn.config(state=tk.DISABLED)
        self._log("已清空搜索结果")

    def _on_search(self):
        """搜索按钮回调"""
        keyword = self.search_entry.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入要搜索的歌曲名")
            return

        # 禁用搜索按钮防止重复点击
        self.search_btn.config(state=tk.DISABLED)
        self._clear_results()
        self._log(f"正在搜索: {keyword}")
        self.status_var.set("正在搜索...")

        # 在新线程中搜索
        threading.Thread(target=self._search_thread, args=(keyword,), daemon=True).start()

    def _search_thread(self, keyword):
        """搜索线程"""
        try:
            results = self.downloader.search_all(keyword)
            self.search_results = results

            if results:
                # 在主线程更新UI
                self.root.after(0, self._populate_results, results)
                self._log(f"搜索完成，找到 {len(results)} 首歌曲")
                self.root.after(0, lambda: self.status_var.set(f"找到 {len(results)} 首歌曲"))
            else:
                self._log("未找到相关歌曲")
                self.root.after(0, lambda: self.status_var.set("未找到相关歌曲"))
        except Exception as e:
            self._log(f"搜索出错: {e}")
            self.root.after(0, lambda: self.status_var.set("搜索出错"))
        finally:
            self.root.after(0, lambda: self.search_btn.config(state=tk.NORMAL))

    def _populate_results(self, results):
        """填充搜索结果到表格"""
        for idx, song in enumerate(results, 1):
            title = song.get("title", "") or song.get("name", "")
            artist = song.get("artist", "") or song.get("singer", "")
            source = song.get("source_name", song.get("source", "?"))
            quality = song.get("quality", "?")

            # 截断过长文本
            if len(title) > 30:
                title = title[:27] + "..."
            if len(artist) > 20:
                artist = artist[:17] + "..."

            self.tree.insert("", tk.END, values=(idx, title, artist, source, quality))

        if results:
            self.download_btn.config(state=tk.NORMAL)

    def _on_download_selected(self):
        """下载选中歌曲"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择要下载的歌曲")
            return

        item = selected[0]
        idx = int(self.tree.item(item, "values")[0]) - 1
        song = self.search_results[idx]

        title = song.get("title") or song.get("name", "")
        artist = song.get("artist") or song.get("singer", "")

        self._log(f"准备下载: {title} - {artist}")
        self.status_var.set("正在获取下载链接...")
        self.download_btn.config(state=tk.DISABLED)

        # 在新线程中下载
        threading.Thread(target=self._download_thread, args=(song,), daemon=True).start()

    def _download_thread(self, song):
        """下载线程"""
        try:
            # 获取详情
            self._log("正在获取下载链接...")
            detail = self.downloader.get_detail(song)

            if not detail or not detail.get("audio_url"):
                self._log("无法获取下载链接")
                self.root.after(0, lambda: self.status_var.set("无法获取下载链接"))
                self.root.after(0, lambda: self.download_btn.config(state=tk.NORMAL))
                return

            audio_url = detail["audio_url"]
            quality = detail.get("quality", "")
            title = detail.get("title", song.get("title") or song.get("name", ""))
            artist = detail.get("artist", song.get("artist") or song.get("singer", ""))

            self._log(f"音质: {quality}")

            # 下载
            self._log("开始下载...")
            self.root.after(0, lambda: self.status_var.set("正在下载..."))

            success = self._download_mp3(title, artist, audio_url, quality)

            if success:
                self._log("下载完成!")
                self.root.after(0, lambda: self.status_var.set("下载完成"))
            else:
                self._log("下载失败")
                self.root.after(0, lambda: self.status_var.set("下载失败"))

        except Exception as e:
            self._log(f"下载出错: {e}")
            self.root.after(0, lambda: self.status_var.set("下载出错"))
        finally:
            self.root.after(0, lambda: self.download_btn.config(state=tk.NORMAL))

    def _download_mp3(self, title, artist, audio_url, quality=""):
        """下载音乐文件"""
        import requests
        from music import HEADERS

        safe_name = safe_filename(f"{artist} - {title}")
        if quality == "LOSSLESS":
            ext = audio_url.split("?")[0].rsplit(".", 1)[-1].lower() if "." in audio_url.split("?")[0] else "mp3"
        else:
            ext = "mp3"
        if ext not in ("mp3", "flac", "wav", "ape", "m4a", "ogg"):
            ext = "mp3"

        filename = f"{safe_name}.{ext}"
        filepath = os.path.join(self.download_dir, filename)

        try:
            resp = requests.get(audio_url, headers=HEADERS, stream=True, timeout=120, verify=False)
            resp.raise_for_status()

            total_size = int(resp.headers.get("content-length", 0))
            if total_size > 0:
                self._log(f"文件大小: {format_size(total_size)}")

            downloaded = 0
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = int(downloaded / total_size * 100)
                            self.root.after(0, lambda p=percent: self.status_var.set(f"下载中 {p}%"))

            self._log(f"保存到: {filepath}")
            return True

        except Exception as e:
            self._log(f"下载失败: {e}")
            return False


def main():
    root = tk.Tk()
    app = MusicDownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
