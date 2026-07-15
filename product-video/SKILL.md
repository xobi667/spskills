---
name: product-video
description: 使用 Codex 内置视觉与生图能力，把用户上传或指定路径的真实商品素材零确认制作成自然、日常、物理可信的五段竖屏商品视频方案：自动识别窗帘/窗纱、窗膜、玻璃贴、姓名贴、杯口封膜、桌面覆盖、节庆装饰等品类，建立同款证据包和合法动作状态机，校验“生活需求→准备→操作→验证→回到生活”的完整闭环，再串行生成 6 张连续 9:16 锚点、5 条首尾帧视频提示词和克制文案。适用于“上传产品图直接开始”“商品出场景图/分镜”“导演台”“Seedance”“Flow”“视频生成”等；不需要外部 API Key，不使用本地大模型。
---

# 自然商品视频导演台

把真实商品放进一件普通生活小事，完成一个能看懂、能接续、不过度表演的五段闭环。默认追求可信电商实拍，不追求黑棚、大片感、概念机关或夸张功效。

开始前完整读取 [references/prompts.txt](references/prompts.txt)、[references/shot-copy-guide.md](references/shot-copy-guide.md) 和 [references/lessons.md](references/lessons.md)。根据识别出的路线，再读取 [references/category-playbooks.md](references/category-playbooks.md) 的“共同自然主义”“参考图角色包”“六锚点日常闭环”“硬失败清单”和对应路线章节。

## 默认交付合同

- 零确认：主要商品能辨认就直接开始，不询问品名、平台、比例或方案。
- 必须使用已安装的 `$imagegen` Skill 和 Codex 内置 `image_gen`；不得用外部图片 API、本地模型、SVG、Canvas、Pillow、拼图或占位图代替。
- 默认生成 6 张完整 9:16 锚点，组成 `01→02` 至 `05→06` 五段视频；严格串行，一次只生成一张完整图片。
- 生图前必须在内存中建立参考图角色包、事实表和导演表，并让 `scripts/check_plan.py` 经 UTF-8 stdin 校验通过。
- 全片只讲一个有证据的重点，使用同一个人、同一个空间、一个普通任务和一条连续动作链。
- 每对相邻锚点必须能由一个主要动作到达；需要跨越多个不可省略步骤时先修锚点，不得靠冗长提示词补救。
- 允许窗帘垂坠、网面张紧、卷材展开、贴纸剥离、薄膜贴合等品类合法形变；必须锁定同一 SKU 的颜色、图案、文字、部件和材料行为。
- 功能/功效只能由清晰的 `result` 证据授权。目录名、包装文案、安装过程或品类常识都不能单独证明隔热、防水、防蚊、隔音、耐久等结果。
- 成果目录只允许 `01.png` 至 `06.png` 和 `导演台.txt`。硬失败时图片可少，但仍只保留一个 TXT。
- 本地完成后检测 `lark-cli`，把成功图片和纯文本投递给当前登录的飞书本人；飞书不可用不能阻塞本地成果。

## 1. 锁定输入与同款产品族

按以下优先级找素材：用户给出的文件、用户给出的目录、消息附件。目录输入先用 `rg --files` 枚举常见图片，再按自然文件名和相邻目录寻找 `主图/详情/SKU/安装/视频/说明` 素材。

不要信任路径名本身。公司目录存在“窗帘文件夹里是窗膜”等混放情况；必须用 `view_image` 视觉核对产品类型、SKU、颜色、图案、边框、卷芯、配件和印刷。只把身份一致的素材归为同一个产品族，禁止跨款拼接。

证据优先级：明确修改要求/实拍 SKU 图 → 原始商品图 → 结构细节图 → 详情页 → 主图合成 → AI 场景图。低优先级素材不能覆盖高优先级约束；相互冲突的百分比和功效一律进入不确定项。

建立参考图角色包：

