# Hyde Downloader

## Overview
Hyde Downloader is a robust, production-ready desktop application built with Python and PySide6. It serves as a visual front-end for `yt-dlp`, allowing users to effortlessly download videos and audio from hundreds of supported platforms (including YouTube, TikTok, Instagram, Twitter/X, and Facebook). 

## Architecture & Under the Hood

### 1. PySide6 & Glassmorphism UI
The user interface is built entirely with PySide6 (Qt for Python). It employs a custom dark theme and glassmorphism techniques (blur effects via `QGraphicsBlurEffect`, semi-transparent widgets) to deliver a premium, modern experience.

### 2. Multi-Threading for Performance
Network requests in Python are inherently blocking. To prevent the UI from freezing:
- **`FetchInfoWorker` (`QThread`)**: Handles the initial metadata request (`yt-dlp`'s `extract_info` with `download=False`) and downloads the video thumbnail. This allows the application to stay responsive and display a loading state.
- **`DownloadWorker` (`QThread`)**: Executes the actual video/audio download. It uses `yt-dlp`'s `progress_hooks` to emit precise progress data (speed, ETA, percentage) back to the main UI thread via Qt Signals.

### 3. Zero-Configuration FFmpeg (Auto-Resolution)
Extracting high-quality MP3 audio or merging high-resolution video streams (like 1080p and 4K) requires the FFmpeg utility. 
To eliminate complex setup steps for end-users, this project utilizes `imageio-ffmpeg`. When installed, it automatically fetches and bundles a lightweight, cross-platform FFmpeg executable. The application dynamically detects this executable and configures `yt-dlp` to use it, providing a true "zero-configuration" out-of-the-box experience.

### 4. Dynamic Pathing (`sys.frozen`)
The application logic includes special handling for frozen PyInstaller bundles. It uses `getattr(sys, 'frozen', False)` to determine whether it is running as an extracted `.exe` or a standard Python script. This ensures that user settings (`hyde_settings.json`), download history (`downloads_history.json`), and the `downloads` folder are saved alongside the `.exe` file rather than disappearing into a temporary PyInstaller extraction folder (`_MEIPASS`).

## Key Features
- **Multi-Platform Supported**: Backed by `yt-dlp`.
- **Media Type & Quality**: Pick between MP3/MP4, auto-resolutions (e.g., 720p, 1080p), or use the advanced format selector to pick specific codecs.
- **Batch Processing**: Load multiple URLs at once.
- **Mini Mode**: A compact, floating overlay window for drag-and-drop workflow.
- **System Tray**: Minimizes to the system tray for unobtrusive background downloading.
- **Persistent History**: Keeps track of previous downloads with a searchable UI.

## Building the Executable
This project can be easily compiled into a standalone Windows `.exe` using PyInstaller.

```bash
pip install -r requirements.txt
pyinstaller --noconsole --windowed --onefile --name "HydeDownloader" main.py
```
*The compiled executable will be located in the `dist` folder.*
