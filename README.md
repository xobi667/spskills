# spskills

可直接安装到 Codex 的 Skills 集合。

## product-video

上传一张商品图就开始：Codex 用内置图片生成能力逐张生成 5 张独立的 9:16 商品视频场景关键帧，并输出 5 条可用于 Google Flow、CapCut 或通用图片转视频工具的英文提示词。

- 默认零确认，先出图，不先写方案文档。
- 五张图固定为 Hook、Hero、Use、Detail、Ending，不生成五格联系表。
- 一次只生成一张，当前图片落盘后才生成下一张，降低商品串图和变形。
- 图片与唯一的 UTF-8 BOM TXT 直接放在原商品图所在目录；不建素材包子目录，不生成运行时 Markdown 或 JSON。
- 自动锁定商品外形、比例、颜色、数量、Logo/标签位置；模糊区域保持中性，不补造文字、结构、配件、功能或规格。
- 不需要外部 API Key，不安装或运行本地图片/视频大模型。
- 自动检测本机 `lark-cli`：优先以当前登录用户身份把 5 张图和纯文本发给本人，动态 bot 仅作后备；飞书不可用时仍完整保存本地。
- 安全运行日志默认写入桌面的 `生图日志.txt`，不记录 token、用户 ID 或聊天 ID。

### 安装

在 Codex 中运行：

```text
使用 $skill-installer 安装 https://github.com/xobi667/spskills/tree/main/product-video
```

也可以把 `product-video` 目录复制到：

```text
~/.codex/skills/product-video
```

安装或更新后新建一个 Codex 会话，让 Skill 列表重新加载。

### 使用

选择“商品视频工作台”，直接上传商品图并发送；也可以附图后输入：

```text
$product-video 直接开始
```

本地文件或目录也可以直接指定：

```text
$product-video D:\商品项目\主图.png
$product-video D:\商品项目
```

默认输出位于原图目录：

```text
主图-01-hook.png
主图-02-hero.png
主图-03-use.png
主图-04-detail.png
主图-05-ending.png
主图-视频提示词.txt
```

如果当前 Codex 会话没有提供内置生图工具，Skill 不会用本地占位图冒充结果；它会把失败原因与五条提示词写进同一个 TXT。
