"""Update the bundled Claude statusline command in settings.json."""

import sys
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from user_paths import reject_json_constant


def install_setting(path, command):
    try:
        settings = {}
        if path.exists():
            settings = json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=reject_json_constant,
            )
        if not isinstance(settings, dict):
            raise ValueError("Expected a JSON object")
    except (OSError, ValueError) as error:
        sys.exit(f"Error: cannot parse {path}: {error}")

    settings["statusLine"] = {"type": "command", "command": command}
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary:
        staged = Path(temporary.name)
        try:
            json.dump(settings, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.close()
            if path.exists():
                staged.chmod(path.stat().st_mode & 0o777)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        install_setting(Path(sys.argv[1]), sys.argv[2])
    except OSError as error:
        sys.exit(str(error))