- `identity_truth`：最清晰的同款正面/SKU 图，必须有。
- `scale_context`：商品与窗框、杯子、手指、桌面的真实比例。
- `installation_truth`：真实安装顺序、工具和接触面。
- `action_truth`：手、机器或商品的真实运动。
- `result_truth`：唯一能授权可见使用结果的素材。
- `exact_print_truth`：姓名、字样、图案重复和方向；标签/印刷品优先寻找。
- `world_plate`：01 通过预览后固定的房间、窗框、家具和主光。

同一图片可以承担多个角色，但每个角色都要写明来源并确认 `same_sku` 或 `same_variant`。找不到的角色记录为不确定项，不补造。

如果 `identity_truth` 只存在于会话附件、没有本地路径，先用覆盖该附件的最小 `num_last_images_to_include` 生成一张中性背景的临时 `product_truth_proxy.png`：只保留可见轮廓、比例、颜色、部件和标签布局，模糊文字继续模糊。保存到系统临时目录，用 `view_image` 对照原附件做身份 QC，最多定向重试一次；失败就停止，不能让创意锚点冒充真值。后续锚点只用本地代理和 `referenced_image_paths`，完成后删除代理；同一次调用不得混用两种引用机制。

首次生图前初始化目录：

```text
python "<skill_dir>/scripts/deliver_result.py" init --run-id "<run_id>" --source "<源图或目录>" --base-dir "<输出根目录>"
```

只有会话附件没有路径时省略 `--source`，并传 `--product-name 商品`。从 stdout JSON 读取 `project_dir`，不要保存 JSON。

## 2. 建立逐条证据

为每条 `F1...Fn` 记录：

- `observed`：一条可见事实。
- `source` 与 `region`：具体来源和可见区域。
- `evidence_kind`：`identity | scale | installation | action | result | exact_text`。
- `confidence`：只用 `high | medium`；低置信内容进入不确定项。
- `allowed_claims`：允许的 `observed | aesthetic | functional`。

只有 `result` 事实可以授权 `functional`。包装上写着某功效，只能证明“包装出现该字样”，不能证明功效本身。模糊文字保持模糊；没有清晰 `exact_print_truth` 时不生成新的可读姓名、Logo 或参数。

## 3. 自动路由品类与材料形变

同时依据图像内容、实际安装方式和目录线索选择一条路线：

| route | 典型商品 | form_factor |
|---|---|---|
| `window_textile` | 窗帘、门帘、窗纱、卷帘 | `textile_panel / tensioned_mesh / roll_to_sheet` |
| `window_film` | 遮阳、磨砂、隐私、装饰窗膜 | `roll_to_sheet` |
| `adhesive_decal` | 玻璃贴、窗贴、墙贴、标识贴 | `decal_transfer` |
| `small_label` | 姓名贴、文具贴、小标签 | `decal_transfer` |
| `sealing_film` | 杯口封膜、封装膜、热封膜卷材 | `consumable_film` |
| `surface_covering` | 桌布、桌垫、墙纸、保护膜、地垫 | `textile_panel / roll_to_sheet` |
| `seasonal_decor` | 节庆窗贴、灯笼、挂饰、门贴 | 按实物选择 |
| `fallback_household` | 其他家居小商品和配件 | 保守选择 |

读取对应 playbook 的动作白名单、物理锁和禁忌。目录名只能帮助路由；任何具体结构约束以同款图和说明为准。例如只有来源明确证明某款拉链窗纱底部不可掀开时，才把它写入该 SKU 的身份/安装锁。

## 4. 设计一件普通生活小事

不再先想三套“创意机关”。先选一个最符合来源证据的普通任务，并填写：

```text
同一个人 + 同一个真实空间 + 一个小需求
→ 商品准备好
→ 测量/清洁/对齐完成
→ 关键安装或使用动作完成
→ 一个克制的可见检查
→ 手离开，原来的生活/工作继续
```

六个锚点固定阶段：

1. `need`：日常正在发生，出现小需求。
2. `ready`：商品和必要工具进入动作范围。
3. `aligned`：测量、清洁、对齐或放置完成。
4. `applied`：关键拉合、安装、贴合、封合或摆放完成。
5. `verified`：用来源允许的动作检查边缘、位置、外观或结果。
6. `resumed`：人物回到阅读、休息、开窗、收书包、递饮料等原活动。

