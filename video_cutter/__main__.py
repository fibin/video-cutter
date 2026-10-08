"""Entry point: `python -m video_cutter` starts the server and opens the browser."""

from __future__ import annotations

import argparse
import logging
import socket
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Video Cutter: local web interface")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args()

    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}"
    print(f"Video Cutter is running at {url}")
    print(f"Files are stored in: {default_data_dir()}")
    print("Press Ctrl+C to stop")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    # Hide the dev-server warning and per-request lines; they only confuse in a local app.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    flask.cli.show_server_banner = lambda *args, **kwargs: None
    create_app().run(host="127.0.0.1", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
