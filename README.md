# Warning : 
- This repo is not being maintained by me at all. No new version will ever come in this project this project is closed forever from my side. If any developer want to maintain this small project I am happy to share all the resources he needs from my side I will also give him other code that I have saved for this project. I have also made an website for this same project But I dont want to bear the cost of AWS Server for this project so I am not deploying it. If Anyone Want to work in this project you can change anything you want to change in this project feel free to contact me.

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Mail : joshitirth1107@gmail.com
Other Mail : tirthjoshi@thenn.in

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# Hyde Downloader

Hyde Downloader is a versatile and modern desktop application for downloading media from popular platforms like YouTube, TikTok, Instagram, Twitter/X, and more. Built with Python and PySide6, it features a beautiful glassmorphism-inspired UI, smooth animations, and asynchronous background operations to ensure the application stays fast and responsive.

## Features

- **Multi-Platform Support**: Download videos and audio from YouTube, TikTok, Instagram, Twitter/X, Facebook, and hundreds of other websites supported by `yt-dlp`.
- **Modern UI**: A sleek, dark-themed, glassmorphism UI with micro-animations.
- **Asynchronous Operations**: Background processing for fetching video information and downloading prevents the UI from freezing.
- **Format & Quality Selection**: Choose between standard quality presets or use the advanced format selector to pick exactly the resolution, codec, and bitrate you want.
- **Batch Downloading**: Add multiple URLs at once by pasting a list or loading a `.txt` file.
- **Mini-Mode**: A compact, always-on-top window for quickly dropping URLs and monitoring progress.
- **Download Queue**: Queue multiple downloads without interruption.
- **History Tracking**: Built-in history tab with search functionality to find past downloads easily.
- **System Tray Integration**: Can be minimized to the system tray to run quietly in the background.

## Requirements

The application requires Python 3.10+ and the following packages:
- `PySide6`
- `yt-dlp`
- `imageio-ffmpeg`

The `imageio-ffmpeg` package automatically bundles and manages a local `ffmpeg` executable for your system, meaning zero configuration is required for downloading and merging high-quality videos or extracting audio. You can still provide a custom `ffmpeg` path in the Settings tab if you prefer.

## Installation

1. Clone or download this repository.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python main.py
   ```

## Usage

1. Open **Hyde Downloader**.
2. Paste a URL into the **Media URL** field.
3. Click **Fetch Info** to retrieve available formats and metadata.
4. Select your desired **Media Type** (Audio or Video) and **Quality/Resolution**.
5. Optionally provide a custom filename.
6. Click **Download** to start the process or add it to the queue.

You can customize the default download location, theme settings, and other preferences in the **Settings** tab.
#
