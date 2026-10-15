"""Initialize local configuration with a random signing key; never print its value."""

import re
import secrets
from pathlib import Path

from dotenv import dotenv_values


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    content = (target if target.exists() else root / ".env.example").read_text(encoding="utf-8")
    existing = dotenv_values(target).get("DOCUMIND_AUTH_SECRET") if target.exists() else None
    if existing:
        if len(existing.encode()) < 32:
            raise SystemExit("La clave existente es demasiado corta; actualízala sin publicarla.")
        print("PASS: existing local signing key preserved")
        return
    line = "DOCUMIND_AUTH_SECRET=" + secrets.token_urlsafe(48)
    if re.search(r"^DOCUMIND_AUTH_SECRET=", content, flags=re.MULTILINE):
        content = re.sub(r"^DOCUMIND_AUTH_SECRET=.*$", line, content, flags=re.MULTILINE)
    else:
        content = content.rstrip() + "\n" + line + "\n"
    target.write_text(content, encoding="utf-8", newline="\n")
    print("PASS: local .env initialized; signing key kept private")


if __name__ == "__main__":
    main()
