#!/usr/bin/env python3
"""itu-ctf - CLI for ctf.itunderground.dk (CTFd).

Login credentials themselves are never stored by this tool. Provide them
via the CTF_USERNAME / CTF_PASSWORD environment variables, or it will
prompt for them interactively (password input is hidden). Once logged in,
the resulting session cookie + CSRF token are cached to disk (mode 600)
so you aren't re-prompted on every command - a fresh login only happens
when there's no cache yet or the cached session has expired.

Usage:
    itu-ctf ls                 list all challenges (id, category, points, solved, name)
    itu-ctf show <id>          show a challenge's full description, tags, hints, files
    itu-ctf get                fetch ALL challenges into ./<category>/<id>_<name>/
                               (each folder gets a README.md with the description
                               plus any attached files)
    itu-ctf get <id>           fetch just one challenge into ./<id>_<name>/
    itu-ctf get [<id>] -o DIR  ...rooted under DIR instead of the current directory
    itu-ctf logout             clear the cached session (forces re-login next run)

Filters (ls and get, when no id is given):
    --unsolved                 only challenges you haven't solved
    --solved                   only challenges you've already solved
    --category NAME            only this category (case-insensitive)
    --min-points N / --max-points N   only challenges in a points range

    e.g. itu-ctf ls --unsolved --category web
         itu-ctf get --unsolved -o ~/ctf-practice
"""
import argparse
import getpass
import json
import os
import re
import sys
from urllib.parse import urlparse

import requests

BASE_URL = "https://ctf.itunderground.dk"
USER_AGENT = "itu-ctf-cli/1.0"
CACHE_DIR = os.path.expanduser("~/.cache/itu-ctf")
CACHE_FILE = os.path.join(CACHE_DIR, "session.json")


def get_credentials():
    username = os.environ.get("CTF_USERNAME")
    password = os.environ.get("CTF_PASSWORD")
    if not username:
        username = input("Username: ")
    if not password:
        password = getpass.getpass("Password: ")
    return username, password


def login(session: requests.Session, username: str, password: str):
    resp = session.get(f"{BASE_URL}/login")
    resp.raise_for_status()
    match = re.search(r'name="nonce"\s+type="hidden"\s+value="([a-f0-9]+)"', resp.text)
    if not match:
        sys.exit("Could not find login nonce - site structure may have changed.")
    nonce = match.group(1)

    data = {"name": username, "password": password, "_submit": "Submit", "nonce": nonce}
    resp = session.post(f"{BASE_URL}/login", data=data, allow_redirects=True)
    resp.raise_for_status()

    if resp.url.rstrip("/").endswith("/login"):
        sys.exit("Login failed - check your username/password.")


def get_csrf_token(session: requests.Session) -> str:
    resp = session.get(f"{BASE_URL}/challenges")
    resp.raise_for_status()
    match = re.search(r"csrfNonce['\"]?\s*:\s*[\"']([a-f0-9]+)[\"']", resp.text)
    if not match:
        sys.exit("Could not find CSRF token for API calls - site structure may have changed.")
    return match.group(1)


