import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_plan.py"
SPEC = importlib.util.spec_from_file_location("check_plan", SCRIPT)
check_plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_plan)


ROUTE_CASES = {
    "window_textile": ("tensioned_mesh", ["reach", "measure", "press_frame", "settle", "resume_use"]),
    "window_film": ("roll_to_sheet", ["clean", "align", "squeegee", "inspect", "resume_use"]),
    "adhesive_decal": ("decal_transfer", ["clean", "align", "press", "inspect", "resume_use"]),
    "small_label": ("decal_transfer", ["select", "align", "press", "inspect", "pack"]),
    "sealing_film": ("consumable_film", ["place_cup", "align_film", "press_seal", "inspect", "handover"]),
    "surface_covering": ("roll_to_sheet", ["clear_surface", "align", "smooth", "inspect", "place_items"]),
    "seasonal_decor": ("decal_transfer", ["choose_position", "align", "press", "inspect", "resume_use"]),
    "fallback_household": ("rigid", ["pick_up", "prepare", "operate", "inspect", "resume_use"]),
}


def valid_plan(route="window_film"):
    form_factor, actions = ROUTE_CASES[route]
    packet = [
        {"role": "identity_truth", "source": "同款SKU主图.jpg", "identity_match": "same_sku"},
        {"role": "installation_truth", "source": "同款详情安装图.jpg", "identity_match": "same_sku"},
        {"role": "result_truth", "source": "同款详情安装图.jpg", "identity_match": "same_sku"},
    ]
    if route == "small_label":
        packet.append(
            {"role": "exact_print_truth", "source": "姓名贴清晰图.jpg", "identity_match": "same_sku"}
        )
    facts = [
        {
            "id": "F1",
            "observed": "同款商品的颜色、图案和边缘结构",
            "source": "同款SKU主图.jpg",
            "region": "商品正面",
            "evidence_kind": "identity",
            "confidence": "high",
            "allowed_claims": ["observed", "aesthetic"],
        },
        {
            "id": "F2",
            "observed": "详情图展示商品与安装表面保持接触",
            "source": "同款详情安装图.jpg",
            "region": "手和接触边缘",
            "evidence_kind": "installation",
            "confidence": "high",
            "allowed_claims": ["observed"],
        },
        {
            "id": "F3",
            "observed": "安装完成后边缘平整且位置稳定",
            "source": "同款详情安装图.jpg",
            "region": "完成状态",
            "evidence_kind": "result",
            "confidence": "medium",
            "allowed_claims": ["observed"],
        },
    ]
    phases = ["need", "ready", "aligned", "applied", "verified", "resumed"]
    states = [
        "普通房间正在使用，目标表面仍待处理",
        "商品和必要工具已放到手边",
        "商品已沿目标边缘完成对齐",
        "关键贴合或安装动作已经完成",
        "手在正常距离检查完成后的边缘与位置",
        "手离开商品，人物回到原来的日常活动",
    ]
    anchors = []
    for index in range(6):
        anchors.append(
            {
                "id": "{:02d}".format(index + 1),
                "state_id": "S{}".format(index + 1),
                "phase": phases[index],
                "scene": "同一间普通白天住宅",
                "state": states[index],
                "product_phase": "商品阶段：{}".format(phases[index]),
                "deformation_state": "遵循 {} 的自然形变阶段 {}".format(form_factor, index + 1),
                "surface_contact": "与目标表面的接触关系在阶段 {} 清楚可见".format(index + 1),
                "actor_state": "同一成年人在阶段 {} 只完成当前动作".format(index + 1),
                "tool_state": "必要工具始终放在目标表面旁的固定操作区，阶段 {} 后仍可追踪".format(index + 1),
                "camera_family": ("master", "detail", "master", "detail", "master", "closure")[index],
                "camera_side": "same_space",
                "shot_size": ("medium", "medium_close", "close", "close", "medium_close", "medium")[index],
                "screen_axis": "镜头始终位于目标表面正面轴线左侧",
            }
        )
    jobs = ["daily_trigger", "prepare", "apply", "verify", "return"]
    info_types = ["context", "task_progress", "product_fact", "product_fact", "result"]
    fact_ids = [[], [], ["F2"], ["F1"], ["F3"]]
    claim_types = ["none", "none", "observed", "observed", "observed"]
    segments = []
    for index in range(5):
        segments.append(
            {
                "id": "{:02d}".format(index + 1),
                "from": "{:02d}".format(index + 1),
                "to": "{:02d}".format(index + 2),
                "from_state_id": "S{}".format(index + 1),
                "to_state_id": "S{}".format(index + 2),
                "narrative_job": jobs[index],
                "cause": states[index],
                "effect": states[index + 1],
                "prompt_mode": "motion_only_i2v",
                "visual_focus": "阶段 {} 中唯一需要看清的动作结果".format(index + 1),
                "visible_change": "相邻锚点之间只发生一次 {} 动作".format(actions[index]),
                "physical_consequence": "该动作使商品状态从阶段 {} 连续进入阶段 {}".format(index + 1, index + 2),
                "information_type": info_types[index],
                "new_information": "阶段 {} 的生活任务进展清楚可见".format(index + 1),
                "action": {
                    "subject": "同一成年人的双手" if index < 4 else "同一成年人",
                    "action_family": actions[index],
                    "motion": "只完成 {} 对应的一次连续动作".format(actions[index]),
                    "direction": "沿接触表面从左向右移动约二十厘米",
                    "speed": "普通手部操作速度，末端自然减速",
                    "resistance": "保留材料摩擦和轻微阻力",
                    "contact": "手、商品和目标表面的接触点持续可见",
                    "end_state": states[index + 1],
                },
                "action_basis": (
                    "reference" if actions[index] in check_plan.REFERENCE_REQUIRED_ACTIONS else "route_default"
                ),
                "action_fact_ids": ["F2"] if actions[index] in check_plan.REFERENCE_REQUIRED_ACTIONS else [],
                "camera": {
                    "role": ("hold_context", "follow_contact", "follow_contact", "reveal_result", "return_to_master")[index],
                    "move": "locked",
                    "motivation": "让当前唯一动作或结果保持可读",
                },
                "background_response": "背景中的日常物品保持不动，只有自然光轻微变化",
                "fact_ids": fact_ids[index],
                "claim_type": claim_types[index],
                "copy": "无",
                "copy_role": "none",
                "copy_basis": "none",
                "copy_reference": "",
                "copy_visual_evidence": "",
                "transition": "none",
            }
        )
    return {
        "product": {
            "name": "测试商品",
            "route": route,
            "form_factor": form_factor,
            "identity_key": "同一SKU、颜色和图案款",
            "reference_packet": packet,
            "facts": facts,
            "uncertainties": ["背面结构未展示，不生成背面特写"],
        },
        "creative": {
            "spine": "在同一房间完成一次普通安装并回到原来的生活",
            "selling_point": "商品与目标表面贴合后的可见完成状态",
            "selling_point_fact_ids": ["F3"],
            "selling_point_claim_type": "observed",
            "daily_trigger": "普通房间正在使用，目标表面仍待处理",
            "preparation": "把同款商品和必要工具放到手边并完成对齐",
            "application": "沿真实接触面完成一次关键操作",
            "visible_verification": "手在正常距离检查边缘和位置",
            "return_to_life": "手离开商品，人物继续原来的日常活动",
            "ordinary_setting": "有人真实居住的普通住宅，不是样板间",
            "causal_sentence": "因为准备和贴合连续完成，所以检查结束后能自然回到日常",
        },
        "realism": {
            "location": "普通住宅的一间正在使用的房间",
            "time_of_day": "白天",
            "lighting": "一侧普通窗光和室内自然反射",
            "lens": "40mm equivalent",
            "actor": "一名成年人，最多两只手入镜",
            "life_traces": ["桌上一本正在使用的笔记本", "窗边一把普通椅子"],
            "background_activity": "人物完成安装后继续桌边活动",
            "visual_style": "自然电商实拍，适度景深和准确接触影",
        },
        "anchors": anchors,
        "segments": segments,
    }


