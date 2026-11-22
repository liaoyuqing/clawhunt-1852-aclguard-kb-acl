"""IAM 桩：5 个虚构角色。真实环境替换成 S2-IAM 的 /internal/whoami 调用。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from .models import Principal

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "roles.json"


def load_roles(path: Path = FIXTURE) -> Dict[str, Principal]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["key"]: Principal.from_dict(item) for item in raw["roles"]}


def all_principals(path: Path = FIXTURE) -> List[Principal]:
    return list(load_roles(path).values())