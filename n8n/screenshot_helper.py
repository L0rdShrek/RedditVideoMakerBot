"""
Playwright-based screenshot helper for n8n integration.

Takes screenshots of Reddit posts and comments for use in the
video generation pipeline. Designed to be called from n8n's
Execute Command node.

Usage:
    python screenshot_helper.py \
        --url "https://www.reddit.com/r/AskReddit/comments/abc123/..." \
        --username "reddit_user" \
        --password "reddit_pass" \
        --output-dir "./screenshots" \
        --comment-ids "comment1,comment2,comment3" \
        --theme "dark" \
        --width 1080 \
        --height 1920
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import ViewportSize, sync_playwright

DARK_MODE_COOKIES = [
    {
        "name": "reddit_session",
        "value": "",
        "domain": ".reddit.com",
        "path": "/",
    },
    {
        "name": "USER",
        "value": "eyJwcmVmcyI6eyJ0b3BDb250ZW50RGlzbWlzc2FsVGltZSI6MCwiZ2xvYmFsVGhlbWUiOiJSRURESVQiLCJuaWdodG1vZGUiOnRydWUsImNvbGxhcHNlZFRyYXlTZWN0aW9ucyI6eyJmYXZvcml0ZXMiOmZhbHNlLCJtdWx0aXMiOmZhbHNlLCJtb2RlcmF0aW5nIjpmYWxzZSwic3Vic2NyaXB0aW9ucyI6ZmFsc2UsInByb2ZpbGVzIjpmYWxzZX0sInRvcENvbnRlbnRUaW1lc0Rpc21pc3NlZCI6MH19",
        "domain": ".reddit.com",
        "path": "/",
    },
]

LIGHT_MODE_COOKIES = [
    {
        "name": "USER",
        "value": "eyJwcmVmcyI6eyJ0b3BDb250ZW50RGlzbWlzc2FsVGltZSI6MCwiZ2xvYmFsVGhlbWUiOiJSRURESVQiLCJuaWdodG1vZGUiOmZhbHNlLCJjb2xsYXBzZWRUcmF5U2VjdGlvbnMiOnsiZmF2b3JpdGVzIjpmYWxzZSwibXVsdGlzIjpmYWxzZSwibW9kZXJhdGluZyI6ZmFsc2UsInN1YnNjcmlwdGlvbnMiOmZhbHNlLCJwcm9maWxlcyI6ZmFsc2V9LCJ0b3BDb250ZW50VGltZXNEaXNtaXNzZWQiOjB9fQ==",
        "domain": ".reddit.com",
        "path": "/",
    },
]


def take_screenshots(
    url: str,
    username: str,
    password: str,
    output_dir: str,
    comment_ids: list[str],
    theme: str = "dark",
    width: int = 1080,
    height: int = 1920,
    zoom: float = 1.0,
) -> dict:
    """Take screenshots of a Reddit post and its comments."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results = {"title": None, "comments": []}
    dsf = (width // 600) + 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-CA,en;q=0.9",
            color_scheme="dark" if theme == "dark" else "light",
            viewport=ViewportSize(width=width, height=height),
            device_scale_factor=dsf,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        )

        # Set theme cookies
        cookies = DARK_MODE_COOKIES if theme == "dark" else LIGHT_MODE_COOKIES
        context.add_cookies(cookies)

        page = context.new_page()

        # Login
        page.goto("https://www.reddit.com/login", wait_until="domcontentloaded")
        page.locator('input[name="username"]').fill(username)
        page.locator('input[name="password"]').fill(password)
        page.get_by_role("button", name="Log In").click()
        page.wait_for_load_state("networkidle")

        # Navigate to post
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        # Handle NSFW
        try:
            nsfw_button = page.locator('[name="over18"][value="yes"]')
            if nsfw_button.is_visible(timeout=3000):
                nsfw_button.click()
                page.wait_for_load_state("networkidle")
        except Exception:
            pass

        # Screenshot the post title
        try:
            title_path = str(output_path / "title.png")
            post_content = page.locator('[data-test-id="post-content"]')
            post_content.screenshot(path=title_path)
            results["title"] = title_path
        except Exception as e:
            print(f"Warning: Could not screenshot title: {e}", file=sys.stderr)

        # Screenshot each comment
        for idx, comment_id in enumerate(comment_ids):
            try:
                comment_path = str(output_path / f"comment_{idx}.png")
                comment_el = page.locator(f"#t1_{comment_id}")
                comment_el.scroll_into_view_if_needed()
                comment_el.screenshot(path=comment_path)
                results["comments"].append({
                    "index": idx,
                    "comment_id": comment_id,
                    "path": comment_path,
                })
            except Exception as e:
                print(f"Warning: Could not screenshot comment {comment_id}: {e}", file=sys.stderr)

        browser.close()

    return results


def main():
    parser = argparse.ArgumentParser(description="Reddit Screenshot Helper for n8n")
    parser.add_argument("--url", required=True, help="Reddit post URL")
    parser.add_argument("--username", required=True, help="Reddit username")
    parser.add_argument("--password", required=True, help="Reddit password")
    parser.add_argument("--output-dir", required=True, help="Output directory for screenshots")
    parser.add_argument("--comment-ids", default="", help="Comma-separated comment IDs")
    parser.add_argument("--theme", default="dark", choices=["dark", "light"])
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--zoom", type=float, default=1.0)
    args = parser.parse_args()

    comment_ids = [c.strip() for c in args.comment_ids.split(",") if c.strip()]

    results = take_screenshots(
        url=args.url,
        username=args.username,
        password=args.password,
        output_dir=args.output_dir,
        comment_ids=comment_ids,
        theme=args.theme,
        width=args.width,
        height=args.height,
        zoom=args.zoom,
    )

    # Output JSON for n8n to parse
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
