"""模型写入的结构合同；从既有状态领域/记录字段/Link方向生成，不保存事实。"""
from __future__ import annotations

from copy import deepcopy

from ..contracts.references import validate_position, validate_source_refs
from ..std.serialization import json_text

from .graph import ENDPOINTS, RECORD_FIELDS, RECORD_GROUPS
from .state import DOMAINS


# 留下模型字段的声明顺序；落盘身份及来源另由相应校验补充。
_STATE_OPERATIONS = {
    "set": (("local_ref", "entry"), ("entry_id", "entry")),
    "clear": (("entry_id",),),
}
_RECORD_OPERATIONS = {
    "create": (("local_ref", "record"),),
    "update": (("ref", "record"),),
    "retire": (("ref",),),
}
_RECORD_REQUIRED = ("record_kind", "payload")
_RECORD_PAYLOAD_REQUIRED = {
    kind: tuple(sorted(fields - {"explanation_candidates"})) for kind, fields in RECORD_FIELDS.items()
}
_LINK_ENDPOINT_FIELDS = ("subject_ref", "object_ref")


def _operation_fields(operations: dict) -> set[str]:
    """依赖：状态或记录操作声明。输入：操作及候选字段组。输出：可写字段集合。实现：收集各分支键，op由上层处理。"""
    return {name for branches in operations.values() for fields in branches for name in fields}


def _operation_alternatives(operations: dict, op: str) -> list[dict]:
    """依赖：操作声明。输入：操作及名称。输出：有序必需/禁用字段。实现：同组其他分支专用字段均不得混用。"""
    permitted = _operation_fields(operations)
    return [{"required": ["op", *fields], "forbidden": sorted(permitted - set(fields))}
            for fields in operations.get(op, ())]


def _operation_schema(operations: dict, properties: dict, description: str) -> dict:
    """依赖：同源操作候选字段。输入：操作、字段Schema及指导。输出：模型可见Schema。实现：生成op及互斥oneOf，保留属性和分支顺序。"""
    return {"type": "object", "properties": {"op": {"type": "string", "enum": list(operations)}, **properties},
            "required": ["op"], "additionalProperties": False, "description": description,
            "oneOf": [{"properties": {"op": {"enum": [op]}}, "required": alternative["required"],
                       "not": {"anyOf": [{"required": [key]} for key in alternative["forbidden"]]}}
                      for op in operations for alternative in _operation_alternatives(operations, op)]}


def _scope_errors(scope: object) -> list[str]:
    """依赖：GraphKey。输入：序列化scope。输出：字段错误。实现：严格形状后复用唯一身份类型，不重新实现标识符规则。"""
    from ..identity import GraphKey

    try:
        if not isinstance(scope, dict):
            raise ValueError("scope需要对象")
        GraphKey(**scope)
    except (ValueError, TypeError):
        return ["scope错误"]
    return []


def state_entry_schema() -> dict:
    """依赖：既有DOMAINS。输入：无。输出：状态及可选信息来源Schema。实现：value保留所得内容，摄取时点和文件来源仍由host绑定，不建立第二套知识表。"""
    information = {"channel": {"type": "string", "description": "开放自然语言渠道，须适合世界设定：学校课堂/教材/校内通知、报刊、电视/广播、网络/电话/短信、交谈/书信、公开公告/圈层档案、观察、传闻、合理推断或已成立能力；举例不是枚举限制。"},
                   "source": {"type": ["string", "null"], "description": "角色所认知的世界内来源标签；来源未知用null，不猜真名。不是DraftRef或文件引用。"},
                   "certainty": {"type": "string", "description": "角色的确定程度，如听闻未核实、推测、亲见局部；不认证世界真相。"},
                   "basis": {"type": "string", "description": "实际学习/阅读/收听/观看/接收的部分及依据：在场、感官、权限、地区/圈层覆盖、刊期/节目时点、设备信号、传递路径与内容限制。"}}
    return {"type": "object", "properties": {"domain": {"type": "string", "enum": sorted(DOMAINS)},
        "kind": {"type": "string", "description": "稳定类别；人物信息用knowledge/belief/claim/unknown，不把听闻或推测写成世界事实。"},
        "value": {"type": "string", "description": "本条实际所得内容或人物判断；转述只记说出的部分，不从作者全知补齐。"},
        "lifetime": {"type": "string", "enum": ["scene", "carry"]},
        "holder": {"anyOf": [{"type": "string"}, {"type": "object", "properties": {"local_ref": {"type": "string"}}, "required": ["local_ref"], "additionalProperties": False}]},
        "target": {"anyOf": [{"type": "string"}, {"type": "object", "properties": {"local_ref": {"type": "string"}}, "required": ["local_ref"], "additionalProperties": False}]}, "information": {"type": "object", "properties": information,
            "required": list(information), "additionalProperties": False,
            "description": "仅CharacterView可用；新信息应注明四项。旧条目省略表示未注明，不能补造来源/确定程度；获知位置由正文检查点绑定。"}},
        "required": ["domain", "kind", "value", "lifetime"], "additionalProperties": False,
        "description": "CharacterView须非空holder；World没有holder/target时省略，不传null。value为有效现状，承诺不是完成，群体成员/在场不自动产生知识。"
                       "recall/read_document返回的entry_id/source_refs/narrative_position/scene_id是host字段，不可整条回写；只提取本Schema可写字段，entry_id放在外层操作。"}


