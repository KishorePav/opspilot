from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from opspilot.config import Settings
from opspilot.storage.migrations import apply_migrations


def main() -> None:
    settings = Settings.from_environment()
    result = apply_migrations(settings.database_url, Path("migrations"))
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
