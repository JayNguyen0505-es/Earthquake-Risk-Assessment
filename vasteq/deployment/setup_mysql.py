"""Create local MySQL secrets without displaying or replacing existing passwords."""

import os
from pathlib import Path
import secrets


def main():
    directory = Path(__file__).resolve().parent / ".secrets"
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    for name in ["mysql_root_password", "mysql_app_password"]:
        path = directory / name
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if not path.is_file() or not path.read_text().strip():
                raise ValueError(f"Existing secret is not a nonempty file: {path}")
            path.chmod(0o600)
        else:
            with os.fdopen(descriptor, "w") as handle:
                handle.write(secrets.token_hex(32) + "\n")
    print("MySQL secret files are ready; existing passwords were preserved.")


if __name__ == "__main__":
    main()
