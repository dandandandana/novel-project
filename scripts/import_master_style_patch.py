from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "novel-rag"
SHARED = LIBRARY / "shared"
STYLE_ACTIVE = SHARED / "style-audit" / "active"
STYLE_DEPRECATED = SHARED / "style-audit" / "deprecated"
VERSION_MAP = SHARED / "registry" / "version-map.yaml"
MODULE_DEFAULTS = SHARED / "registry" / "module-defaults.yaml"
RETRIEVAL_TESTS = (
    LIBRARY / "stories" / "overturned-world-fujimaru" / "retrieval-tests.yaml"
)
SOURCE = Path(r"D:\project\文风补丁.txt")

TODAY = "2026-07-26"
SOURCE_REF = "D:/project/文风补丁.txt"
OLD_MASTER_ID = "style-master-patch-v1.0"
NEW_MASTER_ID = "style-master-patch-v2.0"
OLD_MANIFEST_ID = "style-global-manifest-v1.3"
NEW_MANIFEST_ID = "style-global-manifest-v1.4"


class LiteralString(str):
    pass


class Dumper(yaml.SafeDumper):
    pass


def _represent_literal(dumper: Dumper, value: LiteralString) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(value), style="|")


Dumper.add_representer(LiteralString, _represent_literal)


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.dump(
        data,
        Dumper=Dumper,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    path.write_text(rendered, encoding="utf-8", newline="\n")


def upsert_by_key(rows: list[dict[str, Any]], key: str, value: dict[str, Any]) -> None:
    for index, row in enumerate(rows):
        if row.get(key) == value.get(key):
            rows[index] = value
            return
    rows.append(value)


def archive_current(path: Path, expected_id: str, archive_path: Path) -> None:
    current = load_yaml(path)
    document_id = current.get("metadata", {}).get("document_id")
    if document_id == expected_id:
        archived = deepcopy(current)
        archived["metadata"]["status"] = "deprecated"
        archived["metadata"]["updated_at"] = TODAY
        write_yaml(archive_path, archived)


def build_master_patch(source_text: str, source_hash: str) -> dict[str, Any]:
    return {
        "metadata": {
            "document_id": NEW_MASTER_ID,
            "story_id": "__shared__",
            "timeline_id": "global",
            "document_type": "style_audit",
            "module_type": "style",
            "title": "对话、旁白与场景叙事总文风协议",
            "audit_scope": "global_module",
            "scene_type": "all",
            "module_id": "master-patch",
            "priority": "highest",
            "enforcement": "mandatory",
            "version": "2.0",
            "status": "active",
            "created_at": "2026-07-12",
            "updated_at": TODAY,
            "supersedes": OLD_MASTER_ID,
            "source_file": SOURCE_REF,
            "source_sha256": source_hash,
        },
        "style_rules": {
            "activation": "active",
            "retrieval_keys": [
                "master_style_patch_v2 dialogue_narration_scene_protocol",
                "live_character_motivation relationship_authenticity natural_dialogue",
                "scene_contract information_admission reader_inference_protection",
                "anti_ai_dialogue ending_evidence_restatement survival_audit",
            ],
            "priority": "highest",
            "enforcement": "mandatory",
            "scope": "global",
            "protocol_versions": {
                "dialogue_and_narration": "0.7",
                "scene_structure_and_information_admission": "0.5",
                "reader_inference_and_ending": "0.1",
            },
            "external_authority_order": [
                "用户当前明确要求",
                "大纲、Canon、History、State 与 Ruler 的事实和硬约束",
                "本总文风协议",
                "更具体且不与总文风冲突的场景专项文风",
                "其他全局文风模块",
            ],
            "internal_style_order": [
                "角色此刻的说话或行动动机",
                "角色与对方的具体关系",
                "活人能够自然说出口或做出的反应",
                "信息清楚",
                "人物设定自然泄露",
                "语言美感",
            ],
            "core_contract": [
                "人物塑造是行动、选择、习惯、区别对待、回避和交流失误的副作用，不是角色当前任务",
                "每个完整场景只完成一个主要变化；变化成立后尽快以行动、决定或新问题收束",
                "设定、背景、能力和历史只有在改变当前判断、选择、主动权或行动方案时才准入",
                "整轮交流需要产生信息、关系、情绪、角色声音或行动后果，单句对白不必逐句高效",
                "旁白负责清楚呈现事实、误判和交流结果，不重复解释台词，不宣布抽象气质",
                "读者已经能够推断的关系、情感和善恶结论不在场景末尾重新归纳",
            ],
            "adapters": {
                "ruler": [
                    "本补丁只裁决文风冲突，不覆盖当前用户要求、剧情硬节点、事实优先级和信息权限边界",
                    "活人感不是可删除噪音；只删除不属于具体角色、关系、行动或场景限制的通用填充",
                ],
                "judgment": [
                    "为每个完整场景确定开始状态、主要矛盾、唯一主要变化、最低必要信息、暂缓信息和终点",
                    "确定一个主要场景类型；局部次类型只改变当前话轮，不反复重置整场结构",
                    "将信息分为本场必须出现、可以只露一部分、暂时不出现三档",
                    "为描写单元分配一至两个参与行动、关系、判断、冲突或伏笔的有效锚点",
                ],
                "generator": [
                    "先写人物行动和当下目标，再写对话与信息差、关系后果、必要设定，最后才是环境与修饰",
                    "对白毛刺、打断、改口、迟到反应和接话失败必须有动机、关系或交流后果",
                    "战斗动作尽快抵达伤害、位置、资源或战术结果；功能对话保持信息连续；日常允许有归属的低信息废话",
                    "到达场景终点后停止，不追加人设证明、能力说明、关系总结、氛围空镜或阅读理解式收束",
                ],
                "audit": [
                    "先查场景主要变化、信息准入和人物行动，再查对白、描写密度、标点和句词",
                    "删除同义身体反应、零结果动作、无作用感官、伪深度句和已经由正文表现出的结论",
                    "若交流不像活人或换谁都能说，应重写整轮交流，不能只补语气词、停顿、动作或口癖",
                    "场景结尾最多回收一个旧锚点，并让它改变下一步行动；旧证据重组不算新信息",
                ],
            },
            "scene_type_dispatch": {
                "battle": "结果、位置、伤害、视野、资源与战术变化优先",
                "functional_dialogue": "信息清楚、保留信息差、减少无关动作，允许问题未被完整回答",
                "relationship_dialogue": "角色私有性、区别对待、边界和潜台词优先，允许有归属的废话",
                "daily": "建立生活状态和关系习惯，不强推主线，不用感官堆砌伪造治愈感",
                "emotional_break": "允许失衡、重复和说错，但不完整播报心理理论",
                "confession": "坦白造成选择或关系后果，不一次回收全部往事",
                "intimacy": "身体反馈服务接受、迟疑、索取、退让和停止，不替代人物选择",
                "confrontation": "明确追问、回避、定义权和主动权变化，不把双方写成轮流发表论文",
                "parting": "用递还、收下、放手、跟上、离开或没有追承载结果",
                "transition": "只交代时间、地点、行动、必要状态和下一场直接相关的异常",
            },
            "compatibility": {
                "native-chinese-dialogue": "补充中文母语语气、接话连续性和翻译腔修正；本补丁控制动机、关系与交流失败",
                "scene-classifier": "沿用其场景识别结果，但以一个完整场景一个主要类型和一个主要变化为上限",
                "information-filter": "沿用存在性废话和信息边界检查，并新增信息准入、同义反复与旧证据重组裁剪",
                "action-continuity": "沿用动作因果链，但零结果动作和无后果慢动作必须删除",
                "battle": "沿用战斗专项强度与声场规则，但攻击必须尽快产生可观察结果",
                "punctuation": "沿用中文标点规范；破折号、省略号、单句段不得机械制造文艺节奏",
                "narration-voice": "旁白保持清楚与视角权限，不使用抽象气质宣布或重复解释台词",
            },
            "content": LiteralString(source_text.rstrip() + "\n"),
        },
        "audit_checks": {
            "must_verify": [
                "角色说话和行动首先服务当前动机，而不是主动证明人设",
                "角色措辞、拒绝、道歉、回避、玩笑和关心方式具有角色私有性",
                "整轮交流产生关系、情绪、角色声音、事实、误判、主动权或行动后果之一",
                "允许误解、答错重点、迟到反应、话题残留和接话失败，但读者仍能判断交流停在哪里",
                "打断争夺说话权、解释权、话题、时间、注意力或关系边界，并影响后续交流",
                "旁白没有重复解释台词、宣布抽象气质或替读者总结潜台词",
                "每个完整场景只有一个主要变化，且终点后没有继续补写总结和氛围",
                "设定和能力只释放当前行动所需部分，没有人物卡式验收或说明书化",
                "环境和感官参与行动、关系、判断、伏笔、身体限制或场景结果",
                "同一种情绪或身体状态只保留一至两个最具体且有后果的证据",
                "不同场景类型使用对应的信息、对白、动作和描写预算",
                "场景结尾没有重新列举旧证据并宣布关系、情感或善恶结论",
                "最终正文只输出正文，不附带场景契约、规则分析和人物塑造总结",
            ],
            "rewrite_required_when": [
                "人物为了证明聪明、温柔、毒舌、深情、冷静或强大而发表说明",
                "所有角色共享改口、反问、冷幽默、语气词、精准观察或情感咨询师式表达",
                "一问一答过度整齐，问题总被立即完整回答，双方轮流发表完整论点",
                "每句对白都承担金句、信息、关系升级和人物塑造，缺少普通回应或交流失误",
                "环境、光影、呼吸、眼神、衣料和微声只用于气氛，没有改变行动或判断",
                "能力已经通过结果表现，随后又被角色解释并由旁白总结",
                "同一受伤、疲惫或情绪状态被多种身体反应重复证明",
                "场景主要变化完成后仍追加价值观、历史、关系总结或象征性空镜",
                "结尾以旧证据清单、伪深度句或阅读理解式总结替读者下结论",
                "毛刺、打断、单句段、破折号或省略号删除后不影响动机、关系和交流结果",
            ],
            "prohibited_fixes": [
                "不得只添加语气词、口癖、停顿、改口和动作描写来伪造活人感",
                "不得为追求信息效率删除属于具体角色关系的废话、旧梗、回避和失败交流",
                "不得以文风优化为由改变大纲结果、事实、角色知识边界或 Judgment 节点主次",
                "不得为了完整感在场景结尾重述已经表现出的关系与情绪",
            ],
            "completion_criteria": [
                "场景变化可用一句具体行动结果概括",
                "人物、关系、信息和环境均通过当前行动自然显露",
                "删除冗余后仍保留角色私有性和必要生活感",
                "结尾停在行动、决定、新问题或未解决关系残留上",
            ],
        },
    }


def upgrade_master_patch(source_text: str, source_hash: str) -> None:
    active_path = STYLE_ACTIVE / "master-patch.yaml"
    current = load_yaml(active_path)
    current_id = current.get("metadata", {}).get("document_id")
    if current_id not in {OLD_MASTER_ID, NEW_MASTER_ID}:
        raise ValueError(f"unexpected master patch version: {current_id}")
    archive_current(
        active_path,
        OLD_MASTER_ID,
        STYLE_DEPRECATED / "master-patch-v1.0.yaml",
    )
    write_yaml(active_path, build_master_patch(source_text, source_hash))


def upgrade_manifest() -> None:
    path = STYLE_ACTIVE / "manifest.yaml"
    manifest = load_yaml(path)
    current_id = manifest.get("metadata", {}).get("document_id")
    if current_id not in {OLD_MANIFEST_ID, NEW_MANIFEST_ID}:
        raise ValueError(f"unexpected style manifest version: {current_id}")
    archive_current(
        path,
        OLD_MANIFEST_ID,
        STYLE_DEPRECATED / "manifest-v1.3.yaml",
    )
    manifest["metadata"].update(
        {
            "document_id": NEW_MANIFEST_ID,
            "module_type": "style",
            "priority": "highest",
            "enforcement": "mandatory",
            "version": "1.4",
            "status": "active",
            "updated_at": TODAY,
            "supersedes": OLD_MANIFEST_ID,
            "source_file": SOURCE_REF,
        }
    )
    audit = manifest["audit"]
    audit["retrieval_key"] = "style_global_manifest_v1_4 master_style_patch_v2_active"
    audit["resolution_order"] = [
        "用户当前明确要求与事实硬约束",
        "正常、清楚、可读的叙事",
        "对话、旁白与场景叙事总文风协议（highest）",
        "当前场景类型专项规则",
        "角色私有性、关系真实性与中文母语感",
        "其他全局文风模块",
    ]
    modules = audit["active_modules"]
    upsert_by_key(
        modules,
        "module_id",
        {
            "module_id": "master-patch",
            "document_id": NEW_MASTER_ID,
            "title": "对话、旁白与场景叙事总文风协议",
            "scope": "global",
            "priority": "highest",
            "enforcement": "mandatory",
            "version": "2.0",
        },
    )
    audit["integration_notes"] = [
        "master-patch 负责总优先级、场景契约、信息准入、活人对白、叙事密度和结尾推理空间",
        "native-chinese-dialogue 继续负责中文母语表达与翻译腔修正，不覆盖角色当下动机和关系边界",
        "scene-classifier、battle、action-continuity 等专项模块只在当前场景适用，并服从总文风的一场一变化和结果准入",
        "总文风不覆盖大纲硬节点、Canon、History、State、Ruler 权限和 Judgment 已确定的主次",
    ]
    audit["conflict_rule"] = (
        "用户当前要求、事实与信息权限优先；文风内部冲突时，以角色当下动机、具体关系、正常可读性和"
        "master-patch 为准。更具体的场景模块可以细化执行，但不得恢复人设证明、设定倾倒、零结果描写、"
        "统一口语模板或复述式结尾。"
    )
    write_yaml(path, manifest)


def update_version_map() -> None:
    data = load_yaml(VERSION_MAP)
    versions = data.setdefault("versions", [])
    upsert_by_key(
        versions,
        "document_family",
        {
            "document_family": "style-master-patch",
            "current": NEW_MASTER_ID,
            "supersedes": [OLD_MASTER_ID],
            "reason": "导入并适配用户确认的对话、旁白、场景结构、信息准入与读者推理保护总文风补丁",
        },
    )
    upsert_by_key(
        versions,
        "document_family",
        {
            "document_family": "style-global-manifest",
            "current": NEW_MANIFEST_ID,
            "supersedes": [
                OLD_MANIFEST_ID,
                "style-global-manifest-v1.2",
                "style-global-manifest-v1.1",
                "style-global-manifest-v1.0",
            ],
            "reason": "启用总文风 V2 并登记其与对白、场景、动作、信息过滤和结尾审计模块的适配关系",
        },
    )
    write_yaml(VERSION_MAP, data)


def update_style_manifest_references() -> None:
    paths = [MODULE_DEFAULTS]
    paths.extend((LIBRARY / "stories").glob("*/registry/module-map.yaml"))
    for path in paths:
        if not path.exists():
            continue
        data = load_yaml(path)
        changed = False
        for module in data.get("modules", []):
            if module.get("module_type") != "style_audit":
                continue
            active_versions = module.get("active_versions", [])
            replaced = [
                NEW_MANIFEST_ID if version == OLD_MANIFEST_ID else version
                for version in active_versions
            ]
            if replaced != active_versions:
                module["active_versions"] = replaced
                changed = True
        if changed:
            write_yaml(path, data)


def retrieval_case(
    case_id: str,
    query: str,
    expected_id: str,
    forbidden_ids: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": case_id,
        "story_id": "overturned-world-fujimaru",
        "timeline_id": "main",
        "query": query,
        "document_types": ["style_audit"],
        "expected_document_ids": [expected_id],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "timeline_isolation", "version", "content_type"],
    }
    if forbidden_ids:
        result["forbidden_document_ids"] = forbidden_ids
    return result


