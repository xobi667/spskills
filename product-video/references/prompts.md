# Product Video Prompt Rules

## 目录

- 优先级
- 风格提取
- 模糊商品增强
- 极速五格分镜
- 关键帧模板
- 视频模板
- 镜头差异
- 失败补跑

## 优先级

1. 商品真实性高于风格和画面冲击力：外形、比例、颜色、材质、数量、Logo 和标签位置不得改。
2. 商品图是事实来源；风格图只提供色调、灯光、环境、构图、景深和镜头语言。
3. 看不清的信息不得补造。模糊 Logo 或文字保持不突出或避开特写；增强图只是未验证候选。
4. 极速五格分镜可一次生成一张五格联系表；生成独立关键帧时一次只处理一个镜头，一个镜头只使用一个主要商品动作和一个主要运镜，禁止在同一 prompt 中切场景。
5. 默认不生成字幕、CTA、价格或卖点文字；清晰可见的包装文字尽量原样保留。画面叠字留给后期剪辑。
6. prompt 顺序固定为：商品锁定 → 镜头目标 → 场景/动作 → 构图/机位 → 运镜 → 灯光/风格 → 结束状态 → 禁止项。
7. 每条视频 prompt 从已生成关键帧的 `first_frame_state` 开始，只写一个主要运镜和最多两个可观察动作，并以 `last_frame_state` 收束；相邻镜头重复必要的 `continuity_anchors`。

## 风格提取

从 `style_reference` 只提取：

```text
palette: 主色与点缀色
lighting: 光向、软硬、色温、对比度
set: 环境、背景材质、道具密度
composition: 主体位置、留白、层次
lens_depth: 景别、透视、景深
mood: 商业氛围
motion_language: 一个适合的主要运镜
```

忽略参考图中的商品、人物身份、Logo、文字、包装、尺寸和功能。

## 模糊商品增强

每张模糊商品图单独处理，使用：

```text
Create a conservative visibility-enhanced candidate from the supplied product reference.

Preserve only the silhouette, proportions, color blocks, material cues, part count, seams, edges, openings, controls, logo position, and label layout that are visibly supported by the source. Improve exposure, denoising, edge clarity, recoverable texture, and background cleanliness without redesigning the product.

Do not invent or complete unreadable text, logos, ports, buttons, accessories, patterns, hidden surfaces, specifications, or packaging details. Keep uncertain regions visually neutral. Do not add promotional copy, badges, labels, or watermarks.

This output is an unverified review candidate, not a factual reconstruction of hidden details.
```

不要把候选新增的信息反写为商品事实。极速模式不等待确认；候选只能提供可见轮廓和色块，不得把未验证细节写入商品身份锁。用户明确选择审阅模式时才展示候选。

## 极速五格分镜

聊天附件默认首先生成一张五格场景分镜图，使用一个生图请求完成即时可见结果：

```text
Create one polished vertical 9:16 e-commerce storyboard contact sheet containing exactly five visually distinct cinematic panels for the same product. The sequence communicates one visual idea only: {CREATIVE_MESSAGE}.

PRODUCT IDENTITY LOCK: Use the uploaded product image as the only source of truth. Keep the exact same single product in every panel: identical silhouette, proportions, color, material cues, part count, logo position, visible label layout, and packaging geometry. Do not redesign, duplicate, relabel, recolor, simplify, or add accessories. Keep unreadable details neutral instead of inventing them.

STYLE: {STYLE_DESCRIPTION}. Lock one shared palette, lighting setup, scene world, lens character, and motion language across all five panels. If no style reference was uploaded, choose a coherent premium commercial setting that does not imply an unverified product function.

PANEL ORDER:
1. Hook — product visible immediately in an attention-catching establishing composition.
2. Hero — clean full-product hero view.
3. Use — conservative lifestyle placement without demonstrating an unverified function.
4. Detail — close view of a clearly visible material, shape, or construction detail; avoid uncertain small text.
5. Ending — stable premium product end frame with clean negative space.

Make the five panels read as one coherent 10-second vertical video sequence with consistent lighting, world, product scale, and color, while varying shot size and camera angle. Use clean panel boundaries and no decorative frame.

Do not add panel numbers, captions, titles, subtitles, CTA, price, badges, specifications, watermarks, UI, invented packaging text, extra products, hands crossing the product, collage labels, or split-screen text. The only text allowed is clearly legible text physically present on the real product.
```

