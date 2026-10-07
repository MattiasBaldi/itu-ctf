# ctf

Small CLI for the ctf.itunderground.dk CTFd instance: list challenges, show
a challenge's description/tags/hints/files, and download challenge files.

Credentials are never stored by this tool. It reads `CTF_USERNAME` /
`CTF_PASSWORD` from the environment if set, otherwise it prompts for them
interactively each run (password input is hidden).

## Install

```bash
chmod +x ctf.py
ln -s "$(pwd)/ctf.py" ~/bin/ctf   # any directory already on your PATH works
```

## Usage

```bash
ctf ls                 # list all challenges (id, category, points, solved, name)
ctf show <id>          # full description, tags, hints, file links for one challenge
ctf get <id>           # download one challenge's files into ./<id>_<name>/
ctf get                # fetch EVERYTHING into ./<category>/<id>_<name>/
                        # (each folder gets a README.md + any attached files)
ctf get [<id>] -o DIR  # root output under DIR instead of the current directory
```
