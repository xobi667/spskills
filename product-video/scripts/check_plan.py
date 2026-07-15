#!/usr/bin/env python3
"""Validate a natural, category-routed product-video plan before generation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any


ANCHOR_IDS = tuple("{:02d}".format(index) for index in range(1, 7))
SEGMENT_IDS = tuple("{:02d}".format(index) for index in range(1, 6))
ANCHOR_PHASES = {
    "01": "need",
    "02": "ready",
    "03": "aligned",
    "04": "applied",
    "05": "verified",
    "06": "resumed",
}
EXPECTED_JOBS = {
    "01": "daily_trigger",
    "02": "prepare",
    "03": "apply",
    "04": "verify",
    "05": "return",
}

ROUTE_ACTIONS = {
    "window_textile": {
        "reach", "measure", "align", "draw", "hang", "press_frame", "roll",
        "settle", "inspect", "open_close", "resume_use",
    },
    "window_film": {
        "clean", "measure", "peel", "spray", "align", "squeegee", "trim",
        "press_edge", "roll_unroll", "inspect", "resume_use",
    },
    "adhesive_decal": {
        "clean", "select", "peel", "align", "press", "smooth", "inspect",
        "resume_use",
    },
    "small_label": {
        "select", "peel", "align", "press", "smooth", "inspect", "pack", "retrieve",
        "resume_use",
    },
    "sealing_film": {
        "load_roll", "place_cup", "align_film", "feed", "press_seal", "release",
        "inspect", "handover",
    },
    "surface_covering": {
        "clear_surface", "measure", "unfold", "align", "smooth", "trim",
        "inspect", "place_items", "resume_use",
    },
    "seasonal_decor": {
        "choose_position", "clean", "peel", "hang", "align", "press", "secure",
        "inspect", "resume_use",
    },
    "fallback_household": {
        "pick_up", "prepare", "align", "place", "attach", "operate", "inspect",
        "resume_use",
    },
}
ROUTE_PHASE_ACTIONS = {
    "window_textile": {
        "daily_trigger": {"reach", "measure"},
        "prepare": {"measure", "align"},
        "apply": {"draw", "hang", "press_frame", "roll", "open_close"},
        "verify": {"settle", "inspect", "open_close"},
        "return": {"resume_use"},
    },
    "window_film": {
        "daily_trigger": {"clean", "measure"},
        "prepare": {"clean", "measure", "peel", "spray", "align"},
        "apply": {"squeegee", "trim", "press_edge", "roll_unroll"},
        "verify": {"inspect", "roll_unroll"},
        "return": {"resume_use"},
    },
    "adhesive_decal": {
        "daily_trigger": {"clean", "select"},
        "prepare": {"select", "peel", "align"},
        "apply": {"press", "smooth"},
        "verify": {"inspect"},
        "return": {"resume_use"},
    },
    "small_label": {
        "daily_trigger": {"select"},
        "prepare": {"peel", "align"},
        "apply": {"press", "smooth"},
        "verify": {"inspect", "retrieve"},
        "return": {"pack", "retrieve", "resume_use"},
    },
    "sealing_film": {
        "daily_trigger": {"load_roll", "place_cup"},
        "prepare": {"load_roll", "place_cup", "align_film", "feed"},
        "apply": {"press_seal"},
        "verify": {"release", "inspect"},
        "return": {"handover"},
    },
    "surface_covering": {
        "daily_trigger": {"clear_surface"},
        "prepare": {"measure", "unfold", "align"},
        "apply": {"unfold", "smooth", "trim"},
        "verify": {"inspect", "place_items"},
        "return": {"place_items", "resume_use"},
    },
    "seasonal_decor": {
        "daily_trigger": {"choose_position", "clean"},
        "prepare": {"clean", "peel", "align"},
        "apply": {"hang", "press", "secure"},
        "verify": {"inspect"},
        "return": {"resume_use"},
    },
    "fallback_household": {
        "daily_trigger": {"pick_up", "prepare"},
        "prepare": {"prepare", "align"},
        "apply": {"place", "attach", "operate"},
        "verify": {"inspect"},
        "return": {"resume_use"},
    },
}
FORM_APPLICATION_ACTIONS = {
    ("window_textile", "textile_panel"): {"draw", "hang", "open_close"},
    ("window_textile", "tensioned_mesh"): {"press_frame"},
    ("window_textile", "roll_to_sheet"): {"roll", "open_close"},
    ("window_film", "roll_to_sheet"): {"squeegee", "trim", "press_edge", "roll_unroll"},
    ("adhesive_decal", "decal_transfer"): {"press", "smooth"},
    ("small_label", "decal_transfer"): {"press", "smooth"},
    ("sealing_film", "consumable_film"): {"press_seal"},
    ("surface_covering", "textile_panel"): {"unfold", "smooth"},
    ("surface_covering", "roll_to_sheet"): {"smooth", "trim"},
    ("seasonal_decor", "decal_transfer"): {"press"},
    ("seasonal_decor", "textile_panel"): {"hang", "secure"},
    ("seasonal_decor", "rigid"): {"hang", "secure"},
}
RETURN_ACTIONS = {
    "window_textile": {"open_close", "resume_use"},
    "window_film": {"roll_unroll", "resume_use"},
    "adhesive_decal": {"inspect", "resume_use"},
    "small_label": {"pack", "retrieve", "resume_use"},
    "sealing_film": {"inspect", "handover"},
    "surface_covering": {"place_items", "resume_use"},
    "seasonal_decor": {"inspect", "resume_use"},
    "fallback_household": {"inspect", "resume_use"},
}
ROUTE_FORM_FACTORS = {
    "window_textile": {"textile_panel", "tensioned_mesh", "roll_to_sheet"},
    "window_film": {"roll_to_sheet"},
    "adhesive_decal": {"decal_transfer"},
    "small_label": {"decal_transfer"},
    "sealing_film": {"consumable_film"},
    "surface_covering": {"textile_panel", "roll_to_sheet"},
    "seasonal_decor": {"decal_transfer", "textile_panel", "rigid"},
    "fallback_household": {"rigid", "textile_panel", "roll_to_sheet"},
}

REFERENCE_ROLES = {
    "identity_truth", "scale_context", "installation_truth", "action_truth",
    "result_truth", "exact_print_truth", "world_plate",
}
EVIDENCE_KINDS = {"identity", "scale", "installation", "action", "result", "exact_text"}
EVIDENCE_ROLE = {
    "identity": "identity_truth",
    "scale": "scale_context",
    "installation": "installation_truth",
    "action": "action_truth",
    "result": "result_truth",
    "exact_text": "exact_print_truth",
}
REFERENCE_REQUIRED_ACTIONS = {
    "press_frame", "hang", "squeegee", "trim", "press_edge", "press_seal", "secure",
}
CONFIDENCE_LEVELS = {"high", "medium"}
CLAIM_TYPES = {"none", "observed", "aesthetic", "functional"}
INFORMATION_TYPES = {"context", "task_progress", "product_fact", "result"}
PROMPT_MODES = {"motion_only_i2v", "chronological_shot", "editorial_bridge"}
COPY_BASES = {"none", "context", "fact", "result"}
COPY_ROLES = {"none", "need", "condition", "proof", "closure"}
COPY_ROLES_BY_JOB = {
    "daily_trigger": {"need"},
    "prepare": set(),
    "apply": set(),
    "verify": {"condition", "proof"},
    "return": {"closure"},
}
SHOT_SIZES = {"wide", "medium", "medium_close", "close", "macro"}
CAMERA_SIDES = {"interior", "exterior", "same_space"}
CAMERA_ROLES = {
    "hold_context", "follow_contact", "reveal_result", "bridge_space",
    "return_to_master",
}
CAMERA_ROLES_BY_JOB = {
    "daily_trigger": {"hold_context", "follow_contact"},
    "prepare": {"follow_contact"},
    "apply": {"follow_contact"},
    "verify": {"reveal_result", "bridge_space"},
    "return": {"return_to_master", "bridge_space"},
}
CAMERA_MOVES = {
    "locked", "handheld_hold", "short_follow", "short_track", "gentle_tilt",
    "small_push_in",
}
TRANSITIONS = {"none", "occlusion", "match_action"}
NO_COPY = {"无", "none", "no copy", "n/a"}

BANNED_COPY_FRAGMENTS = {
    "重新定义品质", "品质之选", "极致体验", "非凡之选", "开启美好生活",
    "不止于此", "匠心品质", "高端大气", "细节自会说话", "留下这一眼",
    "轻松搞定", "不止好看", "一步到位", "质感拉满",
}
BANNED_PROCESS_COPY_FRAGMENTS = {
    "擦净玻璃", "清洁玻璃", "留足裁边", "裁边余量", "对准边缘", "慢慢刮平",
    "沿边刮平", "沿边裁齐", "沿边裁切", "揭开背纸", "逐段压平",
}
BANNED_SPECTACLE = {
    "black studio", "pedestal", "levitating", "floating parts", "volumetric beam",
    "god rays", "energy shield", "magic particles", "explosion", "hero pedestal",
    "luxury mansion", "黑棚", "展示底座", "漂浮零件", "粒子", "火花", "烟雾",
    "光束", "体积光", "发光护盾", "能量波", "爆炸", "豪宅", "英雄镜头",
    "飓风", "风暴式",
}
PLACEHOLDER_VALUES = {
    "无", "同上", "见上", "待定", "默认", "常规", "正常", "自然", "日常", "真实",
    "略", "tbd", "todo", "na", "placeholder",
}


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalized(value: Any) -> str:
    return re.sub(r"[\W_]+", "", _text(value).casefold(), flags=re.UNICODE)


def _require_text(root: Mapping[str, Any], key: str, path: str, errors: list[str]) -> str:
    value = _text(root.get(key))
    if not value:
        errors.append("{} requires non-empty {}".format(path, key))
    return value


def _reject_vague(value: str, path: str, errors: list[str], minimum: int = 4) -> None:
    normalized = _normalized(value)
    if normalized in PLACEHOLDER_VALUES or len(normalized) < minimum:
        errors.append("{} must be concrete, not a placeholder".format(path))


def _string_list(value: Any, path: str, errors: list[str], *, allow_empty: bool = True) -> list[str]:
    if not _is_sequence(value) or any(not _text(item) for item in value):
        errors.append("{} must be a list of non-empty strings".format(path))
        return []
    result = [_text(item) for item in value]
    if not allow_empty and not result:
        errors.append("{} must not be empty".format(path))
    return result


def _contains_banned(texts: Sequence[str]) -> list[str]:
    haystack = "\n".join(texts).casefold()
    return sorted(term for term in BANNED_SPECTACLE if term.casefold() in haystack)


def validate_plan(plan: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(plan, Mapping):
        return ["plan must be a JSON object"]

    product = plan.get("product")
    if not isinstance(product, Mapping):
        errors.append("product must be an object")
        product = {}
    _require_text(product, "name", "product", errors)
    route = _require_text(product, "route", "product", errors)
    if route and route not in ROUTE_ACTIONS:
        errors.append("product.route is invalid")
    form_factor = _require_text(product, "form_factor", "product", errors)
    if route in ROUTE_FORM_FACTORS and form_factor not in ROUTE_FORM_FACTORS[route]:
        errors.append("product.form_factor {} is not valid for route {}".format(form_factor, route))
    identity_key = _require_text(product, "identity_key", "product", errors)
    if identity_key:
        _reject_vague(identity_key, "product.identity_key", errors, 4)

    packet = product.get("reference_packet")
    packet_roles: set[str] = set()
    if not _is_sequence(packet) or not packet:
        errors.append("product.reference_packet must contain at least identity_truth")
        packet = []
    for index, reference in enumerate(packet):
        path = "product.reference_packet[{}]".format(index)
        if not isinstance(reference, Mapping):
            errors.append("{} must be an object".format(path))
            continue
        role = _require_text(reference, "role", path, errors)
        _require_text(reference, "source", path, errors)
        identity_match = _require_text(reference, "identity_match", path, errors)
        if role and role not in REFERENCE_ROLES:
            errors.append("{}.role is invalid".format(path))
        if identity_match and identity_match not in {"same_sku", "same_variant", "not_applicable"}:
            errors.append("{}.identity_match is invalid".format(path))
        if role:
            packet_roles.add(role)
    if "identity_truth" not in packet_roles:
        errors.append("product.reference_packet requires identity_truth")
    if route == "small_label" and "exact_print_truth" not in packet_roles:
        errors.append("small_label requires exact_print_truth to protect names and artwork")

    facts = product.get("facts")
    fact_by_id: dict[str, Mapping[str, Any]] = {}
    fact_texts: set[str] = set()
    if not _is_sequence(facts) or not facts:
        errors.append("product.facts must contain at least one verified fact")
        facts = []
    for index, fact in enumerate(facts):
        path = "product.facts[{}]".format(index)
        if not isinstance(fact, Mapping):
            errors.append("{} must be an object".format(path))
            continue
        fact_id = _require_text(fact, "id", path, errors)
        observed = _require_text(fact, "observed", path, errors)
        _require_text(fact, "source", path, errors)
        _require_text(fact, "region", path, errors)
        evidence_kind = _require_text(fact, "evidence_kind", path, errors)
        confidence = _require_text(fact, "confidence", path, errors)
        allowed_claims = _string_list(fact.get("allowed_claims"), "{}.allowed_claims".format(path), errors, allow_empty=False)
        if observed:
            _reject_vague(observed, "{}.observed".format(path), errors, 4)
        if fact_id and not re.fullmatch(r"F[1-9][0-9]*", fact_id):
            errors.append("{}.id must use F1, F2, ...".format(path))
        if fact_id in fact_by_id:
            errors.append("duplicate fact id {}".format(fact_id))
        if fact_id:
            fact_by_id[fact_id] = fact
        if evidence_kind and evidence_kind not in EVIDENCE_KINDS:
            errors.append("{}.evidence_kind is invalid".format(path))
        required_role = EVIDENCE_ROLE.get(evidence_kind)
        if required_role and required_role not in packet_roles:
            errors.append(
                "{} evidence_kind {} requires reference role {}".format(
                    path, evidence_kind, required_role
                )
            )
        if confidence and confidence not in CONFIDENCE_LEVELS:
            errors.append("{}.confidence is invalid".format(path))
        invalid_claims = set(allowed_claims) - (CLAIM_TYPES - {"none"})
        if invalid_claims:
            errors.append("{}.allowed_claims contains invalid values".format(path))
        if "functional" in allowed_claims and evidence_kind != "result":
            errors.append("{} may allow functional claims only with result evidence".format(path))
        normalized_fact = _normalized(observed)
        if normalized_fact and normalized_fact in fact_texts:
            errors.append("duplicate observed fact at {}".format(path))
        if normalized_fact:
            fact_texts.add(normalized_fact)

    _string_list(product.get("uncertainties", []), "product.uncertainties", errors)

    creative = plan.get("creative")
    if not isinstance(creative, Mapping):
        errors.append("creative must be an object")
        creative = {}
    creative_texts: list[str] = []
    for key in (
        "spine", "selling_point", "daily_trigger", "preparation", "application",
        "visible_verification", "return_to_life", "ordinary_setting", "causal_sentence",
    ):
        value = _require_text(creative, key, "creative", errors)
        creative_texts.append(value)
        if value:
            _reject_vague(value, "creative.{}".format(key), errors, 6)
    selling_point_facts = _string_list(
        creative.get("selling_point_fact_ids"), "creative.selling_point_fact_ids", errors,
        allow_empty=False,
    )
    selling_point_claim = _require_text(
        creative, "selling_point_claim_type", "creative", errors
    )
    if selling_point_claim and selling_point_claim not in CLAIM_TYPES - {"none"}:
        errors.append("creative.selling_point_claim_type is invalid")
    for fact_id in selling_point_facts:
        fact = fact_by_id.get(fact_id)
        if not fact:
            errors.append("creative.selling_point_fact_ids references unknown fact {}".format(fact_id))
            continue
        allowed = {_text(value) for value in fact.get("allowed_claims", [])}
        if selling_point_claim and selling_point_claim not in allowed:
            errors.append(
                "creative.selling_point_claim_type {} is not allowed by fact {}".format(
                    selling_point_claim, fact_id
                )
            )
        if selling_point_claim == "functional" and _text(fact.get("evidence_kind")) != "result":
            errors.append("creative functional selling point requires result evidence")
    selling_point = _text(creative.get("selling_point"))
    if selling_point and re.search(r"(?:\d+(?:\.\d+)?\s*(?:%|％|°C|℃)|百分之)", selling_point):
        if selling_point_claim != "functional":
            errors.append("numeric performance selling points require functional result evidence")
    causal_sentence = _text(creative.get("causal_sentence"))
    if causal_sentence and not any(token in causal_sentence.casefold() for token in ("因此", "所以", "because", "therefore", "→")):
        errors.append("creative.causal_sentence must express an explicit causal link")

    realism = plan.get("realism")
    if not isinstance(realism, Mapping):
        errors.append("realism must be an object")
        realism = {}
    realism_texts: list[str] = []
    for key in ("location", "time_of_day", "lighting", "lens", "actor", "background_activity", "visual_style"):
        value = _require_text(realism, key, "realism", errors)
        realism_texts.append(value)
        if value and key not in {"time_of_day", "lens"}:
            _reject_vague(value, "realism.{}".format(key), errors, 4)
    life_traces = _string_list(realism.get("life_traces"), "realism.life_traces", errors, allow_empty=False)
    if life_traces and not 2 <= len(life_traces) <= 3:
        errors.append("realism.life_traces must contain two or three purposeful everyday details")
    if len({_normalized(trace) for trace in life_traces}) != len(life_traces):
        errors.append("realism.life_traces must not repeat the same detail")
    for index, trace in enumerate(life_traces):
        _reject_vague(trace, "realism.life_traces[{}]".format(index), errors, 4)
    lens = _text(realism.get("lens"))
    if lens and not re.search(r"(?:35|40|45|50)\s*mm", lens, flags=re.IGNORECASE):
        errors.append("realism.lens must use a natural 35-50mm equivalent view")

    banned = _contains_banned(creative_texts + realism_texts + life_traces)
    if banned:
        errors.append("positive plan contains banned spectacle terms: {}".format(", ".join(banned)))

    anchors = plan.get("anchors")
    if not _is_sequence(anchors):
        errors.append("anchors must be a list")
        anchors = []
    anchor_by_id: dict[str, Mapping[str, Any]] = {}
    state_ids: set[str] = set()
    states: set[str] = set()
    scenes: list[str] = []
    camera_families: set[str] = set()
    macro_count = 0
    anchor_positive_texts: list[str] = []
    for index, anchor in enumerate(anchors):
        path = "anchors[{}]".format(index)
        if not isinstance(anchor, Mapping):
            errors.append("{} must be an object".format(path))
            continue
        anchor_id = _require_text(anchor, "id", path, errors)
        state_id = _require_text(anchor, "state_id", path, errors)
        phase = _require_text(anchor, "phase", path, errors)
        scene = _require_text(anchor, "scene", path, errors)
        state = _require_text(anchor, "state", path, errors)
        product_phase = _require_text(anchor, "product_phase", path, errors)
        deformation_state = _require_text(anchor, "deformation_state", path, errors)
        surface_contact = _require_text(anchor, "surface_contact", path, errors)
        actor_state = _require_text(anchor, "actor_state", path, errors)
        tool_state = _require_text(anchor, "tool_state", path, errors)
        camera_family = _require_text(anchor, "camera_family", path, errors)
        camera_side = _require_text(anchor, "camera_side", path, errors)
        shot_size = _require_text(anchor, "shot_size", path, errors)
        screen_axis = _require_text(anchor, "screen_axis", path, errors)
        anchor_positive_texts.extend(
            (scene, state, product_phase, deformation_state, surface_contact, actor_state, tool_state)
        )
        for key, value, minimum in (
            ("scene", scene, 4), ("state", state, 6), ("product_phase", product_phase, 4),
            ("deformation_state", deformation_state, 5), ("surface_contact", surface_contact, 5),
            ("actor_state", actor_state, 5), ("tool_state", tool_state, 5),
            ("screen_axis", screen_axis, 5),
        ):
            if value:
                _reject_vague(value, "{}.{}".format(path, key), errors, minimum)
        if anchor_id in anchor_by_id:
            errors.append("duplicate anchor id {}".format(anchor_id))
        if anchor_id:
            anchor_by_id[anchor_id] = anchor
        if phase and phase != ANCHOR_PHASES.get(anchor_id):
            errors.append("{}.phase must be {}".format(path, ANCHOR_PHASES.get(anchor_id)))
        if state_id in state_ids:
            errors.append("duplicate anchor state_id {}".format(state_id))
        if state_id:
            state_ids.add(state_id)
        normalized_state = _normalized(state)
        if normalized_state and normalized_state in states:
            errors.append("anchor {} repeats an earlier visible state".format(anchor_id or index))
        if normalized_state:
            states.add(normalized_state)
        if scene:
            scenes.append(scene)
        if camera_family:
            camera_families.add(camera_family)
        if camera_side and camera_side not in CAMERA_SIDES:
            errors.append("{}.camera_side is invalid".format(path))
        if shot_size and shot_size not in SHOT_SIZES:
            errors.append("{}.shot_size is invalid".format(path))
        if shot_size == "macro":
            macro_count += 1

    if tuple(anchor_by_id) != ANCHOR_IDS:
        errors.append("anchors must appear exactly once in order 01 through 06")
    if len(camera_families) > 3:
        errors.append("use at most three camera families across the sequence")
    if macro_count > 1:
        errors.append("use macro framing at most once")
    if scenes and len({_normalized(scene) for scene in scenes}) != 1:
        errors.append("the everyday loop must remain in one coherent scene")
    banned = _contains_banned(anchor_positive_texts)
    if banned:
        errors.append("anchors contain banned spectacle terms: {}".format(", ".join(banned)))

    segments = plan.get("segments")
    if not _is_sequence(segments):
        errors.append("segments must be a list")
        segments = []
    segment_ids: list[str] = []
    information_seen: set[str] = set()
    copy_seen: set[str] = set()
    copy_count = 0
    segment_positive_texts: list[str] = []
    for index, segment in enumerate(segments):
        path = "segments[{}]".format(index)
        if not isinstance(segment, Mapping):
            errors.append("{} must be an object".format(path))
            continue
        segment_id = _require_text(segment, "id", path, errors)
        segment_ids.append(segment_id)
        expected_from = "{:02d}".format(index + 1)
        expected_to = "{:02d}".format(index + 2)
        if _text(segment.get("from")) != expected_from or _text(segment.get("to")) != expected_to:
            errors.append("{} must map {} to {}".format(path, expected_from, expected_to))
        narrative_job = _text(segment.get("narrative_job"))
        if narrative_job != EXPECTED_JOBS.get(segment_id):
            errors.append("{}.narrative_job must be {}".format(path, EXPECTED_JOBS.get(segment_id)))

        from_anchor = anchor_by_id.get(expected_from, {})
        to_anchor = anchor_by_id.get(expected_to, {})
        if _text(segment.get("from_state_id")) != _text(from_anchor.get("state_id")):
            errors.append("{}.from_state_id must match anchor {}".format(path, expected_from))
        if _text(segment.get("to_state_id")) != _text(to_anchor.get("state_id")):
            errors.append("{}.to_state_id must match anchor {}".format(path, expected_to))

        cause = _require_text(segment, "cause", path, errors)
        effect = _require_text(segment, "effect", path, errors)
        prompt_mode = _require_text(segment, "prompt_mode", path, errors)
        visual_focus = _require_text(segment, "visual_focus", path, errors)
        visible_change = _require_text(segment, "visible_change", path, errors)
        physical_consequence = _require_text(segment, "physical_consequence", path, errors)
        information_type = _require_text(segment, "information_type", path, errors)
        new_information = _require_text(segment, "new_information", path, errors)
        segment_positive_texts.extend(
            (cause, effect, visual_focus, visible_change, physical_consequence, new_information)
        )
        if cause and effect and _normalized(cause) == _normalized(effect):
            errors.append("{} cause and effect must describe different states".format(path))
        if prompt_mode and prompt_mode not in PROMPT_MODES:
            errors.append("{}.prompt_mode is invalid".format(path))
        for key, value in (
            ("visual_focus", visual_focus),
            ("visible_change", visible_change),
            ("physical_consequence", physical_consequence),
        ):
            if value:
                _reject_vague(value, "{}.{}".format(path, key), errors, 6)
        if information_type and information_type not in INFORMATION_TYPES:
            errors.append("{}.information_type is invalid".format(path))
        normalized_information = _normalized(new_information)
        if normalized_information and normalized_information in information_seen:
            errors.append("{} repeats earlier new_information".format(path))
        if normalized_information:
            information_seen.add(normalized_information)

        action = segment.get("action")
        if not isinstance(action, Mapping):
            errors.append("{}.action must be an object".format(path))
            action = {}
        action_texts: list[str] = []
        for key in ("subject", "motion", "direction", "speed", "resistance", "contact", "end_state"):
            value = _require_text(action, key, "{}.action".format(path), errors)
            action_texts.append(value)
            if value:
                _reject_vague(value, "{}.action.{}".format(path, key), errors, 4)
        segment_positive_texts.extend(action_texts)
        action_family = _require_text(action, "action_family", "{}.action".format(path), errors)
        if route in ROUTE_ACTIONS and action_family not in ROUTE_ACTIONS[route]:
            errors.append("{}.action.action_family {} is not allowed for route {}".format(path, action_family, route))
        phase_actions = ROUTE_PHASE_ACTIONS.get(route, {}).get(narrative_job, set())
        if phase_actions and action_family not in phase_actions:
            errors.append(
                "{}.action.action_family {} is not allowed during {} for route {}".format(
                    path, action_family, narrative_job, route
                )
            )
        if segment_id == "03":
            form_actions = FORM_APPLICATION_ACTIONS.get((route, form_factor), set())
            if form_actions and action_family not in form_actions:
                errors.append(
                    "{}.action.action_family {} violates {} application physics".format(
                        path, action_family, form_factor
                    )
                )
        if segment_id == "05" and route in RETURN_ACTIONS and action_family not in RETURN_ACTIONS[route]:
            errors.append("{}.action must return the product to ordinary life".format(path))
        if _normalized(action.get("end_state")) != _normalized(to_anchor.get("state")):
            errors.append("{}.action.end_state must exactly describe the destination anchor state".format(path))

        action_basis = _require_text(segment, "action_basis", path, errors)
        if action_basis and action_basis not in {"reference", "route_default"}:
            errors.append("{}.action_basis is invalid".format(path))
        action_fact_ids = _string_list(segment.get("action_fact_ids", []), "{}.action_fact_ids".format(path), errors)
        if action_basis == "reference" and not action_fact_ids:
            errors.append("{}.action_basis reference requires action_fact_ids".format(path))
        if action_family in REFERENCE_REQUIRED_ACTIONS and action_basis != "reference":
            errors.append(
                "{}.action.action_family {} requires matching installation/action evidence".format(
                    path, action_family
                )
            )
        for fact_id in action_fact_ids:
            fact = fact_by_id.get(fact_id)
            if not fact:
                errors.append("{} references unknown action fact {}".format(path, fact_id))
            elif _text(fact.get("evidence_kind")) not in {"installation", "action"}:
                errors.append("{} action fact {} must use installation/action evidence".format(path, fact_id))

        camera = segment.get("camera")
        if not isinstance(camera, Mapping):
            errors.append("{}.camera must be an object".format(path))
            camera = {}
        camera_role = _require_text(camera, "role", "{}.camera".format(path), errors)
        move = _require_text(camera, "move", "{}.camera".format(path), errors)
        motivation = _require_text(camera, "motivation", "{}.camera".format(path), errors)
        if motivation:
            _reject_vague(motivation, "{}.camera.motivation".format(path), errors, 4)
        if camera_role and camera_role not in CAMERA_ROLES:
            errors.append("{}.camera.role is invalid".format(path))
        allowed_roles = CAMERA_ROLES_BY_JOB.get(narrative_job, set())
        if allowed_roles and camera_role not in allowed_roles:
            errors.append(
                "{}.camera.role {} does not serve {}".format(path, camera_role, narrative_job)
            )
        if move and move not in CAMERA_MOVES:
            errors.append("{}.camera.move is invalid".format(path))
        background_response = _require_text(segment, "background_response", path, errors)
        if background_response:
            _reject_vague(background_response, "{}.background_response".format(path), errors, 4)

        fact_ids = _string_list(segment.get("fact_ids", []), "{}.fact_ids".format(path), errors)
        for fact_id in fact_ids:
            if fact_id not in fact_by_id:
                errors.append("{} references unknown fact {}".format(path, fact_id))
        if information_type in {"product_fact", "result"} and not fact_ids:
            errors.append("{}.information_type {} requires fact_ids".format(path, information_type))

        claim_type = _require_text(segment, "claim_type", path, errors)
        if claim_type and claim_type not in CLAIM_TYPES:
            errors.append("{}.claim_type is invalid".format(path))
        if claim_type != "none" and not fact_ids:
            errors.append("{}.claim_type {} requires fact_ids".format(path, claim_type))
        if information_type in {"context", "task_progress"} and (claim_type != "none" or fact_ids):
            errors.append("{}.information_type {} must not carry product claims".format(path, information_type))
        for fact_id in fact_ids:
            fact = fact_by_id.get(fact_id, {})
            allowed_claims = {_text(value) for value in fact.get("allowed_claims", [])} if isinstance(fact, Mapping) else set()
            if claim_type not in {"", "none"} and claim_type not in allowed_claims:
                errors.append("{} claim_type {} is not allowed by fact {}".format(path, claim_type, fact_id))
            if claim_type == "functional" and _text(fact.get("evidence_kind")) != "result":
                errors.append("{} functional claim requires result evidence".format(path))

        copy = _require_text(segment, "copy", path, errors)
        copy_role = _require_text(segment, "copy_role", path, errors)
        copy_basis = _require_text(segment, "copy_basis", path, errors)
        copy_reference = _text(segment.get("copy_reference"))
        copy_visual_evidence = _text(segment.get("copy_visual_evidence"))
        is_no_copy = copy.casefold() in NO_COPY
        if is_no_copy:
            if copy_role != "none":
                errors.append("{}.copy_role must be none when copy is 无".format(path))
            if copy_basis != "none":
                errors.append("{}.copy_basis must be none when copy is 无".format(path))
            if copy_reference or copy_visual_evidence:
                errors.append("{}.copy reference/evidence must be empty when copy is 无".format(path))
        else:
            copy_count += 1
            if copy_role not in COPY_ROLES - {"none"}:
                errors.append("{}.copy_role is invalid".format(path))
            allowed_copy_roles = COPY_ROLES_BY_JOB.get(narrative_job, set())
            if copy_role not in allowed_copy_roles:
                errors.append(
                    "{}.copy_role {} is not allowed during {}".format(
                        path, copy_role, narrative_job
                    )
                )
            if copy_basis not in COPY_BASES - {"none"}:
                errors.append("{}.copy_basis must bind the line to context, fact, or result".format(path))
            if not copy_reference:
                errors.append("{}.copy_reference must name the concrete object, condition, or fact".format(path))
            else:
                _reject_vague(copy_reference, "{}.copy_reference".format(path), errors, 4)
            if not copy_visual_evidence:
                errors.append("{}.copy_visual_evidence must point to the target anchor".format(path))
            else:
                _reject_vague(copy_visual_evidence, "{}.copy_visual_evidence".format(path), errors, 6)
            if len(copy) > 30:
                errors.append("{}.copy must be concise (30 characters maximum)".format(path))
            if any(fragment in copy for fragment in BANNED_COPY_FRAGMENTS):
                errors.append("{}.copy contains a generic cliché".format(path))
            if any(fragment in copy for fragment in BANNED_PROCESS_COPY_FRAGMENTS):
                errors.append("{}.copy reads like installation instructions".format(path))
            normalized_copy = _normalized(copy)
            if normalized_copy in copy_seen:
                errors.append("{}.copy repeats an earlier line".format(path))
            if normalized_copy:
                copy_seen.add(normalized_copy)

        transition = _require_text(segment, "transition", path, errors)
        if transition and transition not in TRANSITIONS:
            errors.append("{}.transition is invalid".format(path))
        has_editorial_transition = transition in {"occlusion", "match_action"}
        if prompt_mode == "editorial_bridge" and not has_editorial_transition:
            errors.append("{} editorial_bridge requires exactly one occlusion or match_action transition".format(path))
        if has_editorial_transition and prompt_mode != "editorial_bridge":
            errors.append(
                "{} occlusion/match_action requires prompt_mode editorial_bridge; pure i2v modes cannot contain cuts".format(
                    path
                )
            )
        if has_editorial_transition and narrative_job in {"verify", "return"}:
            if camera_role not in {"bridge_space", "return_to_master"}:
                errors.append("{} spatial transition requires a bridge camera role".format(path))

        from_side = _text(from_anchor.get("camera_side"))
        to_side = _text(to_anchor.get("camera_side"))
        if from_side and to_side and from_side != to_side:
            crosses_window_sides = {from_side, to_side} == {"interior", "exterior"}
            if not crosses_window_sides:
                errors.append("{} camera_side changes without a valid interior/exterior route".format(path))
            elif camera_role not in {"bridge_space", "return_to_master"}:
                errors.append("{} interior/exterior change requires a spatial bridge".format(path))
            elif move != "short_follow" and transition not in {"occlusion", "match_action"}:
                errors.append(
                    "{} interior/exterior change needs short_follow or one motivated transition".format(path)
                )

    if tuple(segment_ids) != SEGMENT_IDS:
        errors.append("segments must appear exactly once in order 01 through 05")
    if copy_count > 3:
        errors.append("use at most three concrete copy lines; zero copy is allowed")
    banned = _contains_banned(segment_positive_texts)
    if banned:
        errors.append("segments contain banned spectacle terms: {}".format(", ".join(banned)))

    return errors


def _load_stdin() -> Any:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid_json: {}".format(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a natural product-video plan from UTF-8 JSON stdin."
    )
    parser.add_argument("--stdin", action="store_true", help="Read the plan from stdin")
    args = parser.parse_args(argv)
    if not args.stdin:
        parser.error("--stdin is required")
    try:
        plan = _load_stdin()
        errors = validate_plan(plan)
    except ValueError as exc:
        errors = [str(exc)]
    payload = {"ok": not errors, "errors": errors}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