def validate_state_entry(entry: object, *, stored: bool = False) -> list[str]:
    """依赖：唯一state_entry_schema。输入：条目及是否落盘形状。输出：结构错误列表。实现：共用身份/信息检查，仅落盘容许既有host字段，拒绝未声明扩展，不判断正文或补造旧证据。"""
    if not isinstance(entry, dict):
        return ["state entry必须为对象"]
    schema, errors = state_entry_schema(), []
    allowed = set(schema["properties"])
    if stored:
        allowed.update({"entry_id", "source_refs", "narrative_position", "scene_id"})
        for name in ("entry_id", "source_refs", "narrative_position"):
            if name not in entry:
                errors.append(f"state entry.{name}缺失")
        if not isinstance(entry.get("entry_id"), str) or not entry.get("entry_id", "").strip():
            errors.append("state entry.entry_id必须为非空字符串")
        errors.extend(validate_source_refs(entry.get("source_refs")))
        errors.extend(validate_position(entry.get("narrative_position")))
    unknown = set(entry) - allowed
    if unknown:
        errors.append(f"state entry未知字段{sorted(str(key) for key in unknown)}；身份/时点/文件来源由host绑定")
    for name in schema["required"]:
        if name not in entry:
            errors.append(f"state entry.{name}缺失")
    for name, spec in schema["properties"].items():
        if name == "information" or name not in entry:
            continue
        value = entry[name]
        if name in {"holder", "target"} and not stored and isinstance(value, dict):
            if set(value) != {"local_ref"} or not isinstance(value.get("local_ref"), str) or not value["local_ref"].strip():
                errors.append(f"state entry.{name}需要非空local_ref")
            continue
        if not isinstance(value, str):
            errors.append(f"state entry.{name}必须为字符串")
        elif "enum" in spec and value not in spec["enum"]:
            errors.append(f"state entry.{name}超出允许范围")
        elif name in {"kind", "holder", "target"} and not value.strip():
            errors.append(f"state entry.{name}必须为非空字符串")
    if entry.get("domain") == "CharacterView" and not (isinstance(entry.get("holder"), str) or
            not stored and isinstance(entry.get("holder"), dict)):
        errors.append("CharacterView需要明确字符串holder")
    if "information" not in entry:
        return errors
    if entry.get("domain") != "CharacterView":
        errors.append("information仅供CharacterView使用")
    information = entry["information"]
    if not isinstance(information, dict):
        return errors + ["state entry.information必须为对象"]
    spec = schema["properties"]["information"]
    unknown = set(information) - set(spec["properties"])
    if unknown:
        errors.append(f"state entry.information未知字段{sorted(str(key) for key in unknown)}；时点与文件来源由host绑定")
    for name in spec["required"]:
        if name not in information:
            errors.append(f"state entry.information.{name}缺失")
            continue
        value = information[name]
        if value is None and "null" in spec["properties"][name]["type"]:
            continue
        if not isinstance(value, str) or not value.strip():
            errors.append(f"state entry.information.{name}必须为非空字符串" + ("或null" if name == "source" else ""))
    return errors