五段岗位为 `daily_trigger → prepare → apply → verify → return`。每段新增内容可为 `context`、`task_progress`、`product_fact` 或 `result`；不要为了凑卖点强迫五段都讲产品事实。

完成六个静态端点后，按 `shot-copy-guide.md` 做相邻可达性检查。默认一段只允许一个动作重点和一个物理后果。先明确交付路径：纯首尾帧 I2V 使用 `motion_only_i2v` 或 `chronological_shot`，两者都不得切镜；只有明确交给多镜头引擎或后期剪辑时才用 `editorial_bridge`，并恰好使用一次门框遮挡或匹配动作转场。转场不能掩盖换商品、跳关键步骤、工具消失或材料状态突变。

## 5. 固定自然主义档案

在导演表中明确一个 `realism`：普通地点、具体时段、一个主光源、35–50mm 等效视角、一名成年人/最多两只手、2–3 个有因果的生活痕迹、背景正在发生的普通活动、自然电商实拍风格。

默认排除：黑棚、展示底座、漂浮、粒子、火花、烟雾、光束、体积光、能量特效、豪宅样板间、风暴式布料、完美对称英雄位、夸张表情、重复商品和戏剧化功效对比。

相机只允许锁定、轻微手持保持、短距离跟随/横移、轻缓俯仰或一次小幅推近。每段只有一个相机行为；运动必须服务于接触、动作或结果可读性。微距全片最多一次。

## 6. 校验导演表

按 [references/prompts.txt](references/prompts.txt) 的 `DIRECTOR PLAN JSON CONTRACT` 在内存中组装 JSON。每个段落必须精确连接相邻 `state_id`，动作的 `end_state` 必须就是尾锚点状态，并写清：

```text
prompt_mode + visual_focus + visible_change + physical_consequence
主体 + 合法 action_family + 接触点/路径 + 尾端状态
一个 camera.role、一个相机行为及动机 + 一个直接环境响应
事实编号/主张权限 + copy_role + copy_visual_evidence 或“无”
```

经 stdin 校验：

```text
<director-plan-json> | python "<skill_dir>/scripts/check_plan.py" --stdin
```

只有 stdout 为 `{"ok":true,"errors":[]}` 才能开始。失败时只在内存中修复对应字段并重跑。再人工检查：动作是否符合该品类物理、是否能从首帧真实到达尾帧、06 是否确实回到 01 的生活任务。

## 7. 用 01 做场景预览，再串行完成锚点

01 是正式锚点，也是场景预览关。它必须先通过：同款商品、普通地点、可信比例、自然主光、合理生活痕迹、没有广告棚特效。通过后把它设为 `world_plate`，再生成 02–06；这是对参考资料“先用场景图预览并修 prompt，再进入视频生成”的落地。

每张执行：

1. 按 prompts 模板只描述当前静态端点，不把六帧故事塞进一张图。
2. 01 引用 `identity_truth` 和必要的比例/场景参考；02–06 持续引用永久商品真值、上一张合格锚点和 `world_plate`。工具有引用数量限制时，优先级是身份真值 → 上一锚点 → 当前动作/印刷真值 → world plate。
3. 调用一次 `image_gen`，保存真实 PNG 为 `01.png` 至 `06.png`。
4. 用 `view_image` 检查身份、图案/文字、品类物理、接触、动作端点、场景连续和自然感。
5. 失败时只写一个最关键的可见缺陷，定向重试当前锚点一次；工具无结果可额外安全重试一次。

每次记录 `anchor_start`、`anchor_saved`、`anchor_retry` 或 `anchor_failed`。当前锚点硬失败时停止后续生图，保留已成功锚点并完成 TXT。

```text
python "<skill_dir>/scripts/deliver_result.py" log --output-dir "<项目目录>" --run-id "<run_id>" --event "<事件>" --source "<源图>" --shot "<01至06>" --status "<状态>" --output "<输出图>" --detail "<安全短原因>"
```