class CheckPlanTests(unittest.TestCase):
    def test_all_company_routes_pass(self):
        for route in ROUTE_CASES:
            with self.subTest(route=route):
                self.assertEqual(check_plan.validate_plan(valid_plan(route)), [])

    def test_route_form_factor_variants_pass(self):
        variants = (
            ("window_textile", "textile_panel", "draw"),
            ("window_textile", "roll_to_sheet", "roll"),
            ("surface_covering", "textile_panel", "unfold"),
            ("seasonal_decor", "textile_panel", "hang"),
            ("seasonal_decor", "rigid", "hang"),
        )
        for route, form_factor, apply_action in variants:
            with self.subTest(route=route, form_factor=form_factor):
                plan = valid_plan(route)
                plan["product"]["form_factor"] = form_factor
                plan["segments"][2]["action"]["action_family"] = apply_action
                if apply_action in check_plan.REFERENCE_REQUIRED_ACTIONS:
                    plan["segments"][2]["action_basis"] = "reference"
                    plan["segments"][2]["action_fact_ids"] = ["F2"]
                self.assertEqual(check_plan.validate_plan(plan), [])

    def test_rejects_wrong_route_action_and_form_factor(self):
        plan = valid_plan("window_film")
        plan["product"]["form_factor"] = "rigid"
        plan["segments"][2]["action"]["action_family"] = "press_seal"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("form_factor" in error for error in errors))
        self.assertTrue(any("not allowed for route" in error for error in errors))

    def test_rejects_route_action_in_wrong_phase(self):
        plan = valid_plan("window_film")
        plan["segments"][1]["action"]["action_family"] = "squeegee"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("not allowed during prepare" in error for error in errors))

    def test_rejects_state_id_cheat_wrong_phase_and_wrong_endpoint(self):
        plan = valid_plan()
        plan["anchors"][1]["state_id"] = plan["anchors"][0]["state_id"]
        plan["anchors"][2]["phase"] = "verified"
        plan["segments"][1]["action"]["end_state"] = "差不多完成"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("duplicate anchor state_id" in error for error in errors))
        self.assertTrue(any(".phase must be aligned" in error for error in errors))
        self.assertTrue(any("destination anchor state" in error for error in errors))

    def test_rejects_cross_sku_packet_and_missing_exact_print_truth(self):
        plan = valid_plan("small_label")
        plan["product"]["reference_packet"][0]["identity_match"] = "different_sku"
        plan["product"]["reference_packet"] = [
            item for item in plan["product"]["reference_packet"] if item["role"] != "exact_print_truth"
        ]
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("identity_match is invalid" in error for error in errors))
        self.assertTrue(any("small_label requires exact_print_truth" in error for error in errors))

    def test_functional_claim_requires_result_evidence_and_permission(self):
        plan = valid_plan("window_film")
        plan["segments"][2]["claim_type"] = "functional"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("not allowed by fact F2" in error for error in errors))
        self.assertTrue(any("functional claim requires result evidence" in error for error in errors))

    def test_selling_point_claim_must_be_authorized(self):
        plan = valid_plan("window_film")
        plan["creative"]["selling_point"] = "99% 隔热"
        plan["creative"]["selling_point_fact_ids"] = ["F1"]
        plan["creative"]["selling_point_claim_type"] = "functional"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("not allowed by fact F1" in error for error in errors))
        self.assertTrue(any("functional selling point requires result evidence" in error for error in errors))

    def test_rejects_fake_spectacle_scene_jump_and_non_returning_last_action(self):
        plan = valid_plan("window_textile")
        plan["creative"]["ordinary_setting"] = "黑棚展示底座与体积光"
        plan["anchors"][3]["scene"] = "豪宅客厅"
        plan["segments"][4]["action"]["action_family"] = "draw"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("banned spectacle" in error for error in errors))
        self.assertTrue(any("one coherent scene" in error for error in errors))
        self.assertTrue(any("return the product to ordinary life" in error for error in errors))

    def test_copy_is_optional_but_must_be_concrete_when_present(self):
        plan = valid_plan("small_label")
        plan["segments"][0].update(
            {
                "copy": "细节自会说话",
                "copy_role": "need",
                "copy_basis": "context",
                "copy_reference": "桌上两只相似水杯需要区分",
                "copy_visual_evidence": "目标锚点同时出现两只外观相似的水杯",
            }
        )
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("generic cliché" in error for error in errors))

        plan = valid_plan("small_label")
        plan["segments"][0].update(
            {
                "copy": "相似的水杯，先看名字。",
                "copy_role": "need",
                "copy_basis": "context",
                "copy_reference": "桌上两只相似水杯需要区分",
                "copy_visual_evidence": "目标锚点同时出现两只外观相似的水杯",
            }
        )
        self.assertEqual(check_plan.validate_plan(plan), [])

        plan = valid_plan("window_film")
        plan["segments"][2].update(
            {
                "copy": "贴平后，再沿边裁齐。",
                "copy_role": "proof",
                "copy_basis": "fact",
                "copy_reference": "刀尖沿窗框裁切余料",
                "copy_visual_evidence": "尾帧显示窄余料已经离开窗框",
            }
        )
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("not allowed during apply" in error for error in errors))
        self.assertTrue(any("installation instructions" in error for error in errors))

    def test_reference_action_must_use_installation_or_action_fact(self):
        plan = valid_plan()
        plan["segments"][2]["action_basis"] = "reference"
        plan["segments"][2]["action_fact_ids"] = ["F1"]
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("must use installation/action evidence" in error for error in errors))

        plan = valid_plan("sealing_film")
        plan["segments"][2]["action_basis"] = "route_default"
        plan["segments"][2]["action_fact_ids"] = []
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("requires matching installation/action evidence" in error for error in errors))

    def test_fact_evidence_kind_requires_matching_reference_role(self):
        plan = valid_plan()
        plan["product"]["reference_packet"] = [
            item for item in plan["product"]["reference_packet"] if item["role"] != "result_truth"
        ]
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("requires reference role result_truth" in error for error in errors))

    def test_rejects_placeholder_descriptions(self):
        plan = valid_plan()
        plan["creative"]["daily_trigger"] = "日常"
        plan["segments"][0]["action"]["contact"] = "默认"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("creative.daily_trigger must be concrete" in error for error in errors))
        self.assertTrue(any("action.contact must be concrete" in error for error in errors))

        plan = valid_plan()
        plan["realism"]["life_traces"] = ["窗边木椅", "窗边木椅"]
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("life_traces must not repeat" in error for error in errors))

    def test_requires_motion_focus_camera_role_and_tool_continuity(self):
        plan = valid_plan()
        plan["segments"][1]["visible_change"] = ""
        plan["segments"][1]["camera"]["role"] = "hold_context"
        plan["anchors"][2]["tool_state"] = ""
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("requires non-empty visible_change" in error for error in errors))
        self.assertTrue(any("does not serve prepare" in error for error in errors))
        self.assertTrue(any("requires non-empty tool_state" in error for error in errors))

    def test_allows_only_motivated_interior_exterior_bridge(self):
        plan = valid_plan("window_film")
        for anchor in plan["anchors"][:4]:
            anchor["camera_side"] = "interior"
        plan["anchors"][4]["camera_side"] = "exterior"
        plan["anchors"][5]["camera_side"] = "interior"
        plan["segments"][3]["camera"].update(
            {"role": "bridge_space", "move": "short_follow"}
        )
        plan["segments"][4]["camera"].update(
            {"role": "return_to_master", "move": "locked"}
        )
        plan["segments"][4]["prompt_mode"] = "editorial_bridge"
        plan["segments"][4]["transition"] = "match_action"
        self.assertEqual(check_plan.validate_plan(plan), [])

        plan = valid_plan("window_film")
        plan["segments"][2]["transition"] = "occlusion"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("requires prompt_mode editorial_bridge" in error for error in errors))

    def test_editorial_bridge_requires_one_cut_and_is_not_pure_i2v(self):
        plan = valid_plan("window_film")
        plan["segments"][2]["prompt_mode"] = "editorial_bridge"
        plan["segments"][2]["transition"] = "match_action"
        self.assertEqual(check_plan.validate_plan(plan), [])

        plan["segments"][2]["transition"] = "none"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("editorial_bridge requires exactly one" in error for error in errors))

        plan = valid_plan("window_film")
        plan["segments"][2]["prompt_mode"] = "motion_only_i2v"
        plan["segments"][2]["transition"] = "match_action"
        errors = check_plan.validate_plan(plan)
        self.assertTrue(any("pure i2v modes cannot contain cuts" in error for error in errors))

    def test_cli_returns_machine_readable_result(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--stdin"],
            input=json.dumps(valid_plan("sealing_film"), ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout), {"ok": True, "errors": []})

        invalid = copy.deepcopy(valid_plan())
        invalid["segments"][0]["from"] = "99"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--stdin"],
            input=json.dumps(invalid, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(json.loads(completed.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
