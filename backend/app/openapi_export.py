import json
from pathlib import Path

from app.main import app

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def export() -> str:
    return json.dumps(app.openapi(), indent=2) + "\n"


def main() -> None:
    OUTPUT_PATH.write_text(export(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
