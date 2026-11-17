"""Entry point of the packaged app. Without arguments, or with a file to open,
it starts the desktop app; with a command-line command (`selftest`,
`inspect`, `--version`, ...) it runs that, so the bundle can check itself:

  Refract.app/Contents/MacOS/Refract selftest
"""

import sys

COMMANDS = {"inspect", "verify", "export", "diff", "anonymize", "selftest", "gui", "--version", "-h", "--help"}


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in COMMANDS:
        from refract.cli import main as cli

        return cli(args)
    from refract.ui.app import main as gui

    return gui(args)


if __name__ == "__main__":
    raise SystemExit(main())
