#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
音乐下载器 GUI 版
功能：根据用户输入的歌曲名，从多平台搜索并下载MP3/FLAC音乐文件
数据源：基于 http://qjjlb.quanjian.com.cn/musicdl/ 的聚合音乐站API
支持平台：咪咕音乐 / 网易云音乐 / QQ音乐 / 酷我音乐
使用库：requests（网络请求）、bs4（HTML解析）、re（正则匹配）、tkinter（图形库）
注意：仅供学习爬虫技术，请遵守网站协议和版权规定，勿用于商业用途
"""

import os
import json
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from music import MusicDownloader, DOWNLOAD_DIR


class SearchHistory:
    """搜索历史管理类"""

    def __init__(self, history_file="search_history.json", max_items=20):
        self.history_file = history_file
        self.max_items = max_items
        self.history = self._load_history()

    def _load_history(self):
        """加载历史记录"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_history(self):
        """保存历史记录"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add(self, keyword):
        """添加搜索关键词"""
        if not keyword or not keyword.strip():
            return
        keyword = keyword.strip()
        if keyword in self.history:
            self.history.remove(keyword)
        self.history.insert(0, keyword)
        if len(self.history) > self.max_items:
            self.history = self.history[:self.max_items]
        self._save_history()

    def get_all(self):
        """获取所有历史记录"""
        return self.history.copy()

    def clear(self):
        """清空历史记录"""
        self.history = []
        self._save_history()


class MusicDownloaderGUI:
    """音乐下载器图形界面主类"""

    def __init__(self, root):
        self.root = root
        self.root.title("🎵 音乐下载器 v1.0")
        self.root.geometry("900x650")
        self.root.resizable(True, True)

        # 核心功能类
        self.downloader = MusicDownloader()

        # 当前搜索结果
        self.search_results = []
        self.filtered_results = []

        # 搜索历史管理
        self.search_history = SearchHistory()

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
        search_frame.columnconfigure(2, weight=1)

        # 搜索建议下拉框
        ttk.Label(search_frame, text="歌曲名：").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_combo = ttk.Combobox(search_frame, textvariable=self.search_var, 
                                         font=("Arial", 12))
        self.search_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        self.search_combo['values'] = self.search_history.get_all()
        self.search_combo.bind('<<ComboboxSelected>>', self._on_combo_select)
        self.search_combo.bind('<KeyRelease>', self._on_search_keyrelease)
        self.search_combo.bind('<Return>', lambda e: self._on_search())
        self.search_combo.focus_set()

        self.search_btn = ttk.Button(search_frame, text="🔍 搜索", command=self._on_search)
        self.search_btn.grid(row=0, column=2, padx=5)

        ttk.Label(search_frame, text="下载目录：").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        self.path_var = tk.StringVar(value=self.download_dir)
        self.path_entry = ttk.Entry(search_frame, textvariable=self.path_var, font=("Arial", 10))
        self.path_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=(10, 0))

        self.browse_btn = ttk.Button(search_frame, text="📂 选择", command=self._browse_dir)
        self.browse_btn.grid(row=1, column=2, padx=5, pady=(10, 0))

        # 2. 筛选区域
        filter_frame = ttk.LabelFrame(main_frame, text="筛选结果", padding="5")
        filter_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(3, weight=1)

        ttk.Label(filter_frame, text="歌手：").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.artist_filter_var = tk.StringVar()
        self.artist_filter_combo = ttk.Combobox(filter_frame, textvariable=self.artist_filter_var,
                                                font=("Arial", 10), state='readonly')
        self.artist_filter_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        self.artist_filter_combo.bind('<<ComboboxSelected>>', self._on_filter_change)
        self.artist_filter_combo['values'] = ['全部']

        ttk.Label(filter_frame, text="平台：").grid(row=0, column=2, sticky=tk.W, padx=(10, 5))
        self.source_filter_var = tk.StringVar()
        self.source_filter_combo = ttk.Combobox(filter_frame, textvariable=self.source_filter_var,
                                                 font=("Arial", 10), state='readonly')
        self.source_filter_combo.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=5)
        self.source_filter_combo['values'] = ['全部']
        self.source_filter_combo.bind('<<ComboboxSelected>>', self._on_filter_change)

        self.clear_filter_btn = ttk.Button(filter_frame, text="清除筛选", command=self._clear_filter)
        self.clear_filter_btn.grid(row=0, column=4, padx=(10, 0))

        # 3. 进度和状态信息
        self.status_var = tk.StringVar(value="准备就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))

        # 4. 结果表格
        results_frame = ttk.LabelFrame(main_frame, text="搜索结果", padding="10")
        results_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
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

        # 5. 操作按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, columnspan=2, pady=5)

        self.download_btn = ttk.Button(button_frame, text="⬇️ 下载选中歌曲", command=self._on_download_selected, state=tk.DISABLED)
        self.download_btn.grid(row=0, column=0, padx=5)

        ttk.Button(button_frame, text="📁 打开下载目录", command=self._open_download_dir).grid(row=0, column=1, padx=5)

        ttk.Button(button_frame, text="❌ 清空结果", command=self._clear_results).grid(row=0, column=2, padx=5)

        ttk.Button(button_frame, text="📋 清空历史", command=self._clear_history).grid(row=0, column=3, padx=5)

        # 6. 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="日志", padding="10")
        log_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    def _log(self, message):
        """添加日志"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _on_combo_select(self, event=None):
        """下拉框选择事件"""
        selected = self.search_var.get()
        if selected:
            self._on_search()

    def _on_search_keyrelease(self, event):
        """键盘释放事件，用于搜索建议"""
        current_text = self.search_var.get()
        if not current_text:
            return
        
        # 获取匹配的历史记录
        history = self.search_history.get_all()
        matches = [h for h in history if current_text.lower() in h.lower()]
        
        if matches:
            self.search_combo['values'] = matches
        else:
            # 没有匹配时显示所有历史
            self.search_combo['values'] = history

    def _on_filter_change(self, event=None):
        """筛选条件改变时重新显示结果"""
        artist_filter = self.artist_filter_var.get()
        source_filter = self.source_filter_var.get()

        # 应用筛选
        self.filtered_results = []
        for song in self.search_results:
            # 按歌手筛选
            if artist_filter != '全部':
                artist = song.get("artist", "") or song.get("singer", "")
                if artist_filter not in artist:
                    continue

            # 按平台筛选
            if source_filter != '全部':
                source = song.get("source_name", "")
                if source_filter != source:
                    continue

            self.filtered_results.append(song)

        # 更新显示
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        for idx, song in enumerate(self.filtered_results, 1):
            title = song.get("title", "") or song.get("name", "")
            artist = song.get("artist", "") or song.get("singer", "")
            source = song.get("source_name", song.get("source", "?"))
            quality = song.get("quality", "?")

            if len(title) > 30:
                title = title[:27] + "..."
            if len(artist) > 20:
                artist = artist[:17] + "..."

            self.tree.insert("", tk.END, values=(idx, title, artist, source, quality))

        self.status_var.set(f"筛选结果: {len(self.filtered_results)} 首歌曲")

    def _clear_filter(self):
        """清除筛选条件"""
        self.artist_filter_var.set('全部')
        self.source_filter_var.set('全部')
        self.filtered_results = self.search_results.copy()
        self._on_filter_change()

    def _clear_history(self):
        """清空搜索历史"""
        self.search_history.clear()
        self.search_combo['values'] = []
        messagebox.showinfo("提示", "搜索历史已清空")

    def _update_filter_options(self):
        """更新筛选选项"""
        artists = set()
        sources = set()
        
        for song in self.search_results:
            artist = song.get("artist", "") or song.get("singer", "")
            if artist:
                artists.add(artist)
            
            source = song.get("source_name", "")
            if source:
                sources.add(source)
        
        self.artist_filter_combo['values'] = ['全部'] + sorted(list(artists))
        self.source_filter_combo['values'] = ['全部'] + sorted(list(sources))
        self.artist_filter_var.set('全部')
        self.source_filter_var.set('全部')

    def _browse_dir(self):
        """浏览选择下载目录"""
        dir_path = filedialog.askdirectory(initialdir=self.download_dir)
        if dir_path:
            self.download_dir = dir_path
            self.path_var.set(dir_path)

    def _open_download_dir(self):
        """打开下载目录"""
        if os.path.exists(self.download_dir):
            subprocess.run(["open", self.download_dir])

    def _clear_results(self):
        """清空搜索结果"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.search_results = []
        self.filtered_results = []
        self.download_btn.config(state=tk.DISABLED)
        self._log("已清空搜索结果")
        self._clear_filter()

    def _on_search(self):
        """搜索按钮回调"""
        keyword = self.search_var.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入要搜索的歌曲名")
            return

        # 添加到历史记录
        self.search_history.add(keyword)
        self.search_combo['values'] = self.search_history.get_all()

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
            self.search_results = results.copy()
            self.filtered_results = results.copy()

            if results:
                # 在主线程更新UI
                self.root.after(0, self._populate_results, results)
                self.root.after(0, lambda: self.status_var.set(f"找到 {len(results)} 首歌曲"))
                self.root.after(0, self._update_filter_options)
                self._log(f"搜索完成，找到 {len(results)} 首歌曲")
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
        song = self.filtered_results[idx]

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
        """下载音乐文件（委托给 MusicDownloader.download_mp3）"""
        def progress_cb(downloaded, total):
            if total > 0:
                p = int(downloaded / total * 100)
                self.root.after(0, lambda: self.status_var.set(f"下载中 {p}%"))

        success, filepath = self.downloader.download_mp3(
            title, artist, audio_url, quality,
            download_dir=self.download_dir,
            progress_callback=progress_cb,
            log_callback=self._log
        )
        if success:
            self._log(f"保存到: {filepath}")
        return success


def main():
    root = tk.Tk()
    app = MusicDownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