五格必须是同一商品和同一视觉世界。用户要求拆分时，以这五格的构图意图为准重新生成独立关键帧，不直接低质量裁切联系人表。

## 关键帧模板

```text
Create one photorealistic vertical 9:16 e-commerce video keyframe for {SHOT_ID}.

PRODUCT IDENTITY LOCK: The supplied product reference is the only source of truth. Preserve its exact silhouette, proportions, color, material, part count, distinctive construction, logo placement, visible label layout, and confirmed packaging text. Do not redesign, simplify, duplicate, recolor, relabel, or add accessories. If a detail is unclear, keep it visually neutral rather than inventing it.

STYLE ROLE LOCK: The supplied style reference is style-only. Use only its palette, lighting, environment, composition, depth, mood, and camera language. Do not copy any product, person, text, logo, packaging, or brand from it.

SHOT PURPOSE: {PURPOSE}
SCENE: {SCENE}
PRODUCT PLACEMENT OR ACTION: {PRODUCT_ACTION}
SHOT SIZE AND ANGLE: {SHOT_SIZE}, {CAMERA_ANGLE}
COMPOSITION: {COMPOSITION}; keep safe framing for vertical 9:16.
LIGHTING AND STYLE: {LIGHTING_STYLE}
EXPECTED END FRAME: {END_STATE}

Make the real product dominant, physically plausible, sharp, clean, and commercially polished. Render realistic contact shadows, reflections, scale, and material response. Keep the important product area readable and unobstructed.

Do not add captions, slogans, UI, badges, specifications, watermarks, or decorative typography. Preserve only clearly legible text physically present on the product.

AVOID: product deformation, changed proportions, changed color or material, extra or missing parts, duplication, invented packaging or text, altered logo, floating objects, impossible reflections, warped hands, clutter, watermark, UI, frame, collage, split screen, or low-resolution artifacts.
```

比例由用户覆盖时替换首句。每次 prompt 只描述当前镜头，不汇总其它镜头场景。调用时只传已锁定的必要商品视角和一张当前风格图，不混入其它镜头关键帧。

## 视频模板

```text
Animate the supplied identity-locked, QC-passed keyframe into one continuous vertical product shot lasting about {DURATION_SECONDS} seconds.

Keep the product completely identity-locked: its exact shape, proportions, color, material, part count, logo, labels, and placement must remain stable in every frame.

ACTION: {PRODUCT_ACTION}
CAMERA: {CAMERA_MOVEMENT}; maintain {SHOT_SIZE} from {CAMERA_ANGLE}.
ENVIRONMENT MOTION: {ENVIRONMENT_MOTION}
LIGHTING: {LIGHTING_STYLE}, stable with no flicker.
END STATE: {END_STATE}; finish with a clean hold suitable for editing.

Use physically plausible motion and temporal consistency. No cuts or scene changes.
AVOID: morphing, melting, bending, duplication, disappearing parts, invented surfaces, label or text changes, camera jumps, focus pumping, lighting flicker, warped hands, extra objects, subtitles, CTA, watermark, or UI.
```

商品本身不应运动时，让商品静止，只移动相机、光影或少量背景元素。

## 镜头差异

- `hook`：第一帧已有可辨识商品，用环境或镜头快速建立吸引力。
- `hero`：商品整体最清晰，使用干净背景和稳定构图。
- `use`：只展示合理且不虚构功效的使用动作；涉及手部时减少遮挡。
- `detail`：只放大真实可见材质、结构或包装细节，避开不确定文字。
- `ending`：商品稳定、构图完整、留出自然收尾空间，不新增 CTA。

同一项目保持场景世界、色彩、时间段和商品尺度一致，同时让景别和运动各有差异。

## 失败补跑

每次只修当前失败点，不推翻已通过内容：

```text
Regenerate only {SHOT_ID}. The previous attempt failed because: {DEFECTS}.
Keep all identity-locked product facts, scene intent, framing, lighting, and style unchanged. Correct only the listed defects. Do not reuse or modify any other shot.
```

比例错误时使用：

```text
Generatively extend the QC-passed composition to an exact vertical 9:16 canvas. Preserve the product size, geometry, and locked scene. Extend only background-safe areas; do not crop, stretch, duplicate, or distort the product.
```
