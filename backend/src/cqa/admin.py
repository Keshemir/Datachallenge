"""Create/rotate the single-workspace administrator password locally, never via HTTP."""

import argparse
import getpass
import os
import secrets
from pathlib import Path

from dotenv import set_key

from .security import hash_password
from .settings import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument(
        "--password-file", type=Path, default=ROOT / ".secrets" / "admin-password.txt"
    )
    args = parser.parse_args()
    if args.generate:
        password = secrets.token_urlsafe(24)
        args.password_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Never overwrite existing credentials accidentally.
        fd = os.open(args.password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(password + "\n")
    else:
        password = getpass.getpass("New administrator password (12–128 characters): ")
        if password != getpass.getpass("Repeat password: "):
            raise SystemExit("Passwords do not match")
    encoded = hash_password(password)
    args.env_file.touch(mode=0o600, exist_ok=True)
    set_key(args.env_file, "CQA_PASSWORD_HASH", encoded)
    print(
        "Administrator password configured. Restart the backend; previous sessions become invalid."
    )
    if args.generate:
        print(f"Read the password locally: {args.password_file}")


if __name__ == "__main__":
    main()