def draft_reference_schema() -> dict:
    """依赖：既有DraftRef字段合同。输入：无。输出：JSON Schema。实现：要求原样使用save_draft的完整引用，kind/版本/指纹可见，不推断来源。"""
    properties = {"kind": {"type": "string", "enum": ["draft"]}, "draft_document_id": {"type": "string"},
                  "draft_revision": {"type": "integer", "minimum": 1}, "content_hash": {"type": "string"},
                  "checkpoint_id": {"type": "string"}}
    return {"type": ["object", "null"], "properties": properties, "required": list(properties),
            "additionalProperties": False, "description": "原样复制save_draft返回的完整DraftRef；无正文只记作者计划/笔记时可省略或null。"}


def remember_update_examples() -> list[dict]:
    """依赖：既有状态操作合同。输入：无。输出：三次独立update样例。实现：给出新建/原槽更新/解除，唯一占位ID须以host回执替换，不构造来源或版本。"""
    return [
        {"state_changes": [{"op": "set", "local_ref": "gate-status", "entry": {
            "domain": "World", "kind": "gate_status", "value": "山门暂时关闭。", "lifetime": "carry"}}]},
        {"state_changes": [{"op": "set", "entry_id": "<返回的gate-status稳定ID>", "entry": {
            "domain": "World", "kind": "gate_status", "value": "山门已开放。", "lifetime": "carry"}}]},
        {"state_changes": [{"op": "clear", "entry_id": "<返回的gate-status稳定ID>"}]},
    ]


def remember_update_schema() -> dict:
    """依赖：状态/graph常量和同源样例。输入：无。输出：唯一update结构、操作分支及模型可见样例。实现：共用字段声明派生必需/禁用键，样例同时进入description，来源/CAS仍由MemoryService验证。"""
    endpoint = {"type": "object", "properties": {"kind": {"type": "string", "enum": ["entity", "state", *RECORD_FIELDS]},
        "id": {"type": "string"}, "local_ref": {"type": "string"}}, "additionalProperties": False,
        "description": "已有端点用真实kind+id；本批新端点只用local_ref，不能猜人物ID。"}
    field_schemas = {"title": {"type": "string"}, "text": {"type": "string"}, "nature": {"type": "string",
        "description": "已发生线索与author_plan区分；作者计划不能成为剧情事实。"},
        "explanation_candidates": {"type": "array", "items": {"type": "string"}},
        "relation_type": {"type": "string", "enum": list(ENDPOINTS)},
        **dict.fromkeys(_LINK_ENDPOINT_FIELDS, endpoint)}
    entry = state_entry_schema()
    properties = {"state_changes": {"type": "array", "items": _operation_schema(_STATE_OPERATIONS, {
        "local_ref": {"type": "string"}, "entry_id": {"type": "string"}, "entry": entry},
        "local_ref仅用于新set；更新set用已返回entry_id和完整可写entry，domain/kind/holder/target沿原身份；clear只用已返回entry_id。先recall读取原条目，只提取entry Schema字段，不猜ID或嵌入host字段。")},
        "scene_boundary": {"type": "string", "enum": ["begin_scene"]},
        "unresolved_entities": {"type": "array", "items": {"type": "object", "properties": {
            "local_ref": {"type": "string"}, "name": {"type": "string"}, "entity_type": {"type": "string"}},
            "required": ["local_ref", "name", "entity_type"], "additionalProperties": False},
            "description": "正文中新出现且尚无正式ID的身份。同名不合并；本批端点及holder/target可用local_ref，host返回稳定ID。"}}
    for group, kind in RECORD_GROUPS.items():
        payload_fields = {name: deepcopy(field_schemas[name]) for name in sorted(RECORD_FIELDS[kind])}
        record = {"type": "object", "properties": {"record_kind": {"type": "string", "enum": [kind]},
            "payload": {"type": "object", "properties": payload_fields, "required": list(_RECORD_PAYLOAD_REQUIRED[kind]), "additionalProperties": False},
            "source_refs": {"type": "array", "items": {"type": "object"},
                            "description": "默认用本次draft_ref；纯计划/笔记可原样复制上下文AuthorInputRef。"}},
            "required": list(_RECORD_REQUIRED), "additionalProperties": False}
        properties[group] = {"type": "array", "items": _operation_schema(_RECORD_OPERATIONS, {
            "local_ref": {"type": "string"},
            "ref": {"type": "object", "properties": {"kind": {"type": "string", "enum": [kind]}, "id": {"type": "string"}},
                    "required": ["kind", "id"], "additionalProperties": False}, "record": record},
            "create必须唯一local_ref和record；update必须真实ref和完整record；retire只需真实ref。")}
    examples = remember_update_examples()
    return {"type": "object", "properties": properties, "additionalProperties": False, "examples": examples,
        "description": "只写本批变化，不写累计摘要。经历文本在experiences[].record.payload.text，不是summary；record_kind必须小写。"
                       "以下是三次独立调用的update：新set→原ID更新→状态已结束时clear，按正文实际变化使用，不必凑齐步骤。"
                       "先save_draft；每次draft_ref原样取对应正文保存回执，expected_memory_revision取最新context/recall/remember回执。"
                       "将占位ID替换为首批local_ref_to_stable_id['gate-status']或recall返回的同一entry_id，不原样提交占位符。"
                       "更新仅提取entry Schema的可写字段，保留原domain/kind/holder/target；不能把回读整条entry写回。示例：" + json_text(examples) +
                       "。明确收到本次提交的校验拒绝（error.details中有实际issues或operations）后，修正参数须发起新调用，harness用新的operation_id。"
                       "仅ok:false或source_invalid不足以判断可改参重试；超时、断连等结果未知时，保留原operation_id和完整原参数查询或恢复原回执，不自动改参重发。"}


