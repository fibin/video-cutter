# Video Cutter

A video cutting app that runs on your own computer. Take a file from disk or a YouTube link, set one or more time ranges and get a single video joined from those pieces.

- Two modes: **keep** the chosen pieces and join them in order, or **remove** them and keep the rest.
- Cuts are frame-accurate, not snapped to the nearest keyframe.
- Progress is shown for uploading, downloading from YouTube and cutting, including which piece is being processed.
- Free and fully local: built on Python, [ffmpeg](https://ffmpeg.org/) and [yt-dlp](https://github.com/yt-dlp/yt-dlp). Your videos never leave your machine.

## Download (Windows)

1. Open [Releases](https://github.com/fibin/video-cutter/releases/latest) and download **VideoCutter.exe**.
2. Double-click it. The app opens in its own window; nothing else needs to be installed.

Windows may show "Windows protected your PC" because the exe is not signed. Click **More info → Run anyway**. Starting takes a few seconds while the app unpacks itself.

The window uses Microsoft Edge WebView2, which comes with Windows 10 and 11. If it is missing, the app opens in your browser instead.

## Run from source (Windows, macOS, Linux)

All you need is **Python 3.10 or newer**. ffmpeg and everything else are installed automatically.

1. Install Python if you don't have it: https://www.python.org/downloads/
   On Windows, tick **Add python.exe to PATH** in the installer.
2. Get this repository: green **Code → Download ZIP** button, then unzip it.
   Or with git: `git clone https://github.com/fibin/video-cutter.git`
3. Start the app:
   - **Windows:** double-click `start.bat`.
   - **macOS / Linux:** open a terminal in the project folder and run `./start.sh`.

The first start takes a few minutes while dependencies download. On Windows and macOS the app then opens in its own window; on Linux it opens in your browser at http://127.0.0.1:8765. Add `--browser` to always use the browser. Keep the terminal window open while you use it; press `Ctrl+C` or close the window to stop.

## How to use

1. **Video.** Drop a file into the window or click to choose one. For YouTube, open the "YouTube link" tab, paste the link and press "Download".
2. **Segments.** Set the start and end of each piece. Times can be written as `1:30`, `01:02:03.5` or in seconds (`90`). The ⏱ button inserts the current player position, ▶ plays the piece so you can check it. An empty end means "until the end of the video".
3. **Cut.** Press the button, wait for the progress bar to fill and save the result.

Results and downloaded videos are stored in a `VideoCutter` folder in your home folder (for example `C:\Users\<name>\VideoCutter` on Windows). You can clean it out at any time. Set the `VIDEO_CUTTER_DATA` environment variable to use another folder.

Only download YouTube videos you have the rights or the author's permission to use.

## Troubleshooting

- **"Python not found":** install Python (step 1) and start again.
- **YouTube downloads stopped working:** YouTube changes often. Update yt-dlp with
  `.venv/bin/python -m pip install -U "yt-dlp[default]"` (Windows: `.venv\Scripts\python -m pip install -U "yt-dlp[default]"`).
- **Odd errors after an update:** delete the `.venv` folder in the project and start again; dependencies will be reinstalled.

## For developers

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # tests
.venv/bin/python -m video_cutter       # run (--port, --no-browser)
```

How it works:

- `video_cutter/timecode.py`: parsing times and segment lists, including the "remove" mode.
- `video_cutter/ffmpeg_tools.py`: cutting and joining in a single ffmpeg run. Each piece is a separate input with an accurate `-ss/-t`, pieces are joined with the `concat` filter, and progress is read from `-progress`.
- `video_cutter/youtube.py`: downloading with yt-dlp, with progress.
- `video_cutter/app.py`: local Flask server. Uploads, downloads and cuts run in the background; the UI polls their status.
- `video_cutter/desktop.py`: the native window (pywebview) with a Save dialog and "Show in folder".
- `video_cutter/static/`: plain HTML, CSS and JS UI, no build step.
- `packaging/`: PyInstaller spec for the single-file exe. `pyinstaller packaging/VideoCutter.spec` builds it; `VideoCutter.exe --self-test report.txt` checks a build. CI builds it on every push. A push to `main` publishes a release for the version in `video_cutter/__init__.py` if that version is not released yet, so bump `__version__` to ship a new one.
