#!/usr/bin/env python3
"""Refresh the live numbers baked into index.html.

Numbers on a static page go stale silently, so every one of them lives between
a pair of marker comments and is rewritten from an authoritative source here:

    <!--S:stars-->180<!--E:stars-->              total stars over own non-fork repos
    <!--S:star:clawock-->7<!--E:star:clawock-->  stars of one repo
    <!--S:zhihu-->2.0<!--E:zhihu-->              知乎 follower count, in thousands

Adding a new project card needs no change here: add the marker pair with the
repo name and it gets filled on the next run.

Every failure is fatal. A run that cannot resolve a number must go red rather
than quietly leave a stale one in place and report success.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "index.html"

OWNER = "KCNyu"
# 知乎 has no open API; the profile README repo already refreshes the figure
# daily with the cookie it holds, so read it from there instead of duplicating
# that secret into this repo.
ZHIHU_SOURCE = f"https://raw.githubusercontent.com/{OWNER}/{OWNER}/master/README.md"
ZHIHU_RE = re.compile(
    r"<!--START_SECTION:zhihu-followers-->(.*?)<!--END_SECTION:zhihu-followers-->",
    re.S,
)
FOLLOWERS_RE = re.compile(r"([\d,]+)\s*个关注")

MARKER_RE = re.compile(r"<!--S:([^>]+?)-->(.*?)<!--E:\1-->", re.S)

# A plausibility floor: the account has had well over this many repos and stars
# for years, so a smaller number means the API answered with something partial
# rather than that the numbers really dropped.
MIN_REPOS = 5
MIN_TOTAL_STARS = 50


def die(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def api(path: str) -> list | dict:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{OWNER}-homepage-stats",
        },
    )
    token = os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        die(f"GitHub API {path} failed: {exc}")


def fetch_repos() -> dict[str, int]:
    stars: dict[str, int] = {}
    page = 1
    while True:
        batch = api(f"/users/{OWNER}/repos?per_page=100&type=owner&page={page}")
        if not isinstance(batch, list):
            die(f"unexpected repo payload on page {page}")
        for repo in batch:
            if not repo.get("fork"):
                stars[repo["name"]] = repo["stargazers_count"]
        if len(batch) < 100:
            return stars
        page += 1


def fetch_zhihu_thousands() -> str:
    req = urllib.request.Request(ZHIHU_SOURCE, headers={"User-Agent": f"{OWNER}-homepage-stats"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            readme = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        die(f"could not read {ZHIHU_SOURCE}: {exc}")

    section = ZHIHU_RE.search(readme)
    if not section:
        die("zhihu-followers markers missing from the profile README")
    followers = FOLLOWERS_RE.search(section.group(1))
    if not followers:
        die(f"no 个关注 count inside the zhihu section: {section.group(1).strip()!r}")

    count = int(followers.group(1).replace(",", ""))
    if count <= 0:
        die(f"implausible zhihu follower count: {count}")
    return f"{count / 1000:.1f}"


def resolve(key: str, stars: dict[str, int], zhihu: str) -> str:
    if key == "stars":
        return str(sum(stars.values()))
    if key == "zhihu":
        return zhihu
    if key.startswith("star:"):
        name = key[len("star:") :]
        if name not in stars:
            die(f"marker S:{key} names a repo that is not an own non-fork repo")
        return str(stars[name])
    die(f"unknown marker S:{key}")


def main() -> int:
    stars = fetch_repos()
    if len(stars) < MIN_REPOS:
        die(f"only {len(stars)} repos came back, expected at least {MIN_REPOS}")
    total = sum(stars.values())
    if total < MIN_TOTAL_STARS:
        die(f"total stars came back as {total}, expected at least {MIN_TOTAL_STARS}")
    zhihu = fetch_zhihu_thousands()

    page = PAGE.read_text(encoding="utf-8")
    if not MARKER_RE.search(page):
        die("index.html contains no <!--S:...--> markers; nothing would be updated")

    changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        key, old = match.group(1), match.group(2)
        new = resolve(key, stars, zhihu)
        if new != old:
            print(f"  {key}: {old} -> {new}")
            changed += 1
        return f"<!--S:{key}-->{new}<!--E:{key}-->"

    updated = MARKER_RE.sub(replace, page)
    if changed:
        PAGE.write_text(updated, encoding="utf-8")
        print(f"updated {changed} value(s) in index.html")
    else:
        print("all values already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