def _entity_errors(write: dict, path: str, *, stored: bool) -> list[str]:
    """依赖：身份字段/Ref及位置校验。输入：声明、下标路径和形状。输出：有序错误。实现：输入校验作者字段，落盘追加host身份与来源。"""
    errors = []
    fields = {"local_ref", "name", "entity_type"}
    host_fields = {"id", "scope", "source_refs", "narrative_position"} if stored else set()
    if fields | host_fields != write.keys():
        errors.append(path + ": 身份声明字段错误")
    for key in fields | ({"id"} if stored else set()):
        if not isinstance(write.get(key), str) or not write[key].strip():
            errors.append(path + "." + key + ": 需要非空字符串")
    if stored:
        errors.extend(path + "." + error for error in _scope_errors(write.get("scope")))
        errors.extend(path + ": " + error for error in validate_source_refs(write.get("source_refs")))
        errors.extend(path + ": " + error for error in validate_position(write.get("narrative_position")))
    return errors


def _payload_errors(payload: dict, path: str, kind: str, *, stored: bool) -> list[str]:
    """依赖：graph载荷字段/Link端点表。输入：载荷、操作路径、记录类型与形状。输出：有序字段及端点错误。实现：先检查键集合，然后按输入顺序查值与Link方向。"""
    errors = []
    missing = set(_RECORD_PAYLOAD_REQUIRED[kind]) - payload.keys()
    unknown = payload.keys() - RECORD_FIELDS[kind]
    if missing:
        errors.append(path + ".record.payload缺必需字段" + str(sorted(missing)))
    if unknown:
        errors.append(path + ".record.payload未知字段" + str(sorted(str(key) for key in unknown)))
    for name, value in payload.items():
        if not isinstance(name, str):
            errors.append(path + ".payload字段名必须为字符串")
        elif name in _LINK_ENDPOINT_FIELDS:
            concrete = isinstance(value, dict) and set(value) == {"kind", "id"} and all(
                isinstance(value[key], str) for key in ("kind", "id"))
            local = not stored and isinstance(value, dict) and set(value) == {"local_ref"} and isinstance(value["local_ref"], str)
            if not (concrete or local):
                errors.append(path + ".payload." + name + ": 端点错误")
        elif name == "explanation_candidates":
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                errors.append(path + ".payload.explanation_candidates必须为字符串数组")
        elif not isinstance(value, str):
            errors.append(path + ".payload." + name + "必须为字符串")
    if kind == "link":
        relation = payload.get("relation_type")
        if not isinstance(relation, str) or relation not in ENDPOINTS:
            errors.append(path + ".payload.relation_type错误")
        elif all(isinstance(payload.get(name), dict) and "kind" in payload[name] for name in _LINK_ENDPOINT_FIELDS):
            if any(not isinstance(payload[name]["kind"], str) or payload[name]["kind"] not in permitted
                   for name, permitted in zip(_LINK_ENDPOINT_FIELDS, ENDPOINTS[relation])):
                errors.append(path + ".payload.Link端点方向错误")
    return errors


