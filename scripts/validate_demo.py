from __future__ import annotations

import json

from opspilot.demo import create_demo_app


def validate() -> dict[str, object]:
    app = create_demo_app()
    schema = app.openapi()
    paths = set(schema["paths"])
    expected = {
        "/livez",
        "/api/scenarios",
        "/api/scenarios/{scenario_id}/investigate",
    }

    assert paths == expected
    assert all("remediation" not in path for path in paths)
    assert "securitySchemes" not in schema.get("components", {})
    assert schema["info"]["version"] == "0.8.0"

    return {
        "mode": "synthetic-demo",
        "routes": sorted(paths),
        "external_credentials": False,
        "arbitrary_prompt_input": False,
        "remediation_routes": False,
        "status": "passed",
    }


def main() -> None:
    print(json.dumps(validate(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
