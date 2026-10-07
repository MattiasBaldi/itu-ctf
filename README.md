# ituctf

Small CLI for the ctf.itunderground.dk CTFd instance: list challenges, show
a challenge's description/tags/hints/files, and download challenge files.

Login credentials are never stored by this tool - it reads `CTF_USERNAME` /
`CTF_PASSWORD` from the environment if set, otherwise it prompts for them
interactively (password input is hidden). Once logged in, the session
cookie + CSRF token (not the password) are cached to
`~/.cache/ituctf/session.json` (mode 600), so you aren't re-prompted on
every command - the same idea as `gh auth login`.

## Install

```bash
chmod +x ituctf.py
ln -s "$(pwd)/ituctf.py" ~/bin/ituctf   # any directory already on your PATH works
```

## Usage

```bash
ituctf auth             # log in once and cache the session (optional - other
                         # commands will prompt automatically if not logged in)
ituctf ls                 # list all challenges (id, category, points, solved, name)
ituctf show <id>          # full description, tags, hints, file links for one challenge
ituctf get <id>           # download one challenge's files into ./<id>_<name>/
ituctf get                # fetch EVERYTHING into ./<category>/<id>_<name>/
                           # (each folder gets a README.md + any attached files)
ituctf get [<id>] -o DIR  # root output under DIR instead of the current directory
ituctf logout            # clear the cached session
```
