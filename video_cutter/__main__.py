"""Entry point: `python -m video_cutter` opens the app in its own window (or the browser)."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import webbrowser

import flask.cli

from .app import create_app, default_data_dir


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return sock.getsockname()[1]
    raise RuntimeError("Could not find a free port")


def run_browser(app, port: int, open_browser: bool) -> None:
    url = f"http://127.0.0.1:{port}"
    print(f"Video Cutter is running at {url}")
    print(f"Files are stored in: {default_data_dir()}")
    print("Press Ctrl+C to stop")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


def main() -> None:
    # A windowed (no console) build has no stdout/stderr; give print() somewhere to go.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    parser = argparse.ArgumentParser(description="Video Cutter")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--browser", action="store_true", help="open in the web browser instead of an app window")
    parser.add_argument("--no-browser", action="store_true", help="with --browser: do not open the browser automatically")
    parser.add_argument("--self-test", metavar="REPORT", help="check the installation, write a report and exit")
    args = parser.parse_args()

    if args.self_test:
        from .selftest import run_self_test

        sys.exit(run_self_test(args.self_test))

    # Hide the dev-server warning and per-request lines; they only confuse in a local app.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    flask.cli.show_server_banner = lambda *args, **kwargs: None

    app = create_app()
    port = free_port(args.port)
    if not args.browser:
        try:
            from .desktop import run_desktop

            run_desktop(app, port)
            return
        except ImportError:
            # pywebview is only installed on Windows and macOS; elsewhere use the browser.
            pass
        except Exception as exc:  # e.g. no WebView2/GTK backend on this machine
            print(f"Could not open the app window ({exc}); using the browser instead.")
    run_browser(app, port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
