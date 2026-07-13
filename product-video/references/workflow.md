# Product Video Workflow

## 目录

- 输入与图片角色
- 聊天上传极速模式
- 商品真值优先级
- 项目目录
- 完整流程
- 商品身份卡
- 分镜结构
- 恢复与覆盖

## 输入与图片角色

接受聊天中直接上传的单张/多张图片、本地单张图片或递归项目目录。本地文件支持 `.jpg .jpeg .png .webp .bmp .tif .tiff`。

聊天附件优先于询问路径：当前消息已有图片时直接开始，不要求用户再提供文件夹或保存位置。

使用文件名和目录名只能产生 `role_hint`，最终必须查看图片后分类：

- `product_truth`：清晰商品主图、侧面图、背面图、包装图、细节图。
- `style_reference`：氛围、场景、构图、灯光、色彩、镜头参考。
- `ambiguous`：无法确定角色，写入内存中的 `uncertainties` 并按最保守角色继续；只有多个不同商品无法选择目标时才提问。
- `unreadable`：损坏或无法查看，写入警告，不参与生图。

不要因为参考图里出现相似产品，就把它当成用户商品。

## 聊天上传极速模式

当用户在消息中直接附加产品图：

1. 立即读取附件，不询问产品名、平台、比例或输出目录；缺省值使用 Flow + CapCut、9:16、5 镜头、约 10 秒。
2. 单张附件默认作为主要商品真值图。多张附件按商品完整度和清晰度选主要真值；同一商品的其它视角作为补充，氛围/场景图作为风格参考。
3. 没有风格图时，自动选择不暗示未经证实功能的商业场景，例如摄影棚、桌面、生活方式空间或材质背景。
4. 在内存中生成 `auto_locked` 商品身份卡、单一创意重点、统一视觉语言和五镜头分镜，不展示中间确认。若用户没有给卖点，创意重点固定为“让商品被看清并记住”，不推断功能。
5. 直接调用内置生图生成一张五格场景分镜图。五格按 `hook → hero → use → detail → ending` 排列，画面不添加标题、编号、字幕或 CTA。
6. 用户后续说“拆分/单独出图/第 N 镜头”时，使用已锁定商品和分镜生成对应独立关键帧；需要完整素材包时，只有在用户消息中提供明确本地图片或目录路径后才写入项目文件。

附件有工具可访问路径时可用于图片引用，但仍属于聊天模式；没有路径时，使用包含目标附件的最少会话图片数量。只有用户在消息正文中显式给出的本地路径才触发完整素材包，不要因为附件没有路径而停止。

仅在以下情况提问：附件无法读取、商品轮廓完全不可辨，或存在多个明显不同商品且当前要求无法确定目标。一般模糊、不确定材质、看不清小字都使用保守生成，不阻止启动。

## 商品真值优先级

按以下顺序解决冲突：

1. 用户在当前任务中明确说明的真实商品信息。
2. 清晰商品正面图。
3. 同一商品的多个一致视角。
4. 清晰包装、Logo、文字和结构细节图。
5. 模糊商品增强候选，只能作为自动锁定中的不确定推断。

风格参考图永远不能覆盖 1–4。看不清的信息写入 `uncertainties`，不要猜测型号、功效、材质、规格或品牌文字。

## 项目目录

单图输入以文件名主干作为项目名；目录输入以目录名作为项目名。默认创建同级目录 `项目名-视频素材包`。

```text
项目名-视频素材包/
  source-manifest.json
  product-profile.json
  creative-brief.md
  storyboard.json
  storyboard.md
  keyframes/
    shot-01-hook.png
    shot-02-hero.png
    shot-03-use.png
    shot-04-detail.png
    shot-05-ending.png
  prompts/
    flow.md
    capcut.md
    universal.json
  qc-report.md
  failed.txt
```

`failed.txt` 只在仍有失败时需要。

## 完整流程

### 1. 选择输入路径

聊天附件走“聊天上传极速模式”，不运行文件预检。只有用户消息正文中显式提供本地文件或目录路径时才继续以下文件流程。

### 2. 预检

从 Skill 目录运行：

```text
python scripts/preflight_product_video.py --input "<路径>"
```

用户指定规格时追加 `--target-ratio`、`--shots`、`--duration` 或 `--platforms`。读取生成的 `source-manifest.json`。脚本只提供客观尺寸和基于路径的角色提示，不能替代视觉判断。

### 3. 查看和分类

逐张查看本地图片。记录角色、可见事实、冲突和不确定项。模糊风格图只提取：

- 场景类别和空间层次
- 主光方向、软硬度和色温
- 主色、辅色和对比度
- 镜头高度、景别和构图
- 可复用的背景材质、道具和氛围