## 8. 整条复核与视频提示词

连续查看 01–06，先修最早的断点。硬失败包括串款、文字/图案变化、布料违反重力、网面失去张力、薄膜变硬板、卷材方向跳变、贴纸浮空、机器动作不可能、接触消失、房间/主光漂移、未授权功能结果和结尾英雄海报。

首尾帧已经定义人物、商品、房间、光线和构图。视频提示词只描述两帧之间的可见变化，使用一个流动段落并按以下顺序：

```text
唯一动作 → 接触点/路径 → 一个可见物理后果
→ 一个相机行为及镜头岗位 → 真实速度并停稳
→ 精确落到尾帧 → 一句短身份/场景连续性锁
```

使用字面、具体、按时间顺序的描述，不写“高级、震撼、电影感、丝滑、8K”。不要重新罗列首帧已经可见的外貌、家具和工具，也不要写第二事件、第二运镜、新人物或新道具。只有导演表已批准的 `occlusion`/`match_action` 才能写转场。目标引擎为 Wan 首尾帧时优先中文；需要 LTX 风格时保持单段、直接从动作开始且不超过 200 词。

按交付路径选择 [prompts.txt](references/prompts.txt) 中的 profile：Veo/Flow/Runway 且源帧信息充分时用 `motion_only_i2v`，少重述画面；LTX/Wan 或引擎需要完整描述时用 `chronological_shot`。这两种纯 I2V profile 都只能完成同一个已校验动作且 `transition=none`。只有成片明确通过多镜头引擎或 NLE 剪辑时才使用 `editorial_bridge`；它允许同一任务中的两个短拍点和一次有动机的切镜，必须在导演台标注“剪辑版”，不得冒充纯首尾帧连续生成。

## 9. 文案与 TXT

文案可以 0–3 条，不强制结尾口号。先分配 `need | condition | proof | closure` 岗位，再写句子；准备和关键操作段默认写“无”，不为清洁、测量、刮平、裁边、揭纸或压合配说明书字幕。每条必须绑定目标锚点中的具体对象、必要条件或有证据结果，并在导演表写出 `copy_visual_evidence`；删除画面后仍能套到任意商品的句子一律删除。条件性功能必须把条件写入句子。禁止“细节自会说话、留下这一眼、轻松搞定、不止好看、一步到位、质感拉满”等空话。

严格输出：

```text
项目：<商品名>
规格：9:16｜5 段｜每段 4–6 秒
商品路线：<route>｜<form_factor>
日常场景：<普通地点、人物和小任务>
完整闭环：<需求→准备→操作→验证→回到生活>
传播重点：<一个证据支持的重点>

01｜<短镜头名>
生活动作：日常触发
首尾帧：01.png → 02.png
视频提示词：<一个具体段落>
字幕/旁白：<具体短句或“无”>

……

05｜<短镜头名>
生活动作：回到生活
首尾帧：05.png → 06.png
视频提示词：<一个具体段落>
字幕/旁白：<具体短句或“无”>
```

正文经 stdin 交给唯一落盘者：

```text
@'
<内存中的 TXT 正文>
'@ | python "<skill_dir>/scripts/deliver_result.py" deliver --output-dir "<项目目录>" --run-id "<run_id>" --image "01=<01路径>" --image "02=<02路径>" --image "03=<03路径>" --image "04=<04路径>" --image "05=<05路径>" --image "06=<06路径>" --result-text-stdin
```

投递仅限当前登录本人；其他人、群聊、公开文档或云盘位置必须另行确认。

## 10. 生图不可用

没有内置 `image_gen`、附件无法建立可靠身份真值或工具连续失败时，不调用外部 API、不用本地模型或绘图库伪造成品、不创建占位图。仍按新版结构输出五条备用视频提示词和文案，并在规格行后加 `生图：失败（准确原因）`。已成功锚点按原编号传入，缺失项不传。

实际调用过内置生图后，遵守 `$imagegen` 的会话展示规则：保存、QC、日志和投递静默完成，最终不追加下载说明、图片摘要或追问。