def load_cached_session(session: requests.Session):
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        session.cookies.update(data["cookies"])
        return data["csrf_token"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def save_cached_session(session: requests.Session, csrf_token: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump({"cookies": session.cookies.get_dict(), "csrf_token": csrf_token}, f)
    os.chmod(CACHE_FILE, 0o600)


def session_is_valid(session: requests.Session, csrf_token: str) -> bool:
    try:
        resp = session.get(
            f"{BASE_URL}/api/v1/users/me",
            headers={"Accept": "application/json", "CSRF-Token": csrf_token},
        )
        return resp.status_code == 200 and resp.json().get("success", False)
    except (requests.RequestException, ValueError):
        return False


def ensure_auth(session: requests.Session) -> str:
    csrf_token = load_cached_session(session)
    if csrf_token and session_is_valid(session, csrf_token):
        return csrf_token

    username, password = get_credentials()
    login(session, username, password)
    csrf_token = get_csrf_token(session)
    save_cached_session(session, csrf_token)
    return csrf_token


def cmd_auth(session: requests.Session):
    """Explicit login (like 'gh auth login') - always re-authenticates and
    overwrites the cache, regardless of whether one already exists."""
    username, password = get_credentials()
    login(session, username, password)
    csrf_token = get_csrf_token(session)
    save_cached_session(session, csrf_token)

    name = username
    try:
        resp = session.get(
            f"{BASE_URL}/api/v1/users/me",
            headers={"Accept": "application/json", "CSRF-Token": csrf_token},
        )
        name = resp.json().get("data", {}).get("name", username)
    except (requests.RequestException, ValueError):
        pass
    print(f"Logged in as {name}. Session cached at {CACHE_FILE} (not your password - just the session).")


def api_get(session: requests.Session, csrf_token: str, path: str):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "CSRF-Token": csrf_token,
    }
    resp = session.get(f"{BASE_URL}{path}", headers=headers)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        sys.exit(f"API request failed: {payload}")
    return payload["data"]


def fetch_challenges(session, csrf_token):
    return api_get(session, csrf_token, "/api/v1/challenges")


def fetch_challenge_detail(session, csrf_token, challenge_id):
    return api_get(session, csrf_token, f"/api/v1/challenges/{challenge_id}")


def slugify(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name or "challenge").strip("_")


def add_filter_args(parser):
    parser.add_argument("--unsolved", action="store_true", help="only challenges you haven't solved")
    parser.add_argument("--solved", action="store_true", help="only challenges you've already solved")
    parser.add_argument("--category", help="only this category (case-insensitive)")
    parser.add_argument("--min-points", type=int, help="only challenges worth at least this many points")
    parser.add_argument("--max-points", type=int, help="only challenges worth at most this many points")


def filter_challenges(challenges, args):
    result = challenges
    if getattr(args, "unsolved", False):
        result = [c for c in result if not c.get("solved_by_me")]
    if getattr(args, "solved", False):
        result = [c for c in result if c.get("solved_by_me")]
    category = getattr(args, "category", None)
    if category:
        result = [c for c in result if (c.get("category") or "").lower() == category.lower()]
    min_points = getattr(args, "min_points", None)
    if min_points is not None:
        result = [c for c in result if (c.get("value") or 0) >= min_points]
    max_points = getattr(args, "max_points", None)
    if max_points is not None:
        result = [c for c in result if (c.get("value") or 0) <= max_points]
    return result


def save_challenge(session, chall_dir, detail):
    """Write README.md + download attached files for one challenge into chall_dir."""
    os.makedirs(chall_dir, exist_ok=True)

    with open(os.path.join(chall_dir, "README.md"), "w") as fh:
        fh.write(f"# {detail.get('name')}\n\n")
        fh.write(f"- id: {detail.get('id')}\n")
        fh.write(f"- category: {detail.get('category')}\n")
        fh.write(f"- points: {detail.get('value')}\n")
        fh.write(f"- solved: {bool(detail.get('solved_by_me'))}\n\n")
        if detail.get("description"):
            fh.write(detail["description"] + "\n\n")
        conn = detail.get("connection_info")
        if conn:
            fh.write(f"Connection info: {conn}\n\n")
        tags = detail.get("tags") or []
        if tags:
            tag_names = [t.get("value", t) if isinstance(t, dict) else t for t in tags]
            fh.write(f"Tags: {', '.join(tag_names)}\n")

    for f in detail.get("files") or []:
        url = f if f.startswith("http") else f"{BASE_URL}{f}"
        filename = os.path.basename(urlparse(url).path) or "file"
        resp = session.get(url)
        resp.raise_for_status()
        with open(os.path.join(chall_dir, filename), "wb") as fh2:
            fh2.write(resp.content)


# ---- commands ----

def cmd_ls(session, csrf_token, args):
    challenges = filter_challenges(fetch_challenges(session, csrf_token), args)
    if args.json:
        print(json.dumps(challenges, indent=2))
        return

    if not challenges:
        print("No challenges match those filters.")
        return

    challenges.sort(key=lambda c: (c.get("category", ""), c.get("value", 0)))
    last_category = None
    for c in challenges:
        if c.get("category") != last_category:
            last_category = c.get("category")
            print(f"\n== {last_category} ==")
        solved = "x" if c.get("solved_by_me") else " "
        print(f"[{solved}] id={c.get('id'):<4} {c.get('value', 0):>4} pts  {c.get('name')}")


def cmd_show(session, csrf_token, args):
    c = fetch_challenge_detail(session, csrf_token, args.id)
    if args.json:
        print(json.dumps(c, indent=2))
        return

    print(f"[{c.get('id')}] {c.get('name')}  -  {c.get('category')}  -  {c.get('value')} pts")
    print("-" * 60)
    if c.get("description"):
        print(c["description"])

    tags = c.get("tags") or []
    if tags:
        tag_names = [t.get("value", t) if isinstance(t, dict) else t for t in tags]
        print(f"\nTags: {', '.join(tag_names)}")

    files = c.get("files") or []
    if files:
        print("\nFiles:")
        for f in files:
            url = f if f.startswith("http") else f"{BASE_URL}{f}"
            print(f"  {url}")

    hints = c.get("hints") or []
    if hints:
        print("\nHints:")
        for h in hints:
            cost = h.get("cost", 0)
            label = f" (cost: {cost})" if cost else ""
            print(f"  - hint id={h.get('id')}{label}")

    conn = c.get("connection_info")
    if conn:
        print(f"\nConnection info: {conn}")

    print(f"\nSolves: {c.get('solves', '?')}   Solved by you: {bool(c.get('solved_by_me'))}")


def cmd_get(session, csrf_token, args):
    base_dir = args.output

    if args.id:
        detail = fetch_challenge_detail(session, csrf_token, args.id)
        chall_dir = os.path.join(base_dir, f"{args.id}_{slugify(detail.get('name'))}")
        save_challenge(session, chall_dir, detail)
        print(f"[{detail.get('id')}] {detail.get('name')} -> {chall_dir}")
        return

    matches = filter_challenges(fetch_challenges(session, csrf_token), args)
    if not matches:
        print("No challenges match those filters.")
        return

    os.makedirs(base_dir, exist_ok=True)
    for summary in matches:
        cid = summary["id"]
        detail = fetch_challenge_detail(session, csrf_token, cid)
        category = slugify(detail.get("category") or "misc")
        chall_dir = os.path.join(base_dir, category, f"{cid}_{slugify(detail.get('name'))}")
        save_challenge(session, chall_dir, detail)
        solved = "x" if detail.get("solved_by_me") else " "
        print(f"[{solved}] [{cid}] {detail.get('name')} -> {chall_dir}")


def main():
    parser = argparse.ArgumentParser(prog="itu-ctf", description="CLI for ctf.itunderground.dk")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="log in and cache the session (like 'gh auth login')")

    ls_p = sub.add_parser("ls", help="list challenges (supports filters)")
    ls_p.add_argument("--json", action="store_true", help="print raw JSON")
    add_filter_args(ls_p)

    show_p = sub.add_parser("show", help="show a challenge's description, tags, hints, files")
    show_p.add_argument("id", help="challenge id (see 'ls')")
    show_p.add_argument("--json", action="store_true", help="print raw JSON")

    get_p = sub.add_parser("get", help="download one challenge (id given) or matching ones (no id, filters apply)")
    get_p.add_argument("id", nargs="?", help="challenge id (see 'ls'); omit to fetch everything matching the filters")
    get_p.add_argument("-o", "--output", default=".", help="base directory (default: current dir)")
    add_filter_args(get_p)

    sub.add_parser("logout", help="clear the cached session (forces re-login next run)")

    args = parser.parse_args()

    if args.command == "logout":
        try:
            os.remove(CACHE_FILE)
            print("Cached session cleared.")
        except FileNotFoundError:
            print("No cached session to clear.")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    if args.command == "auth":
        cmd_auth(session)
        return

    csrf_token = ensure_auth(session)

    if args.command == "ls":
        cmd_ls(session, csrf_token, args)
    elif args.command == "show":
        cmd_show(session, csrf_token, args)
    elif args.command == "get":
        cmd_get(session, csrf_token, args)


if __name__ == "__main__":
    main()