def _record_errors(data: object, path: str, kind: str, operation_id: object, *, stored: bool) -> list[str]:
    """依赖：记录载荷/Ref及位置校验。输入：记录、操作路径、类型及落盘外层ID。输出：有序错误。实现：先核记录及载荷形状，再校来源与载荷字段。"""
    if not isinstance(data, dict):
        return [path + ".record需要包含record_kind和payload的对象"]
    if data.get("record_kind") != kind:
        return [path + ".record.record_kind必须为小写" + kind]
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return [path + ".record.payload必须是对象"]
    errors = []
    fields = {*_RECORD_REQUIRED, "source_refs"}
    if stored:
        fields.update({"id", "scope", "narrative_position"})
    if data.keys() - fields:
        errors.append(path + ".record存在未知字段")
    if stored:
        errors.extend(path + ".record." + error for error in _scope_errors(data.get("scope")))
        if data.get("id") != operation_id:
            errors.append(path + ": 内外record ID不一致")
        if "narrative_position" not in data:
            errors.append(path + ".record.narrative_position缺失")
        errors.extend(path + ": " + error for error in validate_position(data.get("narrative_position")))
    if stored or "source_refs" in data and data["source_refs"] != []:
        errors.extend(path + ": " + error for error in validate_source_refs(data.get("source_refs")))
    errors.extend(_payload_errors(payload, path, kind, stored=stored))
    return errors


def _input_identity_errors(write: dict, path: str, kind: str | None, *, creates: bool) -> list[str]:
    """依赖：新增/既有身份合同。输入：操作、原路径、记录种类及是否允许新建。输出：具体身份错误。实现：分清local_ref、状态ID及记录Ref，保留历史允许的Ref形状。"""
    identity_field = "entry_id" if kind is None else "ref"
    if creates and "local_ref" in write:
        local_ref = write["local_ref"]
        if not isinstance(local_ref, str) or not local_ref.strip() or identity_field in write:
            return [path + ": 新记录local_ref错误或混用ID"]
    elif kind is None:
        entry_id = write.get(identity_field)
        if not isinstance(entry_id, str) or not entry_id.strip():
            return [path + ".entry_id缺失"]
    else:
        ref = write.get(identity_field)
        if not isinstance(ref, dict) or set(ref) != {"kind", "id"} or ref.get("kind") != kind or not isinstance(ref.get("id"), str):
            return [path + ".ref错误"]
    return []


def _operation_errors(write: dict, path: str, kind: str | None, *, stored: bool) -> list[str]:
    """依赖：共同操作声明及身份/值校验。输入：操作、原路径、可选记录种类和形状。输出：有序错误。实现：先查分支和身份，再查解除来源、状态或记录。"""
    state = kind is None
    operations = _STATE_OPERATIONS if state else _RECORD_OPERATIONS
    op = write.get("op")
    if not isinstance(op, str) or op not in operations:
        return [path + ".op错误"]
    variants = operations[op]
    permitted = _operation_fields(operations)
    supplied = write.keys()
    errors = []
    branch_fields = permitted & supplied
    if not stored and sum(set(fields) == branch_fields for fields in variants) != 1:
        errors.append(path + ": 操作必需字段缺失或混用新建/更新/解除字段，请按声明选择一个分支")
    unknown = supplied - permitted - {"op"}
    if stored:
        unknown -= {"source_refs", "id"}
    if unknown:
        errors.append(path + ": 未知操作字段")
    id_field = "entry_id" if state else "id"
    operation_id = write.get(id_field)
    if stored:
        if not isinstance(operation_id, str) or not operation_id.strip():
            errors.append(path + "." + id_field + "缺失")
    else:
        errors.extend(_input_identity_errors(write, path, kind, creates=any("local_ref" in fields for fields in variants)))
    value_field = "entry" if state else "record"
    if not any(value_field in fields for fields in variants):
        if {"entry", "record"} & supplied:
            errors.append(path + ": 解除操作不能携带新值")
        if stored:
            errors.extend(path + ": " + error for error in validate_source_refs(write.get("source_refs")))
    elif state:
        entry = write.get(value_field)
        errors.extend(path + ".entry: " + error for error in validate_state_entry(entry, stored=stored))
        if stored and isinstance(entry, dict) and entry.get("entry_id") != operation_id:
            errors.append(path + ": 内外entry_id不一致")
    else:
        errors.extend(_record_errors(write.get(value_field), path, kind, operation_id, stored=stored))
    return errors


