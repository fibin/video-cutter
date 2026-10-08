"""Native desktop window (pywebview) around the local web server."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from werkzeug.serving import make_server

from .jobs import Registry


class DesktopApi:
    """Methods exposed to the page as `window.pywebview.api.*`."""

    def __init__(self, registry: Registry):
        self._registry = registry
        self._window = None  # set once the window exists; not exposed to JS

    def attach(self, window) -> None:
        self._window = window

    def save_result(self, job_id: str) -> dict:
        """Ask where to save a finished cut and copy it there."""
        import webview

        job = self._registry.get_job(job_id)
        if not job or job.state != "done" or "path" not in job.result:
            return {"error": "The result is not available any more"}
        picked = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=job.result["filename"],
            file_types=("MP4 video (*.mp4)",),
        )
        if not picked:
            return {"cancelled": True}
        target = Path(picked if isinstance(picked, str) else picked[0])
        if target.suffix.lower() != ".mp4":
            target = target.with_suffix(".mp4")
        shutil.copyfile(job.result["path"], target)
        return {"saved": str(target)}

    def show_in_folder(self, path: str) -> None:
        """Open the system file manager with `path` selected."""
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)])


def run_desktop(app, port: int) -> None:
    """Serve `app` on 127.0.0.1:`port` in the background and show it in a native window."""
    import webview

    server = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    api = DesktopApi(app.config["registry"])
    window = webview.create_window(
        "Video Cutter",
        f"http://127.0.0.1:{port}",
        js_api=api,
        width=980,
        height=900,
        min_size=(640, 600),
    )
    api.attach(window)
    try:
        webview.start(private_mode=False)
    finally:
        server.shutdown()
