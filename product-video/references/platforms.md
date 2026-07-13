# Flow and CapCut Outputs

## 目录

- 共同规则
- 通用 JSON
- Google Flow
- CapCut
- 默认五镜头

## 共同规则

Skill 不调用外部 API，也不登录或操作平台；只生成逐镜头、可复制粘贴的中文操作说明和英文提示词。界面模型名、积分和可选时长可能变化，不写死。

- 从 `storyboard.json` 派生全部平台文件，禁止分别创作三套分镜。
- 五个镜头分别生成，再按顺序剪辑。
- 平台不支持 2 秒时，生成最短可用长度，再截取到 `duration_seconds`。
- 默认无字幕、无 CTA、无生成式旁白；文字、配音和音乐留给剪辑阶段。
- 没有独立负面提示词框时，把 `negative_prompt_en` 作为 `Avoid:` 追加到主提示词。
- 平台参考功能不可用时，回退为“单张已锁定且通过质检的关键帧 → 图片转视频”，不改分镜。

## 通用 JSON

`prompts/universal.json` 只投影执行所需字段，不作为第二份可编辑真源：

```json
{
  "schema_version": "1.0",
  "project_name": "项目名",
  "product_profile": "../product-profile.json",
  "aspect_ratio": "9:16",
  "target_duration_seconds": 10,
  "global_consistency_prompt": "所有镜头共用的商品身份和视觉世界约束",
  "shots": [
    {
      "id": "shot-01",
      "keyframe": "../keyframes/shot-01-hook.png",
      "duration_seconds": 2,
      "first_frame_state": "关键帧起始状态",
      "motion": "一个主要运镜和最多两个动作",
      "last_frame_state": "明确结束状态",
      "continuity_anchors": ["商品朝向", "尺度", "主光方向", "背景锚点"],
      "prompt_en": "动作、环境、镜头运动和结束状态",
      "negative_prompt_en": "商品一致性和画面问题约束"
    }
  ]
}
```

视频 prompt 描述从关键帧开始如何运动，不重新设计静态商品。每镜只保留一个主要运镜和最多两个动作，并在结尾落到 `last_frame_state`；相邻镜头复用必要的 `continuity_anchors`。

## Google Flow

优先把每个镜头的 `keyframe` 作为该镜头的起始帧。若当前界面允许补充产品参考，可额外上传一张清晰商品真值图；不要再上传含其它商品的风格图，因为风格已烘焙进关键帧。

Flow 版聚焦一个连续镜头，可保留较完整的摄影描述：

```text
Animate the supplied start frame as one continuous vertical product shot. Keep the exact product unchanged in shape, proportions, color, material, part count, logo, labels, packaging layout, and scale.

{PRODUCT_ACTION}. Camera: {CAMERA_MOVEMENT}, maintaining {SHOT_SIZE} from {CAMERA_ANGLE}. {ENVIRONMENT_MOTION}. Use {LIGHTING_STYLE}, stable and flicker-free. End on {END_STATE} and hold cleanly.

No cuts, scene changes, product morphing, duplication, invented surfaces, label changes, warped hands, subtitles, watermarks, or UI.
```

`prompts/flow.md` 每镜头固定格式：

```text
## Shot 01 — Hook
Input: keyframes/shot-01-hook.png
Optional product reference: <商品真值图路径>
Mode: Start frame preferred
Target edit duration: 2s

Prompt:
<FLOW_PROMPT_EN>
```

只有起止帧都已经商品身份锁定并通过一致性检查时才使用双帧控制。

## CapCut

CapCut 版保持短而动作优先，便于复制到图片转视频描述栏：

```text
Animate this identity-locked, QC-passed product keyframe into a clean vertical e-commerce shot. Keep the product perfectly unchanged and stable. {PRODUCT_ACTION}. Use {CAMERA_MOVEMENT}; maintain {SHOT_SIZE}, {CAMERA_ANGLE}, and {LIGHTING_STYLE}. End with {END_STATE}. No morphing, duplication, label changes, extra objects, flicker, subtitles, watermark, or UI.
```

`prompts/capcut.md` 每镜头固定格式：

```text
## Shot 01 — Hook
Image: keyframes/shot-01-hook.png
Target edit duration: 2s

Prompt:
<CAPCUT_PROMPT_EN>

Editing note: trim to 2s; <TRANSITION_NOTE>
```

不要加入界面按钮位置等容易变化的说明，也不要省略商品身份约束。

## 默认五镜头

| 顺序 | purpose | 目标时长 | 意图 |
|---|---|---:|---|
| 1 | hook | 2.0s | 快速显露商品，第一帧已有主体 |
| 2 | hero | 2.0s | 主视角展示，突出轮廓与高级感 |
| 3 | use | 2.0s | 保守使用情境，仅展示图片或用户文字明确支持的功能 |
| 4 | detail | 2.0s | 身份锁中可见材质或结构特写，避开不确定文字 |
| 5 | ending | 2.0s | 商品稳定定格并留安全留白，不生成 CTA |

用户指定总时长时按比例调整，保持五镜头顺序。若用户明确指定镜头数，再同步调整 `storyboard.json` 和校验脚本参数。
