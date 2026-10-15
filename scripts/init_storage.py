"""Create a private bucket explicitly; safe to repeat."""

from packages.config import get_settings
from packages.storage import S3Storage


def main() -> None:
    S3Storage(get_settings()).ensure_bucket()
    print("PASS: private storage bucket available")


if __name__ == "__main__":
    main()
