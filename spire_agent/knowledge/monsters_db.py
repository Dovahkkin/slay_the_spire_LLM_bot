"""
尖塔怪物战术情报知识库与动态 RAG 注入工具 (KV-Cache 友好架构)
- 本地静态加载并持久化 monsters.yaml；
- 随战场存活怪物动态监测、去重提取机制与战术禁忌；
- 采用规范字典序排序与高密度静态描述，最大化服务端 Prompt KV Cache 前缀命中率。
"""

from typing import Dict, Any, Optional, List, Set
from pathlib import Path
import re
import yaml
from ..models import Monster

_DOSSIERS_CACHE: Optional[Dict[str, Any]] = None


def load_monsters_knowledge() -> Dict[str, Any]:
    """懒加载并常驻内存 monsters.yaml 知识库"""
    global _DOSSIERS_CACHE
    if _DOSSIERS_CACHE is not None:
        return _DOSSIERS_CACHE

    yaml_path = Path(__file__).parent / "monsters.yaml"
    if yaml_path.exists():
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                _DOSSIERS_CACHE = yaml.safe_load(f) or {}
        except Exception:
            _DOSSIERS_CACHE = {}
    else:
        _DOSSIERS_CACHE = {}
    return _DOSSIERS_CACHE


def _norm(s: str) -> str:
    """归一化字符串：移除标点空格并转小写"""
    return "".join(c.lower() for c in s if c.isalnum()) if s else ""


def lookup_monster_dossier(raw_id: str, raw_name: str = "") -> Optional[Dict[str, Any]]:
    """
    根据怪物 ID 或名称精准检索知识库战术档案
    支持 Pass 1A 精确 Key、Pass 1B 精确 Name/别名、Pass 2 子串模糊命中
    """
    dossiers = load_monsters_knowledge()
    if not dossiers:
        return None

    norm_id = _norm(raw_id)
    norm_name = _norm(raw_name)

    # 1. 精确命中匹配 (优先 raw_id，其次 raw_name)
    for target in [norm_id, norm_name]:
        if not target:
            continue
        # Pass 1A: Key 完美匹配
        for key, val in dossiers.items():
            if target == _norm(key):
                return val
        # Pass 1B: Name / Aliases 完美匹配
        for key, val in dossiers.items():
            if target == _norm(val.get("name", "")):
                return val
            aliases = [_norm(a) for a in val.get("aliases", [])]
            if target in aliases:
                return val

    # 2. 子串模糊降级 (如 SpikeSlime_L 匹配 SpikeSlime, GremlinWizard 匹配 Gremlin Wizard)
    for target in [norm_id, norm_name]:
        if not target:
            continue
        for key, val in dossiers.items():
            k_norm = _norm(key)
            n_norm = _norm(val.get("name", ""))
            if (k_norm and k_norm in target) or (n_norm and n_norm in target):
                return val
            for a in val.get("aliases", []):
                a_norm = _norm(a)
                if a_norm and a_norm in target:
                    return val

    return None


# 常见召唤物或分裂衍生怪集合（用于标记特异警报）
SUMMON_OR_SPAWN_KEYWORDS = {
    "dagger", "torchhead", "bronzeorb", "spikeslimes", "acidslimes", "spikeslimem", "acidslimem"
}


def format_monster_dossiers(alive_monsters: List[Monster]) -> List[str]:
    """
    针对当前存活怪物生成高密度、KV-Cache 友好的机制战术警报卡片：
    - 按怪物规范 ID 自动去重 (避免 3 只邪教徒或 3 个哨兵重复膨胀)；
    - 按确定性字母序字典序排序 (确保只要存活怪集合不变，生成的 Token 序列 100% 字节级一致，最大化命中 KV Cache)；
    - 仅保留不变的核心机制 (key_mechanics) 与致命战术禁忌 (tactics)，变动的血量/格挡放在 ENEMIES 列表中，绝不在此反复震荡；
    - 识别召唤物/衍生怪并在前面添加高亮提示。
    """
    if not alive_monsters:
        return []

    # 1. 去重提取存活怪物的战术条目
    seen_keys: Set[str] = set()
    matched_entries: List[Dict[str, Any]] = []

    for m in alive_monsters:
        dossier = lookup_monster_dossier(m.id, m.name)
        if not dossier:
            continue
        # 使用规范化名称作为去重 Key
        canonical_name = dossier.get("name", m.name)
        norm_key = _norm(canonical_name)
        if norm_key in seen_keys:
            continue
        seen_keys.add(norm_key)

        is_summon = any(kw in _norm(m.id) or kw in _norm(m.name) for kw in SUMMON_OR_SPAWN_KEYWORDS)
        matched_entries.append({
            "name": canonical_name,
            "danger": dossier.get("danger_level", "Medium"),
            "threat_type": dossier.get("threat_type", ""),
            "mechanics": dossier.get("key_mechanics", "").strip().replace("\n", " "),
            "tactics": dossier.get("tactics", "").strip().replace("\n", " "),
            "is_summon": is_summon,
        })

    if not matched_entries:
        return []

    # 2. 关键：按名称进行确定性字母排序 (保证 Prompt 前缀绝对稳定，最大化命中服务端 KV Cache)
    matched_entries.sort(key=lambda x: x["name"])

    # 3. 组装高密度警示块
    lines: List[str] = []
    for entry in matched_entries:
        summon_tag = "⚠️ [SUMMON/SPAWN] " if entry["is_summon"] else ""
        threat_tag = f" | Threat: {entry['threat_type']}" if entry['threat_type'] else ""
        lines.append(f"- {summon_tag}[{entry['name']}] (Danger: {entry['danger']}{threat_tag}):")
        if entry["mechanics"]:
            lines.append(f"  * MECHANICS: {entry['mechanics']}")
        if entry["tactics"]:
            lines.append(f"  * TACTICS: {entry['tactics']}")

    return lines
