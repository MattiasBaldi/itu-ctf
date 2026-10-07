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
itu-ctf ls            # list challenges: id, points, solved, name
itu-ctf show <id>     # full description, tags, hints, file links
itu-ctf get <id>      # download one challenge into ./<id>_<name>/
itu-ctf get           # download ALL (or filtered) into ./<category>/<id>_<name>/
                      # (each folder gets a README.md + any attached files)
itu-ctf get -o DIR    # ...rooted under DIR instead of the current directory
itu-ctf logout        # clear the cached session
```

### Filters

`ls` and `get` (when no id is given) take filters, and they combine freely:

```bash
itu-ctf ls -u                  # not solved yet
itu-ctf ls -c web              # one category (case-insensitive)
itu-ctf ls -u -c web           # combined
itu-ctf ls --min 100 --max 300 # points range

itu-ctf get -u -o ~/ctf-practice   # bulk-download just the unsolved ones
```

| flag | meaning |
|---|---|
| `-u`, `--unsolved` | not solved yet |
| `-s`, `--solved` | already solved |
| `-c`, `--category NAME` | one category |
| `--min N` / `--max N` | points range |
