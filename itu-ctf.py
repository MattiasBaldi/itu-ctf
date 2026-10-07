#!/usr/bin/env python3
"""itu-ctf - CLI for ctf.itunderground.dk (CTFd).

Login credentials themselves are never stored by this tool. Provide them
via the CTF_USERNAME / CTF_PASSWORD environment variables, or it will
prompt for them interactively (password input is hidden). Once logged in,
the resulting session cookie + CSRF token are cached to disk (mode 600)
so you aren't re-prompted on every command - a fresh login only happens
when there's no cache yet or the cached session has expired.

Usage:
    itu-ctf ls              list challenges, with a header row: id, pts, name
    itu-ctf show <id>       full description, tags, hints, files for one
    itu-ctf get <id>        download one challenge into ./<id>_<name>/
    itu-ctf get             download ALL (or filtered) into ./<category>/<id>_<name>/
    itu-ctf get -o DIR      ...rooted under DIR instead of the current directory
    itu-ctf logout          clear the cached session

Filters (ls and get, when no id given) are just bare words, no flags -
combine as many as you like:
    unsolved | solved        solve status
    <category>                e.g. web, crypto (case-insensitive)
    N-M  or  N+               points range, e.g. 100-300 or 200+

    e.g. itu-ctf ls unsolved web
         itu-ctf get unsolved 100-300 -o ~/ctf-practice
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


def filter_challenges(challenges, tokens):
    """No flags - just bare words: 'unsolved', 'solved', a category name
    (case-insensitive), or a points range like '100-300' or '200+'."""
    if not tokens:
        return challenges

    categories = {(c.get("category") or "").lower() for c in challenges}
    result = challenges
    for tok in tokens:
        low = tok.lower()
        if low == "unsolved":
            result = [c for c in result if not c.get("solved_by_me")]
        elif low == "solved":
            result = [c for c in result if c.get("solved_by_me")]
        elif re.fullmatch(r"\d+-\d+", tok):
            lo, hi = (int(x) for x in tok.split("-"))
            result = [c for c in result if lo <= (c.get("value") or 0) <= hi]
        elif re.fullmatch(r"\d+\+", tok):
            lo = int(tok[:-1])
            result = [c for c in result if (c.get("value") or 0) >= lo]
        elif low in categories:
            result = [c for c in result if (c.get("category") or "").lower() == low]
        else:
            valid = ", ".join(sorted(categories)) or "(none)"
            sys.exit(f"Not a recognized filter: {tok!r}\n"
                      f"Use 'solved', 'unsolved', a range like 100-300 or 200+, or a category: {valid}")
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
    challenges = filter_challenges(fetch_challenges(session, csrf_token), args.query)
    if args.json:
        print(json.dumps(challenges, indent=2))
        return

    if not challenges:
        print("No challenges match those filters.")
        return

    challenges.sort(key=lambda c: (c.get("category", ""), c.get("value", 0)))

    prefix = "    "  # width of "[x] "
    id_w = max((len(str(c.get("id", ""))) for c in challenges), default=2)
    pts_w = max((len(str(c.get("value", 0))) for c in challenges), default=3)

    solved_count = sum(1 for c in challenges if c.get("solved_by_me"))
    print(f"{solved_count}/{len(challenges)} solved\n")
    print(f"{prefix}{'ID':>{id_w}}  {'PTS':>{pts_w}}  NAME")

    last_category = None
    for c in challenges:
        if c.get("category") != last_category:
            last_category = c.get("category")
            title = (last_category or "uncategorized").upper()
            print(f"\n{prefix}{title}")
            print(f"{prefix}{'-' * len(title)}")
        solved = "x" if c.get("solved_by_me") else " "
        print(f"[{solved}] {c.get('id'):>{id_w}}  {c.get('value', 0):>{pts_w}}  {c.get('name')}")


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

    if len(args.query) == 1 and args.query[0].isdigit():
        challenge_id = args.query[0]
        detail = fetch_challenge_detail(session, csrf_token, challenge_id)
        chall_dir = os.path.join(base_dir, f"{challenge_id}_{slugify(detail.get('name'))}")
        save_challenge(session, chall_dir, detail)
        print(f"[{detail.get('id')}] {detail.get('name')} -> {chall_dir}")
        return

    matches = filter_challenges(fetch_challenges(session, csrf_token), args.query)
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
        print(f"[{solved}] {cid:>3}  {detail.get('name')} -> {chall_dir}")


def main():
    parser = argparse.ArgumentParser(prog="itu-ctf", description="CLI for ctf.itunderground.dk")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="log in and cache the session")

    ls_p = sub.add_parser("ls", help="list challenges  e.g. ls unsolved web 100-300")
    ls_p.add_argument("query", nargs="*", help="unsolved | solved | a category | N-M | N+")
    ls_p.add_argument("--json", action="store_true", help="raw JSON")

    show_p = sub.add_parser("show", help="show one challenge in full")
    show_p.add_argument("id")
    show_p.add_argument("--json", action="store_true", help="raw JSON")

    get_p = sub.add_parser("get", help="download by id, or filtered/all  e.g. get unsolved web")
    get_p.add_argument("query", nargs="*", help="a challenge id, or filters like 'ls'")
    get_p.add_argument("-o", "--output", default=".", metavar="DIR", help="output dir (default: .)")

    sub.add_parser("logout", help="clear the cached session")

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