def update_retrieval_tests() -> None:
    data = load_yaml(RETRIEVAL_TESTS)
    tests = data.setdefault("tests", [])
    cases = [
        retrieval_case(
            "style-master-patch-v2-key",
            "master_style_patch_v2 dialogue_narration_scene_protocol",
            NEW_MASTER_ID,
            [OLD_MASTER_ID],
        ),
        retrieval_case(
            "style-master-patch-character-motivation",
            "角色当下反应 关系真实感 信息效率 人设展示",
            NEW_MASTER_ID,
            [OLD_MASTER_ID],
        ),
        retrieval_case(
            "style-master-patch-scene-contract",
            "每个完整场景只能有一个主要变化",
            NEW_MASTER_ID,
            [OLD_MASTER_ID],
        ),
        retrieval_case(
            "style-master-patch-reader-inference",
            "禁止证据回收清单",
            NEW_MASTER_ID,
            [OLD_MASTER_ID],
        ),
        retrieval_case(
            "style-global-manifest-v1-4",
            "style_global_manifest_v1_4 master_style_patch_v2_active",
            NEW_MANIFEST_ID,
            [OLD_MANIFEST_ID],
        ),
    ]
    for case in cases:
        upsert_by_key(tests, "id", case)
    write_yaml(RETRIEVAL_TESTS, data)


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    source_text = SOURCE.read_text(encoding="utf-8")
    source_hash = sha256(source_text.encode("utf-8")).hexdigest()
    upgrade_master_patch(source_text, source_hash)
    upgrade_manifest()
    update_style_manifest_references()
    update_version_map()
    update_retrieval_tests()
    print(f"master_patch={NEW_MASTER_ID}")
    print(f"style_manifest={NEW_MANIFEST_ID}")
    print(f"source_sha256={source_hash}")


if __name__ == "__main__":
    main()
