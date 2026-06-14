"""
Fully native desktop app — a real macOS window (WKWebView via pywebview), no
browser. Serves the dashboard from a background thread on a private port and
renders it in a native window with its own Dock icon.

  python run.py app

Requires: pip install --user pywebview  (pulls pyobjc WebKit).
"""

from __future__ import annotations
import functools
import http.server
import os
import socketserver
import threading


def _serve(directory: str) -> int:
    """Start a localhost-only static server on a free port; return the port."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1]


def main() -> None:
    try:
        import webview
    except ImportError:
        raise SystemExit(
            "native app needs pywebview — install it with:\n"
            "  python3 -m pip install --user pywebview")

    from forex_bot import dashboard, paper

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    os.chdir(repo)

    # Generate the dashboard HTML and refresh the servable state snapshot.
    dashboard.write("dashboard.html")
    st = paper.load_state()
    if st is not None:
        paper.save_state(st)

    port = _serve(repo)
    webview.create_window(
        "GQ Paper Trading",
        f"http://127.0.0.1:{port}/dashboard.html",
        width=1120, height=840, min_size=(720, 600),
        background_color="#070b14",
    )
    webview.start()                      # blocks on the main thread (required on macOS)


if __name__ == "__main__":
    main()