不要从模糊风格图复制商品细节或文字。

### 4. 模糊商品增强候选

只有当商品真值图不足时才生成。增强目标是提高可辨识度和构图完整性，不是恢复隐藏的真实细节。输出候选后，把模型补出的任何文字、Logo、接口或细节标成未验证。

### 5. 商品身份卡和创意方案

写入 `product-profile.json` 和 `creative-brief.md`。创意方案必须围绕可见商品，不得把推测卖点写成事实。

### 6. 五镜头分镜

默认 10 秒成片，每镜头 2 秒：

1. `hook`：快速建立场景和视觉吸引，第一帧已有商品主体。
2. `hero`：清晰展示商品整体。
3. `use`：展示合理使用环境或动作。
4. `detail`：突出真实可见的材质或结构。
5. `ending`：稳定、干净的商品定格。

先自动选择一个视频方向并贯穿五镜头：用途不明的单张商品图默认使用 `reveal`；只有图片或用户文字明确支持时才选 `feature_showcase`、`in_action` 或 `transformation`。一个短片只传达一个创意重点。五镜头共用同一套色彩、灯光、场景世界和主要运镜语言；第一镜头 2 秒内清楚出现商品，结尾镜头稳定保持约 2 秒。

平台实际生成时长若更长，提示用户后期截取，不为了凑时长加速到不自然。

### 7. 自动锁定或审阅

极速模式把 `confirmation_status` 写为 `auto_locked`，冻结可见商品事实并直接执行。用户明确要求审阅模式时，才展示图片分类、商品身份卡、不确定项、增强候选和分镜摘要；确认后改为 `confirmed`。

### 8. 串行生成关键帧

顺序处理 `shot-01` 到 `shot-05`。每个镜头：读取 prompt 规则、生成一张、保存、视觉质检、必要时在当前镜头内重试，完成后再进入下一张。

### 9. 平台提示词和校验

从同一份 `storyboard.json` 生成 Flow、CapCut 和通用 JSON，避免三套内容漂移。运行校验脚本并按报告补缺。

## 商品身份卡

`product-profile.json` 使用以下最小结构：

```json
{
  "schema_version": "1.0",
  "project_name": "项目名",
  "confirmation_status": "auto_locked",
  "category": "只写可确认类别",
  "visible_facts": ["可直接从商品图确认的事实"],
  "colors": ["主色"],
  "materials": ["仅确认或明确提供的材质"],
  "brand_text": ["清晰可见文字"],
  "must_preserve": ["外形、结构、颜色、数量等"],
  "uncertainties": ["看不清或冲突的信息"],
  "source_images": ["商品真值图路径"]
}
```

极速模式使用 `auto_locked`，审阅模式由用户确认后使用 `confirmed`。两种状态都只锁定可见或用户明确提供的事实；不确定营销功效不得进入提示词。

## 分镜结构

`storyboard.json` 是提示词的唯一真源：

```json
{
  "schema_version": "1.0",
  "project_name": "项目名",
  "aspect_ratio": "9:16",
  "target_duration_seconds": 10,
  "video_type": "reveal",
  "creative_message": "让商品被看清并记住",
  "visual_language": "统一色彩、灯光、场景世界和主要运镜语言",
  "product_profile_path": "product-profile.json",
  "shots": [
    {
      "id": "shot-01",
      "sequence": 1,
      "purpose": "hook",
      "duration_seconds": 2,
      "scene": "场景",
      "first_frame_state": "关键帧中的明确起始状态",
      "product_action": "商品或环境动作",
      "motion": "一个主要运镜和最多两个可观察动作",
      "last_frame_state": "镜头结束时可继续衔接的明确状态",
      "continuity_anchors": ["商品朝向", "商品尺度", "主光方向", "背景锚点"],
      "shot_size": "close_up",
      "camera_angle": "three-quarter front",
      "camera_movement": "slow push-in",
      "keyframe": "keyframes/shot-01-hook.png",
      "prompt_en": "英文视频提示词",
      "negative_prompt_en": "英文负面约束"
    }
  ]
}
```

`purpose` 默认顺序固定为 `hook, hero, use, detail, ending`。镜头时长总和与目标成片时长误差不超过 0.1 秒。

## 恢复与覆盖

- 输出存在且通过质检时复用。
- 输出缺失或失败时只补对应镜头。
- `product-profile.json` 已锁定（`auto_locked` 或 `confirmed`）时，不因恢复任务重新猜测商品。
- 用户明确要求覆盖时，保留原始输入和已锁定商品档案，只重做生成内容。
- 不删除用户输入或其它项目目录。
