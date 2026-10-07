# itu-ctf

Small CLI for the ctf.itunderground.dk CTFd instance: list challenges, show
a challenge's description/tags/hints/files, and download challenge files.

Login credentials are never stored by this tool - it reads `CTF_USERNAME` /
`CTF_PASSWORD` from the environment if set, otherwise it prompts for them
interactively (password input is hidden). Once logged in, the session
cookie + CSRF token (not the password) are cached to
`~/.cache/itu-ctf/session.json` (mode 600), so you aren't re-prompted on
every command - the same idea as `gh auth login`.

## Install

```bash
chmod +x itu-ctf.py
ln -s "$(pwd)/itu-ctf.py" ~/bin/itu-ctf   # any directory already on your PATH works
```

## Usage

```bash
itu-ctf auth          # log in once and cache the session (optional - other
                      # commands will prompt automatically if not logged in)
itu-ctf ls            # list challenges, with a header row: [solved] id pts name
itu-ctf show <id>     # full description, tags, hints, file links
itu-ctf get <id>      # download one challenge into ./<id>_<name>/
itu-ctf get           # download ALL (or filtered) into ./<category>/<id>_<name>/
                      # (each folder gets a README.md + any attached files)
itu-ctf get -o DIR    # ...rooted under DIR instead of the current directory
itu-ctf logout        # clear the cached session
```

`ls` shows a solved-count summary, a header row, and category sections -
all aligned to the same columns (widths adjust to fit whatever ids/points
are in the list, so it won't misalign even with a 4-digit id):

```
8/9 solved

     ID  PTS  NAME

    WEB
    ---
[x]  94   50  NO ROBOTS!
[ ] 119  400  Super
```

(`[x]` = solved, `[ ]` = not solved yet, then id, points, name.)

### Filters

No flags - `ls` and `get` (when no id is given) take plain words, and you can
combine as many as you like:

```bash
itu-ctf ls unsolved             # not solved yet
itu-ctf ls web                  # one category (case-insensitive)
itu-ctf ls unsolved web         # combined
itu-ctf ls 100-300              # points range
itu-ctf ls 200+                 # 200 points or more

itu-ctf get unsolved -o ~/ctf-practice   # bulk-download just the unsolved ones
```

| word | meaning |
|---|---|
| `unsolved` | not solved yet |
| `solved` | already solved |
| `<category>` | one category, e.g. `web`, `crypto` |
| `N-M` | points between N and M |
| `N+` | points N or more |

An unrecognized word exits with an error listing the real category names.
`get` treats a single bare number as a challenge id instead (`itu-ctf get 119`).
