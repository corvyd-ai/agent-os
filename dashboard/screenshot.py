#!/usr/bin/env python3
"""agent-os Dashboard screenshot utility.

Captures PNG screenshots of dashboard pages using Playwright.
Requires the dashboard to be running (make dev).

Usage:
    python screenshot.py                           # Overview page (/)
    python screenshot.py /costs                    # Specific page
    python screenshot.py --all                     # All pages
    python screenshot.py /costs --full-page        # Full scrollable height
    python screenshot.py /costs --width 1920       # Custom viewport
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Static routes (always captured)
STATIC_ROUTES = [
    "/",
    "/tasks",
    "/agents",
    "/timeline",
    "/costs",
    "/messages",
    "/strategy",
]


def _discover_agent_routes(port: int) -> list[str]:
    """Discover agent detail routes from the API."""
    try:
        url = f"http://localhost:{port}/api/agents"
        with urllib.request.urlopen(url, timeout=3) as resp:
            agents = json.loads(resp.read())
        return [f"/agents/{a['id']}" for a in agents]
    except Exception:
        return []


def route_to_filename(route: str) -> str:
    """Convert a route path to a screenshot filename."""
    if route == "/":
        return "overview.png"
    name = route.lstrip("/").replace("/", "--")
    return f"{name}.png"


def capture(route: str, *, page, output_dir: Path, full_page: bool, delay: int, port: int) -> Path:
    """Navigate to a route and capture a screenshot."""
    url = f"http://localhost:{port}{route}"
    page.goto(url, wait_until="networkidle")

    # Wait for Loading spinner to disappear (if present)
    page.wait_for_selector(".animate-spin", state="detached", timeout=10000)

    # Extra delay for Recharts SVG animations
    if delay > 0:
        page.wait_for_timeout(delay)

    filepath = output_dir / route_to_filename(route)
    page.screenshot(path=str(filepath), full_page=full_page)
    return filepath


def main(args: argparse.Namespace) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: playwright not installed. Run: pip install playwright && playwright install chromium", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(__file__).parent / "screenshots"
    output_dir.mkdir(exist_ok=True)

    if args.all:
        # Discover agent routes dynamically from the API
        agent_routes = _discover_agent_routes(args.port)
        routes = STATIC_ROUTES + agent_routes
    else:
        routes = [args.route]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})

        try:
            # Quick connectivity check
            page.goto(f"http://localhost:{args.port}/", wait_until="commit", timeout=5000)
        except Exception:
            print(f"Error: Cannot connect to dashboard at localhost:{args.port}", file=sys.stderr)
            print("Make sure the dashboard is running (make dev)", file=sys.stderr)
            browser.close()
            sys.exit(1)

        for route in routes:
            filepath = capture(route, page=page, output_dir=output_dir, full_page=args.full_page, delay=args.delay, port=args.port)
            print(filepath)

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture agent-os Dashboard screenshots")
    parser.add_argument("route", nargs="?", default="/", help="Dashboard route to capture (default: /)")
    parser.add_argument("--all", action="store_true", help="Capture all pages")
    parser.add_argument("--width", type=int, default=1440, help="Viewport width (default: 1440)")
    parser.add_argument("--height", type=int, default=900, help="Viewport height (default: 900)")
    parser.add_argument("--delay", type=int, default=1500, help="Extra wait after load in ms (default: 1500)")
    parser.add_argument("--full-page", action="store_true", help="Capture full scrollable height")
    parser.add_argument("--port", type=int, default=5175, help="Frontend port (default: 5175)")
    args = parser.parse_args()
    main(args)
