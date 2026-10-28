"""Build tests/data/helpdesk-v1-moved.json: same meaning as v1, only ids,
positions, node order, key order and export metadata differ (R2 fixture).

    uv run python tests/tools/make_moved.py
"""

import json
import uuid
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def reverse_keys(value):
    if isinstance(value, dict):
        return {key: reverse_keys(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [reverse_keys(item) for item in value]
    return value


def main() -> None:
    workflow = json.loads((DATA / "helpdesk-v1.json").read_text(encoding="utf-8"))
    for index, node in enumerate(workflow["nodes"]):
        node["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"moved/{node['name']}"))
        node["position"] = [node["position"][0] + 400, node["position"][1] - 120 * index]
        if "webhookId" in node:
            node["webhookId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"moved-hook/{node['name']}"))
    workflow["nodes"].reverse()
    workflow["id"] = "MovedWorkflow0001"
    workflow["versionId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "moved/version"))
    workflow["updatedAt"] = "2026-10-28T09:00:00.000Z"
    out = DATA / "helpdesk-v1-moved.json"
    out.write_text(json.dumps(reverse_keys(workflow), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
