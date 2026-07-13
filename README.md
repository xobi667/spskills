# spskills

Codex Skills 集合。

## product-video

上传商品图后，使用 Codex 内置视觉与图片生成能力，零确认生成一张无叠字的 9:16 五格场景分镜图；也支持独立关键帧、Google Flow、CapCut 和通用视频提示词素材包。

- 不需要外部 API Key。
- 不安装或运行本地图片、视频大模型。
- 自动区分商品真值图和风格参考图。
- 模糊商品图采用保守增强，不补造文字、Logo、接口或功能。

### 安装

在 Codex 中运行：

```text
使用 $skill-installer 安装 https://github.com/xobi667/spskills/tree/main/product-video
```

也可以把 `product-video` 目录复制到：

```text
~/.codex/skills/product-video
```

安装后建议新建 Codex 会话，让 Skill 列表重新加载。

### 使用

选择“商品视频工作台”，上传一张商品图并发送；或附图后输入：

```text
$product-video 直接开始
```

默认立即输出一张 9:16 五格分镜图。后续可以继续要求：

```text
拆分五个镜头
单独生成第 3 镜头
输出 Flow 和 CapCut 提示词
根据 D:\商品项目 生成完整素材包
```
