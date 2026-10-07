import os
from typing import Dict, Any, Optional
from pathlib import Path
import yaml
from .base import BaseTool, ToolResult


class MonsterDossierTool(BaseTool):
    """
    怪物战术情报查阅工具：
    查询特定怪物的行动轴、机制弱点、致命技能与打法禁忌（例如：地精大块头忌技能牌、乐嘉维林睡眠对策）。
    """

    def __init__(self):
        self._dossiers: Dict[str, Any] = {}
        self._load_knowledge()

    def _load_knowledge(self):
        yaml_path = Path(__file__).parent.parent / "knowledge" / "monsters.yaml"
        if yaml_path.exists():
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    self._dossiers = yaml.safe_load(f) or {}
            except Exception as e:
                pass

    @property
    def name(self) -> str:
        return "lookup_monster_tactics"

    @property
    def description(self) -> str:
        return (
            "查询指定怪物的行动规律、特异技能机制以及高胜率战术禁忌。"
            "遇到精英怪 (如 GremlinNob, Lagavulin, Slavers) 或 Boss 时强烈推荐调用此工具，获取克制对策。"
        )

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "monster_id": {
                    "type": "string",
                    "description": "怪物的游戏 ID 或英文名，如 'GremlinNob', 'Lagavulin', 'Cultist', 'TheGuardian'",
                }
            },
            "required": ["monster_id"],
        }

    def execute(self, params: Dict[str, Any], context: Any = None) -> ToolResult:
        monster_id = params.get("monster_id", "").strip()

        # 1. 规范化函数（去除下划线、空格、特殊符号）
        def _norm(s: str) -> str:
            return "".join(c.lower() for c in s if c.isalnum())

        norm_id = _norm(monster_id)

        # 2. 匹配查找：Pass 1A 精确 Key 完美命中
        info = None
        for key, val in self._dossiers.items():
            if norm_id == _norm(key):
                info = val
                break

        # Pass 1B: 精确 Name / 别名完美命中
        if not info:
            for key, val in self._dossiers.items():
                norm_name = _norm(val.get("name", ""))
                aliases = [_norm(a) for a in val.get("aliases", [])]
                if norm_id == norm_name or norm_id in aliases:
                    info = val
                    break

        # Pass 2: 子串模糊匹配降级
        if not info:
            for key, val in self._dossiers.items():
                norm_key = _norm(key)
                norm_name = _norm(val.get("name", ""))
                aliases = [_norm(a) for a in val.get("aliases", [])]

                if (norm_key and norm_key in norm_id) or (norm_id and norm_id in norm_key):
                    info = val
                    break
                if (norm_name and norm_name in norm_id) or (norm_id and norm_id in norm_name):
                    info = val
                    break
                if any((a and a in norm_id) or (norm_id and norm_id in a) for a in aliases):
                    info = val
                    break

        if not info:
            return ToolResult(
                success=True,
                data={
                    "monster_id": monster_id,
                    "tip": "未收录该特异怪物的专有行动轴。请遵循常规战术：若怪物当前意图为高伤攻击则算满格挡；若为成长怪则尽快击杀。",
                },
            )

        return ToolResult(success=True, data=info)
