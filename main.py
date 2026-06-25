import os
import sys
import re
import json
from collections import deque
from datetime import datetime
import urllib.request
import yt_dlp
import imageio_ffmpeg

from PySide6.QtCore import (
    Qt,
    QThread,
    Signal,
    Slot,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    QSize,
)
from PySide6.QtGui import (
    QIcon,
    QPixmap,
    QAction,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QProgressBar,
    QTextEdit,
    QFrame,
    QMessageBox,
    QFileDialog,
    QGraphicsOpacityEffect,
    QGraphicsBlurEffect,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QCheckBox,
    QPlainTextEdit,
    QSystemTrayIcon,
    QMenu,
)


# ============================================================
#  PATHS / CONSTANTS
# ============================================================  

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR_DEFAULT = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR_DEFAULT, exist_ok=True)
DOWNLOAD_DIR = DOWNLOAD_DIR_DEFAULT

HISTORY_FILE = os.path.join(BASE_DIR, "downloads_history.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "hyde_settings.json")


# ============================================================
#  UTILITIES
# ============================================================

def safe_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[\/\\\?\%\*\:\|\\"<>\.]', "_", name)
    if not name:
        name = "hyde_download"
    return name


def get_website_name(url: str) -> str:
    u = url.lower()
    if "youtu" in u:
        return "YouTube"
    if "tiktok" in u:
        return "TikTok"
    if "instagram" in u:
        return "Instagram"
    if "facebook" in u:
        return "Facebook"
    if "twitter" in u or "x.com" in u:
        return "Twitter / X"
    return "Unknown"


def get_media_info(url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "dump_single_json": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.youtube.com/",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = []
    for f in info.get("formats", []):
        fm = {
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution")
                        or (f"{f.get('width')}x{f.get('height')}"
                            if f.get("width") and f.get("height") else None),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "fps": f.get("fps"),
            "tbr": f.get("tbr"),
            "abr": f.get("abr"),
        }
        formats.append(fm)

    return {
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "formats": formats,
        "website": get_website_name(url),
        "source_url": url,
    }


def load_json_file(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def format_speed(speed: float | None) -> str:
    if not speed:
        return ""
    # speed is bytes/s
    if speed < 1024:
        return f"{int(speed)} B/s"
    kb = speed / 1024
    if kb < 1024:
        return f"{kb:.1f} KB/s"
    mb = kb / 1024
    return f"{mb:.2f} MB/s"


def format_eta(eta: int | None) -> str:
    if not eta or eta <= 0:
        return ""
    m, s = divmod(int(eta), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


# ============================================================
#  SETTINGS HANDLER
# ============================================================

DEFAULT_SETTINGS = {
    "download_dir": DOWNLOAD_DIR_DEFAULT,
    "auto_paste_url": False,
    "default_media_type": "audio",   # "audio" or "video"
    "default_format_audio": "mp3",
    "default_format_video": "mp4",
    "auto_open_folder_after_download": True,
    "theme": "dark",
    "animations_enabled": True,
    "show_advanced_formats": True,
    "custom_ffmpeg_path": "",
    "download_thumbnail": False,
}


def load_settings():
    s = load_json_file(SETTINGS_FILE, DEFAULT_SETTINGS)
    # Ensure defaults for missing keys
    for k, v in DEFAULT_SETTINGS.items():
        if k not in s:
            s[k] = v
    return s


SETTINGS = load_settings()
DOWNLOAD_DIR = SETTINGS.get("download_dir", DOWNLOAD_DIR_DEFAULT)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ============================================================
#  FETCH INFO WORKER
# ============================================================

class FetchInfoWorker(QThread):
    finished_success = Signal(dict, bytes)
    finished_error = Signal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            info = get_media_info(self.url)
            thumb_data = b""
            thumb_url = info.get("thumbnail")
            if thumb_url:
                try:
                    thumb_data = urllib.request.urlopen(thumb_url, timeout=5).read()
                except Exception:
                    pass
            self.finished_success.emit(info, thumb_data)
        except Exception as e:
            self.finished_error.emit(str(e))


# ============================================================
#  DOWNLOAD WORKER
# ============================================================

class DownloadWorker(QThread):
    progress_changed = Signal(int)
    status_changed = Signal(str)
    finished_success = Signal(str, dict)  # path, info dict for history + thumb
    finished_error = Signal(str)

    def __init__(
        self,
        url: str,
        media_type: str,
        fmt: str,
        quality: int | None,  # now represents target height (video) or kbps (audio)
        filename: str,
        format_selector_override: str | None = None,
        download_thumbnail: bool = False,
        custom_ffmpeg_path: str = "",
    ):
        super().__init__()
        self.url = url
        self.media_type = media_type
        self.fmt = fmt
        self.quality = quality
        self.filename = filename
        self.format_selector_override = format_selector_override
        self.download_thumbnail = download_thumbnail
        self.custom_ffmpeg_path = custom_ffmpeg_path

    def run(self):
        try:
            if not self.filename or self.filename.strip() == "":
                try:
                    info_meta = get_media_info(self.url)
                    self.filename = info_meta.get("title", "hyde_download")
                except Exception:
                    self.filename = "hyde_download"

            base_name = safe_filename(self.filename)

            # --- Format selection (hybrid: presets + advanced formats) ---
            if self.format_selector_override:
                # user picked a specific format_id / selector from advanced list
                format_selector = self.format_selector_override
            else:
                # preset-based selection using quality
                if self.media_type == "audio":
                    if isinstance(self.quality, int):
                        # limit by bitrate
                        format_selector = f"bestaudio[abr<={self.quality}]/bestaudio/best"
                    else:
                        format_selector = "bestaudio/best"
                else:
                    # video with optional height limit
                    if isinstance(self.quality, int):
                        # graceful fallback with <= height
                        format_selector = (
                            f"bestvideo[height<={self.quality}]+bestaudio/best/"
                            f"best[height<={self.quality}]/best"
                        )
                    else:
                        format_selector = "bestvideo*+bestaudio/best"

            if self.media_type == "audio":
                postprocessors = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.fmt,
                    "preferredquality": "192",
                }]
            else:
                # NOTE: youtube-dl/yt-dlp uses 'preferedformat' spelling internally
                postprocessors = [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": self.fmt,
                }]

            outtmpl = os.path.join(DOWNLOAD_DIR, base_name + ".%(ext)s")

            def progress_hook(d):
                if d["status"] == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    downloaded = d.get("downloaded_bytes", 0)
                    if total:
                        pct = int(downloaded * 100 / total)
                    else:
                        pct_str = d.get("_percent_str", "0%").strip().replace("%", "")
                        try:
                            pct = int(float(pct_str))
                        except Exception:
                            pct = 0

                    spd = format_speed(d.get("speed"))
                    eta_str = format_eta(d.get("eta"))

                    status = f"Downloading... {pct}%"
                    if spd:
                        status += f" • {spd}"
                    if eta_str:
                        status += f" • ETA {eta_str}"

                    self.progress_changed.emit(pct)
                    self.status_changed.emit(status)

                elif d["status"] == "finished":
                    self.progress_changed.emit(100)
                    self.status_changed.emit("Processing...")

            ydl_opts = {
                "format": format_selector,
                "outtmpl": outtmpl,
                "postprocessors": postprocessors,
                "progress_hooks": [progress_hook],
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Referer": "https://www.youtube.com/",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            }

            if self.custom_ffmpeg_path:
                ydl_opts["ffmpeg_location"] = self.custom_ffmpeg_path
            else:
                try:
                    ydl_opts["ffmpeg_location"] = imageio_ffmpeg.get_ffmpeg_exe()
                except Exception:
                    pass

            self.status_changed.emit("Starting download...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)

            candidates = []
            for d in info.get("requested_downloads", []):
                fp = d.get("filepath")
                if fp:
                    candidates.append(fp)
            if info.get("_filename"):
                candidates.append(info["_filename"])

            expected = os.path.join(DOWNLOAD_DIR, base_name + f".{self.fmt}")
            candidates.insert(0, expected)

            final_path = None
            for path in candidates:
                if path and os.path.exists(path):
                    final_path = os.path.abspath(path)
                    break

            if not final_path:
                raise FileNotFoundError("Could not determine downloaded file path.")

            thumb_path = None
            if self.download_thumbnail:
                thumb_url = info.get("thumbnail")
                if thumb_url:
                    try:
                        data = urllib.request.urlopen(thumb_url).read()
                        thumb_path = os.path.join(DOWNLOAD_DIR, base_name + ".jpg")
                        with open(thumb_path, "wb") as f:
                            f.write(data)
                    except Exception:
                        thumb_path = None

            self.progress_changed.emit(100)
            self.status_changed.emit("Done")

            history_entry = {
                "title": info.get("title"),
                "url": self.url,
                "media_type": self.media_type,
                "format": self.fmt,
                "filepath": final_path,
                "thumbnail_path": thumb_path,
                "date": datetime.now().isoformat(timespec="seconds"),
            }

            self.finished_success.emit(final_path, history_entry)

        except Exception as e:
            self.finished_error.emit(str(e))


# ============================================================
#  MINI-MODE WINDOW
# ============================================================

class MiniModeWindow(QWidget):
    start_download_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Hyde Mini")
        self.setFixedSize(320, 100)

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Paste URL...")
        self.btn = QPushButton("Download")
        self.btn.clicked.connect(self.on_download_clicked)
        row.addWidget(self.url_edit)
        row.addWidget(self.btn)

        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        self.progress.setFormat("Idle")

        layout.addLayout(row)
        layout.addWidget(self.progress)

    def on_download_clicked(self):
        url = self.url_edit.text().strip()
        if url:
            self.start_download_requested.emit(url)

    def update_progress(self, value: int, text: str | None = None):
        self.progress.setValue(value)
        if text:
            self.progress.setFormat(text)


# ============================================================
#  MAIN WINDOW
# ============================================================

class HydeDownloaderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hyde Downloader (v 1.0)")
        self.setMinimumSize(1000, 650)
        self.setWindowIcon(QIcon())

        self.worker: DownloadWorker | None = None
        self.formats: list[dict] = []
        self.queue: deque[dict] = deque()
        self.history: list[dict] = load_json_file(HISTORY_FILE, [])
        self.history_filter: str = ""

        self.header_full_text = "Hyde Downloader"
        self.header_index = 0
        self.type_timer: QTimer | None = None

        self._tab_animations: list[QPropertyAnimation] = []

        self.mini_mode_window = MiniModeWindow()
        self.mini_mode_window.start_download_requested.connect(
            self.start_download_from_mini
        )

        self.tray_icon = None
        self.create_tray_icon()

        self._init_ui()
        self._apply_styles()

        self.tabs.currentChanged.connect(self.on_tab_changed)

        if SETTINGS.get("animations_enabled", True):
            self.start_intro_animation()
        else:
            self.header_label.setText(self.header_full_text)
            self.subtitle_label.setVisible(True)

        self.refresh_history_list()

        if SETTINGS.get("auto_paste_url", False):
            clipboard = QApplication.clipboard()
            text = clipboard.text().strip()
            if text.startswith("http"):
                self.url_edit.setText(text)

    # ---------------------- UI BUILD ---------------------- #

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        self.header_label = QLabel("")
        self.header_label.setObjectName("HeaderLabel")
        self.header_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.subtitle_label = QLabel("By Tirth (v 1.0)")
        self.subtitle_label.setObjectName("SubtitleLabel")
        self.subtitle_label.setVisible(False)

        main_layout.addWidget(self.header_label)
        main_layout.addWidget(self.subtitle_label)

        # Card with blur effect (glassmorphism)
        card = QFrame()
        card.setObjectName("Card")
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(10)
        card.setGraphicsEffect(blur)

        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(15)
        card_layout.setContentsMargins(18, 18, 18, 18)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")

        # Main Downloader tab
        main_tab = QWidget()
        main_tab_layout = QVBoxLayout(main_tab)
        main_tab_layout.setSpacing(12)

        # URL row + mini queue / batch
        url_row = QHBoxLayout()
        url_label = QLabel("Media URL")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "Paste YouTube, TikTok, Instagram, Twitter/X, etc..."
        )

        self.fetch_info_btn = QPushButton("Fetch Info")
        self.fetch_info_btn.clicked.connect(self.on_fetch_info)

        url_row.addWidget(url_label)
        url_row.addWidget(self.url_edit)
        url_row.addWidget(self.fetch_info_btn)

        main_tab_layout.addLayout(url_row)

        # Batch input row
        batch_layout = QHBoxLayout()
        batch_label = QLabel("Batch URLs")
        self.batch_text = QPlainTextEdit()
        self.batch_text.setPlaceholderText("One URL per line...")
        self.batch_text.setFixedHeight(70)
        self.batch_add_btn = QPushButton("Add All to Queue")
        self.batch_add_btn.clicked.connect(self.on_add_batch_to_queue)
        self.batch_load_btn = QPushButton("Load .txt")
        self.batch_load_btn.clicked.connect(self.on_load_batch_file)

        batch_layout.addWidget(batch_label)
        batch_layout.addWidget(self.batch_text)
        batch_btn_col = QVBoxLayout()
        batch_btn_col.addWidget(self.batch_add_btn)
        batch_btn_col.addWidget(self.batch_load_btn)
        batch_btn_col.addStretch()
        batch_layout.addLayout(batch_btn_col)

        main_tab_layout.addLayout(batch_layout)

        # Website + filename row
        meta_row = QHBoxLayout()
        self.website_label = QLabel("Website: —")
        self.website_label.setObjectName("MetaLabel")

        filename_label = QLabel("Filename (optional)")
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("Leave empty to use video title")

        meta_row.addWidget(self.website_label, stretch=1)
        meta_row.addSpacing(20)
        meta_row.addWidget(filename_label)
        meta_row.addWidget(self.filename_edit, stretch=2)

        main_tab_layout.addLayout(meta_row)

        # Options row
        options_row = QHBoxLayout()

        type_label = QLabel("Media Type")
        self.media_type_combo = QComboBox()
        self.media_type_combo.addItem("Audio (MP3)", userData=("audio", "mp3"))
        self.media_type_combo.addItem("Video (MP4)", userData=("video", "mp4"))
        self.media_type_combo.currentIndexChanged.connect(self.on_media_type_changed)

        # defaults from settings
        if SETTINGS.get("default_media_type") == "video":
            self.media_type_combo.setCurrentIndex(1)
        else:
            self.media_type_combo.setCurrentIndex(0)

        quality_label = QLabel("Quality / Resolution")
        self.quality_combo = QComboBox()

        format_label = QLabel("Format (yt-dlp advanced)")
        self.format_combo = QComboBox()
        self.format_combo.addItem("Auto (Recommended)", userData=None)
        self.format_combo.setEnabled(False)

        self.thumb_checkbox = QCheckBox("Download Thumbnail (jpg)")
        self.thumb_checkbox.setChecked(SETTINGS.get("download_thumbnail", False))

        options_row.addWidget(type_label)
        options_row.addWidget(self.media_type_combo)
        options_row.addSpacing(20)
        options_row.addWidget(quality_label)
        options_row.addWidget(self.quality_combo)
        options_row.addSpacing(20)
        options_row.addWidget(format_label)
        options_row.addWidget(self.format_combo)
        options_row.addSpacing(20)
        options_row.addWidget(self.thumb_checkbox)
        options_row.addStretch()

        main_tab_layout.addLayout(options_row)

        # Thumbnail + Info
        info_row = QHBoxLayout()

        self.thumb_label = QLabel()
        self.thumb_label.setObjectName("ThumbLabel")
        self.thumb_label.setFixedSize(180, 100)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setText("No Preview")

        info_col = QVBoxLayout()
        self.title_label = QLabel("Title: —")
        self.uploader_label = QLabel("Uploader: —")
        self.duration_label = QLabel("Duration: —")
        for lbl in (self.title_label, self.uploader_label, self.duration_label):
            lbl.setObjectName("InfoLabel")

        info_col.addWidget(self.title_label)
        info_col.addWidget(self.uploader_label)
        info_col.addWidget(self.duration_label)
        info_col.addStretch()

        info_row.addWidget(self.thumb_label)
        info_row.addLayout(info_col)

        # Mini queue list
        queue_col = QVBoxLayout()
        queue_label = QLabel("Queue List")
        queue_label.setObjectName("MetaLabel")
        self.queue_list = QListWidget()
        self.queue_label = QLabel("Queue: 0")
        self.queue_label.setObjectName("MetaLabel")
        queue_col.addWidget(queue_label)
        queue_col.addWidget(self.queue_list)
        queue_col.addWidget(self.queue_label)

        info_row.addLayout(queue_col)

        main_tab_layout.addLayout(info_row)

        # Progress + Buttons
        bottom_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready")

        self.choose_dir_btn = QPushButton("Change Download Folder")
        self.choose_dir_btn.clicked.connect(self.on_change_download_folder)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self.on_open_folder_clicked)

        self.download_btn = QPushButton("Download")
        self.download_btn.setObjectName("PrimaryButton")
        self.download_btn.clicked.connect(self.on_download_clicked)

        bottom_row.addWidget(self.progress_bar, stretch=2)
        bottom_row.addWidget(self.choose_dir_btn)
        bottom_row.addWidget(self.open_folder_btn)
        bottom_row.addWidget(self.download_btn)

        main_tab_layout.addLayout(bottom_row)

        # Log
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("Status log will appear here...")

        main_tab_layout.addWidget(self.log_edit)

        self.tabs.addTab(main_tab, "Downloader")

        # History tab
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)

        self.history_search_edit = QLineEdit()
        self.history_search_edit.setPlaceholderText("Search history...")
        self.history_search_edit.textChanged.connect(self.on_history_search_changed)

        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self.on_history_item_open)

        history_layout.addWidget(self.history_search_edit)
        history_layout.addWidget(self.history_list)
        self.tabs.addTab(history_tab, "History")

        # Settings tab
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)

        self.chk_auto_paste = QCheckBox("Auto paste URLs from clipboard")
        self.chk_auto_paste.setChecked(SETTINGS.get("auto_paste_url", False))

        self.chk_auto_open_folder = QCheckBox("Auto-open folder after download")
        self.chk_auto_open_folder.setChecked(
            SETTINGS.get("auto_open_folder_after_download", True)
        )

        self.chk_animations = QCheckBox("Enable animations")
        self.chk_animations.setChecked(SETTINGS.get("animations_enabled", True))

        self.chk_show_formats = QCheckBox("Show advanced format selector")
        self.chk_show_formats.setChecked(SETTINGS.get("show_advanced_formats", True))

        self.chk_dark_theme = QCheckBox("Dark theme (requires restart)")
        self.chk_dark_theme.setChecked(SETTINGS.get("theme", "dark") == "dark")

        self.chk_download_thumb_settings = QCheckBox("Download thumbnail by default")
        self.chk_download_thumb_settings.setChecked(
            SETTINGS.get("download_thumbnail", False)
        )

        ffmpeg_row = QHBoxLayout()
        ffmpeg_label = QLabel("Custom FFmpeg path")
        self.ffmpeg_edit = QLineEdit()
        self.ffmpeg_edit.setText(SETTINGS.get("custom_ffmpeg_path", ""))
        ffmpeg_btn = QPushButton("Browse")
        ffmpeg_btn.clicked.connect(self.on_browse_ffmpeg)
        ffmpeg_row.addWidget(ffmpeg_label)
        ffmpeg_row.addWidget(self.ffmpeg_edit)
        ffmpeg_row.addWidget(ffmpeg_btn)

        default_folder_row = QHBoxLayout()
        default_folder_label = QLabel("Default download folder")
        self.default_folder_edit = QLineEdit()
        self.default_folder_edit.setText(SETTINGS.get("download_dir", DOWNLOAD_DIR))
        default_folder_btn = QPushButton("Browse")
        default_folder_btn.clicked.connect(self.on_browse_default_folder)
        default_folder_row.addWidget(default_folder_label)
        default_folder_row.addWidget(self.default_folder_edit)
        default_folder_row.addWidget(default_folder_btn)

        settings_layout.addWidget(self.chk_auto_paste)
        settings_layout.addWidget(self.chk_auto_open_folder)
        settings_layout.addWidget(self.chk_animations)
        settings_layout.addWidget(self.chk_show_formats)
        settings_layout.addWidget(self.chk_dark_theme)
        settings_layout.addWidget(self.chk_download_thumb_settings)
        settings_layout.addLayout(ffmpeg_row)
        settings_layout.addLayout(default_folder_row)

        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.clicked.connect(self.on_save_settings)
        settings_layout.addWidget(self.save_settings_btn)
        settings_layout.addStretch()

        self.tabs.addTab(settings_tab, "Settings")

        card_layout.addWidget(self.tabs)
        main_layout.addWidget(card)

        self.footer_label = QLabel("Downloads folder: " + DOWNLOAD_DIR)
        self.footer_label.setObjectName("FooterLabel")
        main_layout.addWidget(self.footer_label)

        # Mini-mode toggle action in menu
        mini_action = QAction("Toggle Mini Mode", self)
        mini_action.triggered.connect(self.toggle_mini_mode)
        self.menuBar().addAction(mini_action)

        # populate quality presets after combos exist
        self.populate_quality_combo()

    def _apply_styles(self):
        # Glassmorphism + modern dark theme
        self.setStyleSheet("""
        QMainWindow {
            background-color: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 #020617,
                stop:1 #020617
            );
        }
        #HeaderLabel {
            color: #e5e7eb;
            font-size: 28px;
            font-weight: 700;
        }
        #SubtitleLabel {
            color: #9ca3af;
            font-size: 13px;
        }
        #Card {
            background-color: rgba(15, 23, 42, 200);
            border-radius: 18px;
            border: 1px solid rgba(148, 163, 184, 80);
        }
        QLabel {
            color: #e5e7eb;
            font-size: 12px;
        }
        #MetaLabel {
            color: #9ca3af;
            font-size: 12px;
        }
        #InfoLabel {
            color: #d1d5db;
            font-size: 12px;
        }
        #FooterLabel {
            color: #6b7280;
            font-size: 11px;
        }
        QLineEdit, QPlainTextEdit {
            background-color: rgba(15, 23, 42, 210);
            border: 1px solid #374151;
            border-radius: 10px;
            padding: 6px 8px;
            color: #e5e7eb;
            selection-background-color: #1d4ed8;
        }
        QLineEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #3b82f6;
        }
        QComboBox {
            background-color: rgba(15, 23, 42, 210);
            border: 1px solid #374151;
            border-radius: 10px;
            padding: 4px 8px;
            color: #e5e7eb;
        }
        QComboBox::drop-down {
            border: none;
        }
        QComboBox QAbstractItemView {
            background-color: #020617;
            border-radius: 8px;
            border: 1px solid #374151;
            selection-background-color: #1d4ed8;
            color: #e5e7eb;
        }
        QPushButton {
            background-color: rgba(15, 23, 42, 220);
            border-radius: 12px;
            border: 1px solid #374151;
            padding: 6px 14px;
            color: #e5e7eb;
            font-size: 12px;
        }
        QPushButton:hover {
            background-color: #1f2937;
        }
        QPushButton#PrimaryButton {
            background-color: #2563eb;
            border: none;
            font-weight: 600;
        }
        QPushButton#PrimaryButton:hover {
            background-color: #1d4ed8;
        }
        QProgressBar {
            border: 1px solid #374151;
            border-radius: 10px;
            text-align: center;
            background-color: rgba(2, 6, 23, 220);
            color: #e5e7eb;
            font-size: 11px;
        }
        QProgressBar::chunk {
            border-radius: 10px;
            background-color: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #22c55e,
                stop:1 #4ade80
            );
        }
        QTextEdit {
            background-color: rgba(2, 6, 23, 220);
            border: 1px solid #374151;
            border-radius: 12px;
            color: #e5e7eb;
            font-size: 11px;
        }
        #ThumbLabel {
            background-color: rgba(2, 6, 23, 200);
            border-radius: 14px;
            border: 1px dashed #374151;
            color: #4b5563;
            font-size: 11px;
        }
        QTabWidget::pane {
            border: 0px;
        }
        QTabBar::tab {
            background: transparent;
            color: #9ca3af;
            padding: 6px 12px;
            margin-right: 6px;
            border-radius: 10px;
        }
        QTabBar::tab:selected {
            background-color: rgba(37, 99, 235, 160);
            color: #e5e7eb;
        }
        QListWidget {
            background-color: rgba(2, 6, 23, 220);
            border: 1px solid #374151;
            border-radius: 10px;
            color: #e5e7eb;
            font-size: 11px;
        }
        QCheckBox {
            color: #e5e7eb;
        }
        """)

    # ============================================================
    #  INTRO & OTHER ANIMATIONS
    # ============================================================

    def start_intro_animation(self):
        self.header_label.setText("")
        self.header_index = 0
        self.type_timer = QTimer(self)
        self.type_timer.timeout.connect(self.update_header_typing)
        self.type_timer.start(120)

    def update_header_typing(self):
        if self.header_index < len(self.header_full_text):
            current = self.header_label.text()
            self.header_label.setText(current + self.header_full_text[self.header_index])
            self.header_index += 1
        else:
            self.type_timer.stop()
            self.start_byline_fade_in()

    def start_byline_fade_in(self):
        effect = QGraphicsOpacityEffect(self.subtitle_label)
        self.subtitle_label.setGraphicsEffect(effect)
        self.subtitle_label.setVisible(True)
        self.subtitle_anim = QPropertyAnimation(effect, b"opacity", self)
        self.subtitle_anim.setDuration(600)
        self.subtitle_anim.setStartValue(0.0)
        self.subtitle_anim.setEndValue(1.0)
        self.subtitle_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.subtitle_anim.start()

    def on_tab_changed(self, index: int):
        if not SETTINGS.get("animations_enabled", True):
            return
        w = self.tabs.currentWidget()
        if not w:
            return
        effect = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(250)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.start()
        self._tab_animations.append(anim)

        def cleanup():
            try:
                self._tab_animations.remove(anim)
            except ValueError:
                pass

        anim.finished.connect(cleanup)

    def animate_button_pulse(self, btn: QPushButton):
        if not SETTINGS.get("animations_enabled", True):
            return
        anim = QPropertyAnimation(btn, b"minimumWidth", self)
        w = btn.width()
        anim.setDuration(180)
        anim.setStartValue(w)
        anim.setKeyValueAt(0.5, w + 12)
        anim.setEndValue(w)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    # ============================================================
    #  HELPERS
    # ============================================================

    def log(self, text: str):
        self.log_edit.append(text)

    def update_queue_label(self):
        self.queue_label.setText(f"Queue: {len(self.queue)}")

        self.queue_list.clear
        self.queue_list.clear()
        for job in self.queue:
            title = job.get("filename") or job.get("url")
            item = QListWidgetItem(title)
            self.queue_list.addItem(item)

    def populate_format_combo(self):
        self.format_combo.clear()
        self.format_combo.addItem("Auto (Recommended)", userData=None)

        if not self.formats or not SETTINGS.get("show_advanced_formats", True):
            self.format_combo.setEnabled(False)
            return

        media_type, _ = self.media_type_combo.currentData()
        count = 0

        for f in self.formats:
            fmt_id = f.get("format_id")
            if not fmt_id:
                continue
            ext = f.get("ext")
            res = f.get("resolution")
            vcodec = f.get("vcodec")
            acodec = f.get("acodec")
            abr = f.get("abr")
            tbr = f.get("tbr")

            if media_type == "audio":
                if vcodec not in (None, "none"):
                    continue
                info_parts = []
                if ext:
                    info_parts.append(ext)
                info_parts.append("audio")
                br = abr or tbr
                if br:
                    if isinstance(br, (int, float)):
                        info_parts.append(f"{int(br)} kbps")
                    else:
                        info_parts.append(f"{br} kbps")
                label = f"{fmt_id} | " + " • ".join(info_parts)
            else:
                if vcodec in (None, "none"):
                    continue
                info_parts = []
                if ext:
                    info_parts.append(ext)
                if res:
                    info_parts.append(res)
                if acodec in (None, "none"):
                    info_parts.append("video-only")
                else:
                    info_parts.append("video+audio")
                if tbr:
                    if isinstance(tbr, (int, float)):
                        info_parts.append(f"{int(tbr)} kbps")
                    else:
                        info_parts.append(f"{tbr} kbps")
                label = f"{fmt_id} | " + " • ".join(info_parts)

            self.format_combo.addItem(label, userData=str(fmt_id))
            count += 1

        self.format_combo.setEnabled(count > 0)

    def build_format_selector_override(self, selected_format_id: str | None, media_type: str) -> str | None:
        if not selected_format_id:
            return None

        fmt_info = next(
            (f for f in self.formats if str(f.get("format_id")) == str(selected_format_id)),
            None,
        )
        if not fmt_info:
            return selected_format_id

        vcodec = fmt_info.get("vcodec")
        acodec = fmt_info.get("acodec")

        if media_type == "audio":
            return selected_format_id

        if vcodec not in (None, "none") and acodec in (None, "none"):
            return f"{selected_format_id}+bestaudio/best"

        return selected_format_id

    def populate_quality_combo(self):
        """Preset-based quality selection for video & audio."""
        self.quality_combo.clear()
        media_type, _ = self.media_type_combo.currentData()

        if media_type == "audio":
            self.quality_combo.addItem("Auto (Best)", userData=None)
            self.quality_combo.addItem("64 kbps", userData=64)
            self.quality_combo.addItem("128 kbps", userData=128)
            self.quality_combo.addItem("192 kbps", userData=192)
            self.quality_combo.addItem("256 kbps", userData=256)
            self.quality_combo.addItem("320 kbps", userData=320)
        else:
            self.quality_combo.addItem("Auto (Best)", userData=None)
            self.quality_combo.addItem("144p", userData=144)
            self.quality_combo.addItem("240p", userData=240)
            self.quality_combo.addItem("360p", userData=360)
            self.quality_combo.addItem("480p", userData=480)
            self.quality_combo.addItem("720p (HD)", userData=720)
            self.quality_combo.addItem("1080p (Full HD)", userData=1080)
            self.quality_combo.addItem("1440p (2K)", userData=1440)
            self.quality_combo.addItem("2160p (4K)", userData=2160)

    def start_download_job(self, job: dict):
        url = job["url"]
        media_type = job["media_type"]
        fmt = job["fmt"]
        quality = job["quality"]
        filename = job["filename"]
        format_selector_override = job.get("format_selector_override")
        download_thumbnail = job.get("download_thumbnail", False)
        custom_ffmpeg_path = SETTINGS.get("custom_ffmpeg_path", "")

        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting...")
        self.mini_mode_window.update_progress(0, "Starting...")

        self.log(
            f"Starting download:\n"
            f"  URL: {url}\n"
            f"  Type: {media_type}\n"
            f"  Format: {fmt}\n"
            f"  Quality preset: {quality or 'auto'}\n"
            f"  Selector: {format_selector_override or 'auto'}\n"
        )

        self.worker = DownloadWorker(
            url,
            media_type,
            fmt,
            quality,
            filename,
            format_selector_override,
            download_thumbnail=download_thumbnail,
            custom_ffmpeg_path=custom_ffmpeg_path,
        )
        self.worker.progress_changed.connect(self.on_progress_changed)
        self.worker.status_changed.connect(self.on_status_changed)
        self.worker.finished_success.connect(self.on_download_success)
        self.worker.finished_error.connect(self.on_download_error)
        self.worker.finished.connect(self.on_download_finished)
        self.worker.start()

        self.show_tray_message("Download started", filename or url)

    # ============================================================
    #  UI Handlers
    # ============================================================

    @Slot()
    def on_fetch_info(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Please paste a URL first.")
            return

        self.log(f"Fetching info for: {url}")
        self.fetch_info_btn.setEnabled(False)
        self.fetch_info_btn.setText("Fetching...")
        QApplication.setOverrideCursor(Qt.BusyCursor)

        self.info_worker = FetchInfoWorker(url)
        self.info_worker.finished_success.connect(self.on_fetch_success)
        self.info_worker.finished_error.connect(self.on_fetch_error)
        self.info_worker.start()

    @Slot(dict, bytes)
    def on_fetch_success(self, info: dict, thumb_data: bytes):
        self.fetch_info_btn.setEnabled(True)
        self.fetch_info_btn.setText("Fetch Info")
        QApplication.restoreOverrideCursor()

        self.website_label.setText(f"Website: {info.get('website', 'Unknown')}")
        self.title_label.setText(f"Title: {info.get('title', '—')}")
        self.uploader_label.setText(f"Uploader: {info.get('uploader', '—')}")
        dur = info.get("duration")
        if dur:
            mins = dur // 60
            secs = dur % 60
            dur_str = f"{mins}m {secs}s"
        else:
            dur_str = "—"
        self.duration_label.setText(f"Duration: {dur_str}")

        if not self.filename_edit.text().strip() and info.get("title"):
            self.filename_edit.setText(info["title"])

        self.formats = info.get("formats", [])
        self.populate_format_combo()
        self.populate_quality_combo()  # ensure quality presets after info

        if thumb_data:
            try:
                pix = QPixmap()
                pix.loadFromData(thumb_data)
                scaled = pix.scaled(
                    self.thumb_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.thumb_label.setPixmap(scaled)
                self.thumb_label.setText("")
            except Exception as e:
                self.log(f"Failed to load thumbnail data: {e}")
                self.thumb_label.setPixmap(QPixmap())
                self.thumb_label.setText("No Preview")
        else:
            self.thumb_label.setPixmap(QPixmap())
            self.thumb_label.setText("No Preview")

        self.log("Info loaded.")
        self.info_worker = None

    @Slot(str)
    def on_fetch_error(self, error: str):
        self.fetch_info_btn.setEnabled(True)
        self.fetch_info_btn.setText("Fetch Info")
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(self, "Error", f"Failed to fetch info:\n{error}")
        self.log(f"Error fetching info: {error}")
        self.info_worker = None

    @Slot()
    def on_media_type_changed(self):
        # refresh both quality presets & advanced format list
        self.populate_quality_combo()
        if self.formats:
            self.populate_format_combo()

    @Slot()
    def on_change_download_folder(self):
        global DOWNLOAD_DIR
        new_dir = QFileDialog.getExistingDirectory(
            self, "Select Download Folder", DOWNLOAD_DIR
        )
        if new_dir:
            DOWNLOAD_DIR = new_dir
            SETTINGS["download_dir"] = new_dir
            save_json_file(SETTINGS_FILE, SETTINGS)
            self.footer_label.setText("Downloads folder: " + DOWNLOAD_DIR)
            self.log(f"Download folder changed to: {DOWNLOAD_DIR}")

    @Slot()
    def on_open_folder_clicked(self):
        path = DOWNLOAD_DIR
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')

    @Slot()
    def on_download_clicked(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Please paste a URL first.")
            return

        self.animate_button_pulse(self.download_btn)

        media_type, default_fmt = self.media_type_combo.currentData()
        fmt = "mp3" if media_type == "audio" else "mp4"
        quality = self.quality_combo.currentData()
        filename = self.filename_edit.text().strip()

        selected_format_id = self.format_combo.currentData()
        format_selector_override = self.build_format_selector_override(
            selected_format_id, media_type
        )

        job = {
            "url": url,
            "media_type": media_type,
            "fmt": fmt,
            "quality": quality,
            "filename": filename,
            "format_selector_override": format_selector_override,
            "download_thumbnail": self.thumb_checkbox.isChecked(),
        }

        if self.worker is not None and self.worker.isRunning():
            self.queue.append(job)
            self.update_queue_label()
            self.log(f"Added to queue at position {len(self.queue)}")
            QMessageBox.information(
                self,
                "Queued",
                f"Download added to queue at position {len(self.queue)}.",
            )
        else:
            self.start_download_job(job)

        self.filename_edit.clear()

    @Slot(int)
    def on_progress_changed(self, value: int):
        self.progress_bar.setValue(value)
        self.mini_mode_window.update_progress(value, None)

    @Slot(str)
    def on_status_changed(self, text: str):
        if text:
            self.progress_bar.setFormat(text)
            self.mini_mode_window.update_progress(self.progress_bar.value(), text)
            self.log(text)

    @Slot(str, dict)
    def on_download_success(self, file_path: str, history_entry: dict):
        self.log(f"Download finished: {file_path}")
        self.progress_bar.setFormat("Download complete")
        self.open_folder_btn.setEnabled(True)

        self.history.append(history_entry)
        save_json_file(HISTORY_FILE, self.history)
        self.refresh_history_list()

        if SETTINGS.get("auto_open_folder_after_download", True):
            self.on_open_folder_clicked()

        QMessageBox.information(self, "Success", f"File downloaded:\n{file_path}")
        self.show_tray_message("Download complete", history_entry.get("title") or file_path)

    @Slot(str)
    def on_download_error(self, error: str):
        self.log(f"Error: {error}")
        self.progress_bar.setFormat("Error")
        QMessageBox.critical(self, "Download Error", error)
        self.show_tray_message("Download error", error)

    @Slot()
    def on_download_finished(self):
        self.worker = None
        if self.queue:
            next_job = self.queue.popleft()
            self.update_queue_label()
            self.log("Starting next download from queue...")
            self.start_download_job(next_job)
        else:
            self.update_queue_label()
            self.show_tray_message("Queue finished", "All downloads completed.")

    # ============================================================
    #  HISTORY
    # ============================================================

    def refresh_history_list(self):
        self.history_list.clear()
        filter_text = (self.history_filter or "").lower()

        for item in reversed(self.history):
            title = item.get("title") or item.get("filepath")
            date = item.get("date", "")
            url = item.get("url", "")
            if filter_text:
                haystack = " ".join([
                    str(title or "").lower(),
                    str(date).lower(),
                    str(url).lower(),
                ])
                if filter_text not in haystack:
                    continue

            display = f"[{date}] {title}"
            lw_item = QListWidgetItem(display)
            lw_item.setData(Qt.UserRole, item)
            self.history_list.addItem(lw_item)

    @Slot(QListWidgetItem)
    def on_history_item_open(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        path = data.get("filepath")
        if path and os.path.exists(path):
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        else:
            QMessageBox.warning(self, "Missing file", "File not found on disk.")

    @Slot(str)
    def on_history_search_changed(self, text: str):
        self.history_filter = text.strip()
        self.refresh_history_list()

    # ============================================================
    #  BATCH INPUT
    # ============================================================

    @Slot()
    def on_add_batch_to_queue(self):
        lines = [l.strip() for l in self.batch_text.toPlainText().splitlines()]
        urls = [l for l in lines if l.startswith("http")]
        if not urls:
            QMessageBox.information(self, "No URLs", "No valid URLs found.")
            return

        media_type, _ = self.media_type_combo.currentData()
        fmt = "mp3" if media_type == "audio" else "mp4"
        quality = self.quality_combo.currentData()

        for url in urls:
            job = {
                "url": url,
                "media_type": media_type,
                "fmt": fmt,
                "quality": quality,
                "filename": "",
                "format_selector_override": None,
                "download_thumbnail": self.thumb_checkbox.isChecked(),
            }
            if self.worker is not None and self.worker.isRunning():
                self.queue.append(job)
            else:
                if not self.worker:
                    self.start_download_job(job)
                else:
                    self.queue.append(job)

        self.update_queue_label()
        self.log(f"Added {len(urls)} items to queue.")

    @Slot()
    def on_load_batch_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select .txt file with URLs", "", "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            self.batch_text.setPlainText(text)
            self.log(f"Loaded batch URLs from: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read file:\n{e}")

    # ============================================================
    #  SETTINGS
    # ============================================================

    @Slot()
    def on_browse_ffmpeg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select FFmpeg executable", "", "Executables (*)"
        )
        if path:
            self.ffmpeg_edit.setText(path)

    @Slot()
    def on_browse_default_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select default download folder", self.default_folder_edit.text()
        )
        if path:
            self.default_folder_edit.setText(path)

    @Slot()
    def on_save_settings(self):
        SETTINGS["auto_paste_url"] = self.chk_auto_paste.isChecked()
        SETTINGS["auto_open_folder_after_download"] = self.chk_auto_open_folder.isChecked()
        SETTINGS["animations_enabled"] = self.chk_animations.isChecked()
        SETTINGS["show_advanced_formats"] = self.chk_show_formats.isChecked()
        SETTINGS["theme"] = "dark" if self.chk_dark_theme.isChecked() else "light"
        SETTINGS["custom_ffmpeg_path"] = self.ffmpeg_edit.text().strip()
        SETTINGS["download_dir"] = self.default_folder_edit.text().strip() or DOWNLOAD_DIR_DEFAULT
        SETTINGS["download_thumbnail"] = self.chk_download_thumb_settings.isChecked()

        global DOWNLOAD_DIR
        DOWNLOAD_DIR = SETTINGS["download_dir"]
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        self.footer_label.setText("Downloads folder: " + DOWNLOAD_DIR)

        save_json_file(SETTINGS_FILE, SETTINGS)
        QMessageBox.information(self, "Settings", "Settings saved. Some changes may require restart.")

    # ============================================================
    #  MINI MODE / TRAY
    # ============================================================

    def toggle_mini_mode(self):
        if self.mini_mode_window.isVisible():
            self.mini_mode_window.hide()
        else:
            self.mini_mode_window.show()

    def start_download_from_mini(self, url: str):
        self.url_edit.setText(url)
        self.on_download_clicked()

    def create_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.windowIcon())
        menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.showNormal)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(show_action)
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def show_tray_message(self, title: str, message: str):
        if self.tray_icon and self.tray_icon.isVisible():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.Information, 4000)

    def closeEvent(self, event):
        if self.tray_icon:
            self.hide()
            self.show_tray_message("Hyde Downloader", "Still running in system tray.")
            event.ignore()
        else:
            super().closeEvent(event)


# ============================================================
#  ENTRY POINT
# ============================================================

def main():
    app = QApplication(sys.argv)
    window = HydeDownloaderWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