def validate_memory_update(update: object, *, stored: bool = False) -> list[str]:
    """依赖：graph组/共同操作规则。输入：模型或落盘update。输出：按原路径顺序的错误。实现：校验组和列表边界，逐项委托身份声明或操作校验。"""
    if not isinstance(update, dict):
        return ["update必须为对象"]
    errors = []
    allowed = set(RECORD_GROUPS) | {"state_changes", "scene_boundary", "unresolved_entities"}
    if update.keys() - allowed:
        errors.append("update存在未知组")
    for group, writes in update.items():
        if group not in allowed:
            continue
        if group == "scene_boundary":
            valid = (isinstance(writes, dict) and set(writes) == {"kind", "scene_id"} and
                     writes.get("kind") == "begin_scene" and isinstance(writes.get("scene_id"), str)) if stored else writes == "begin_scene"
            if not valid:
                errors.append("update.scene_boundary字段错误")
            continue
        if not isinstance(writes, list):
            errors.append(f"update.{group}必须为数组")
            continue
        for index, write in enumerate(writes):
            path = f"update.{group}[{index}]"
            if not isinstance(write, dict):
                errors.append(path + "必须为对象")
            elif group == "unresolved_entities":
                errors.extend(_entity_errors(write, path, stored=stored))
            else:
                errors.extend(_operation_errors(write, path, RECORD_GROUPS.get(group), stored=stored))
    return errors


def memory_update_guidance(update: object, message: str = "") -> dict:
    """依赖：共同校验/操作字段。输入：失败差分及原错误。输出：字段问题、最小合法形状和只读动作。实现：只为报错下标派生候选分支和原ID读取入口。"""
    issues = validate_memory_update(update)
    result = {"issues": issues, "operations": []}
    if not isinstance(update, dict):
        return result
    for group, writes in update.items():
        kind = RECORD_GROUPS.get(group)
        if (kind is None and group != "state_changes") or not isinstance(writes, list):
            continue
        operations = _STATE_OPERATIONS if kind is None else _RECORD_OPERATIONS
        for index, write in enumerate(writes):
            path = f"update.{group}[{index}]"
            if not isinstance(write, dict) or not any(path in error for error in [*issues, message]):
                continue
            op = write.get("op")
            operation = {"path": path, "alternatives": _operation_alternatives(operations, op) if isinstance(op, str) else []}
            if kind is not None:
                operation.update(record_required=list(_RECORD_REQUIRED), record_kind=kind,
                                 payload_required=list(_RECORD_PAYLOAD_REQUIRED[kind]))
            else:
                operation["entry_required"] = state_entry_schema()["required"]
            ref = write.get("ref")
            identity = write.get("entry_id") or (ref.get("id") if isinstance(ref, dict) else None)
            if isinstance(identity, str) and identity.strip():
                operation["read_before_update"] = {"tool": "recall", "arguments": {"focus": [identity]}}
            result["operations"].append(operation)
    return result


def validate_stored_batch(batch: object) -> list[str]:
    """依赖：共同update/Ref/位置校验。输入：StoredMemoryBatch。输出：完整落盘形状错误。实现：检查批次头及host必需字段后委托同一纯结构owner。"""
    if not isinstance(batch, dict):
        return ["memory batch必须为对象"]
    errors = []
    if not isinstance(batch.get("update"), dict) or not isinstance(batch.get("source_refs"), list):
        errors.append("memory batch需要update映射及source_refs列表")
    if set(batch) - {"batch_id", "memory_revision", "source_refs", "narrative_position", "update", "draft_ref"}:
        errors.append("memory batch存在未知字段；可见性/隔离标记只由reader派生")
    for key in ("batch_id", "memory_revision", "source_refs", "narrative_position", "update"):
        if key not in batch:
            errors.append("memory batch." + key + "缺失")
    if not isinstance(batch.get("batch_id"), str) or not batch.get("batch_id", "").strip():
        errors.append("memory batch.batch_id必须为非空字符串")
    if type(batch.get("memory_revision")) is not int or batch.get("memory_revision", -1) < 0:
        errors.append("memory batch.memory_revision必须为非负整数")
    errors.extend(validate_source_refs(batch.get("source_refs")))
    if batch.get("draft_ref") is not None:
        errors.extend(validate_source_refs([batch["draft_ref"]]))
    errors.extend(validate_position(batch.get("narrative_position")))
    errors.extend(validate_memory_update(batch.get("update"), stored=True))
    return errors
