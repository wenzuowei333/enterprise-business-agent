# 本地图片批处理工具

这是一个本地运行的 Python 图片批处理工具，用于商品图自动抠图、统一白底标准尺寸、叠加客户水印并批量导出。程序使用 `rembg` 在本机进行 AI 抠图，不调用 remove.bg、阿里云、百度云、腾讯云等第三方在线 API，也不会上传图片到云端。

## 功能

- 批量读取 `input` 文件夹中的图片；
- 支持 `jpg`、`jpeg`、`png`、`webp`、`bmp`；
- 使用 `rembg` 本地自动抠图；
- 根据 alpha 通道裁剪主体有效区域；
- 按比例缩放主体，不拉伸变形；
- 输出统一尺寸，默认 `800x800`；
- 默认合成为纯白背景图；
- 支持多个图片水印；
- 支持水印位置、大小、透明度、边距配置；
- **支持水印混合模式**：普通叠加、滤色（提亮）、正片叠底（加深）、叠加、柔光；
- **支持 PSD 光效模板**：自动提取光效图层，跳过纯色填充层；
- 单张图片失败不会中断整个批处理；
- 处理日志写入 `logs/process.log`。

## 项目结构

```text
image_batch_processor/
  main.py
  config.json
  requirements.txt
  install.bat
  README.md
  input/
  output/
  watermarks/
  logs/
```

## 一键安装

双击 `install.bat`，脚本自动完成 Python 检测、虚拟环境创建、依赖安装和目录初始化。

详细安装说明见后文。

## 修改输出尺寸

打开 `config.json`，修改：

```json
{
  "output_width": 800,
  "output_height": 800,
  "margin_ratio": 0.08
}
```

说明：

- `output_width`：输出图片宽度；
- `output_height`：输出图片高度；
- `margin_ratio`：主体四周留白比例。

不同 `margin_ratio` 效果（以 800×800 画布为例）：

```text
margin_ratio=0.02  主体占96%  极少留白
margin_ratio=0.05  主体占90%  少量留白
margin_ratio=0.08  主体占84%  默认，电商标准
margin_ratio=0.12  主体占76%  较宽松
margin_ratio=0.20  主体占60%  大留白
```

## 修改背景颜色

默认输出白底图：

```json
{
  "background_color": [255, 255, 255],
  "transparent_background": false
}
```

如果需要其他纯色背景，例如浅灰色：

```json
{
  "background_color": [245, 245, 245]
}
```

默认不输出透明背景。只有把 `transparent_background` 改成 `true` 并输出 `png` 或 `webp` 时，才会保留透明背景。

## 修改输出格式

默认输出 JPG：

```json
{
  "output_format": "jpg",
  "jpeg_quality": 95
}
```

可选格式：

```text
jpg, jpeg, png, webp
```

如果输出 JPG，程序会自动转换为 RGB，最终不会带透明通道。

## 配置水印

`config.json` 中的 `watermarks` 支持多个水印：

```json
{
  "watermarks": [
    {
      "enabled": true,
      "path": "watermarks/main_watermark.png",
      "position": "bottom_right",
      "scale_ratio": 0.22,
      "opacity": 0.55,
      "margin": 30,
      "blend_mode": "normal"
    },
    {
      "enabled": false,
      "path": "watermarks/tile_watermark.png",
      "position": "tile",
      "scale_ratio": 0.18,
      "opacity": 0.18,
      "margin": 120,
      "blend_mode": "normal"
    }
  ]
}
```

字段说明：

- `enabled`：是否启用该水印；
- `path`：水印文件路径；
- `position`：水印位置；
- `scale_ratio`：水印宽度占输出图宽度的比例；
- `opacity`：透明度/强度。普通模式范围 `0` 到 `1`；光效模板可大于 `1`（如 `10.0`）；
- `margin`：边距，单位为像素。平铺水印时表示水印之间的间隔；
- `blend_mode`：混合模式，默认 `normal`。

支持的位置：

```text
top_left      左上角
top_right     右上角
bottom_left   左下角
bottom_right  右下角
center        居中
tile          满铺平铺
```

## 水印混合模式

`blend_mode` 控制水印与底图的合成方式：

| blend_mode | 效果 | 典型用途 |
|-----------|------|---------|
| `normal` | 普通半透明叠加 | 品牌角标、防盗水印 |
| `screen` | 滤色，提亮底图 | **光效模板**（PSD 光效叠加） |
| `multiply` | 正片叠底，加深底图 | 纹理/质感叠加 |
| `overlay` | 叠加，暗处更暗亮处更亮 | 对比度增强 |
| `soft_light` | 柔光，温和叠加 | 柔和光效 |

### 普通水印示例（品牌角标）

```json
{
  "enabled": true,
  "path": "watermarks/brand_logo.png",
  "position": "bottom_right",
  "scale_ratio": 0.22,
  "opacity": 0.6,
  "margin": 30,
  "blend_mode": "normal"
}
```

### 光效模板示例（PSD 滤色叠加）

```json
{
  "enabled": true,
  "path": "watermarks/light_template.psd",
  "position": "center",
  "scale_ratio": 1.0,
  "opacity": 1.0,
  "margin": 0,
  "blend_mode": "screen"
}
```

光效模板 `opacity` 调参：

```text
opacity=0.5   轻微提亮
opacity=1.0   适中（推荐起点）
opacity=3.0   明显光效
opacity=10.0  强烈光效
```

## PSD 水印模板

### 推荐方式（导出 PNG）

1. 用 Photoshop、Photopea、Affinity Photo 或其他 PSD 工具打开客户提供的 PSD；
2. 找到需要作为水印的图层或组合；
3. 导出为透明背景 PNG；
4. 放入 `watermarks` 文件夹；
5. 在 `config.json` 中引用该 PNG。

这是最稳定、最容易远程调试的方式。

### 直接使用 PSD

程序支持直接读取 PSD 文件作为水印。会自动处理：

- **跳过纯色填充层**：白色/纯色背景图层会被自动识别并跳过，只提取效果图层；
- **保留光效信息**：光效图层的 alpha 通道作为效果强度图，配合 `screen` 混合模式使用；
- **需要安装 `psd-tools`**：

```bash
pip install psd-tools
```

光效模板 PSD 使用示例：

```bash
python main.py --json --quiet --output-width 636 --output-height 636 --watermark-path "watermarks/light_template.psd" --watermark-position center --watermark-scale-ratio 1.0 --watermark-opacity 1.0 --watermark-margin 0 --watermark-blend-mode screen
```

## 运行程序

### 日常使用

双击 `run.bat`，或进入项目目录后执行：

```bash
python main.py
```

程序会自动：

- 读取 `config.json`；
- 创建必要文件夹；
- 批量处理 `input` 中的图片；
- 输出到 `output`；
- 生成日志到 `logs/process.log`。

也可以指定其他配置文件运行，适合测试不同尺寸或不同水印方案：

```bash
python main.py --config config_test_corner.json
```

## Agent 调用方式

如果由 OpenClaw 这类 agent 调用，推荐使用 `--json --quiet`，让 stdout 只返回结构化 JSON，便于程序解析：

```bash
python main.py --json --quiet
```

也可以不修改 `config.json`，直接通过命令行覆盖输入目录、输出目录、尺寸、日志路径和水印。推荐 agent 优先使用下面这种普通参数形式，避免不同 shell 对 JSON 引号转义不一致：

```bash
python main.py ^
  --json --quiet ^
  --input-dir input_batch2 ^
  --output-dir output_agent ^
  --output-width 800 ^
  --output-height 800 ^
  --log-path logs/agent_run.log ^
  --watermark-path watermarks/test_badge_watermark.png ^
  --watermark-position bottom_right ^
  --watermark-scale-ratio 0.25 ^
  --watermark-opacity 0.65 ^
  --watermark-margin 24 ^
  --watermark-blend-mode normal
```

返回 JSON 示例：

```json
{
  "status": "ok",
  "summary": {
    "total": 9,
    "success": 9,
    "failed": 0,
    "skipped": 0
  },
  "outputs": [
    {
      "input": "D:\\...\\input_batch2\\animal_2.jpg",
      "output": "D:\\...\\output_agent\\animal_2_result.jpg",
      "filename": "animal_2_result.jpg"
    }
  ],
  "failures": []
}
```

退出码约定：

```text
0   全部成功，或没有可处理图片
2   初始化失败，例如配置文件不存在、配置格式错误
3   rembg 后端初始化失败，例如依赖或模型问题
10  部分图片失败，但程序已处理完其他图片
```

适合 agent 使用的常用参数：

```text
--config                指定配置文件
--input-dir             覆盖输入目录
--output-dir            覆盖输出目录
--output-width          覆盖输出宽度
--output-height         覆盖输出高度
--output-format         覆盖输出格式，jpg/png/webp
--output-suffix         覆盖输出文件名后缀
--margin-ratio          覆盖主体留白比例
--background-color      覆盖背景色，例如 255,255,255
--log-path              覆盖日志路径
--watermark             用一个 JSON 对象指定水印，可重复传入多个
--watermarks-json       用 JSON 数组指定多个水印
--watermark-path        用普通参数指定单个水印，推荐 agent 使用
--watermark-position    单个水印位置
--watermark-scale-ratio 单个水印缩放比例
--watermark-opacity     单个水印透明度/强度
--watermark-margin      单个水印边距
--watermark-blend-mode  单个水印混合模式：normal/screen/multiply/overlay/soft_light
--json                  stdout 输出 JSON 结果
--quiet                 控制台不输出人类日志
```

如果要传多个水印，可以重复使用 `--watermark`，或使用 `--watermarks-json`。这属于高级用法，需要调用方正确处理命令行引号转义：

```bash
python main.py --json --quiet ^
  --input-dir input_batch2 ^
  --output-dir output_agent_multi ^
  --watermark "{\"enabled\":true,\"path\":\"watermarks/test_center_watermark.png\",\"position\":\"center\",\"scale_ratio\":0.45,\"opacity\":0.2,\"margin\":0,\"blend_mode\":\"normal\"}" ^
  --watermark "{\"enabled\":true,\"path\":\"watermarks/light_template.psd\",\"position\":\"center\",\"scale_ratio\":1.0,\"opacity\":1.0,\"margin\":0,\"blend_mode\":\"screen\"}"
```

输出命名规则：

```text
原文件名_后缀.格式
```

例如：

```text
input/box001.jpg  →  output/box001_result.jpg
```

## 安装 Python 环境

建议安装 Python 3.11。当前项目在 Windows 11 + Python 3.11 环境下完成测试。

在 Windows 上可以从 Python 官网下载安装包：

```text
https://www.python.org/downloads/release/python-3119/
```

安装时**必须**勾选 `Add Python to PATH`。

> 注意：不要从 Microsoft Store 安装 Python。如果已安装，需要在 Windows 设置 → 应用 → 应用执行别名中关掉 `python.exe` 和 `python3.exe`。

检查 Python 是否安装成功：

```bash
python --version
```

## 安装依赖

进入项目目录：

```bash
cd image_batch_processor
```

安装依赖：

```bash
pip install -r requirements.txt
```

`requirements.txt` 中固定了已在 Windows 本地测试通过的版本组合：

```text
rembg==2.0.60
onnxruntime==1.17.3
numpy==1.26.4
protobuf==4.25.3
```

这样做是为了避开部分 Windows 电脑上新版 `onnxruntime` 出现 DLL 初始化失败的问题。

第一次运行 `rembg` 时，可能会自动下载本地模型文件。模型文件保存在本机，不是上传图片。

## 日志

日志文件：

```text
logs/process.log
```

日志包含：

- 开始处理时间；
- 共发现多少张图片；
- 每张图片是否成功；
- 失败原因；
- 输出路径；
- 成功数量、失败数量、总数。

## 常见问题

### install.bat 报错 Python not found

- 确认从 python.org 安装了 Python（不是 Microsoft Store）
- 安装时勾选了 "Add Python to PATH"
- Windows 设置 → 应用执行别名 → 关掉 python.exe 和 python3.exe
- 重新打开命令行窗口再运行 install.bat

### install.bat 报错 Failed to create virtual environment

- 项目路径不要包含中文或特殊字符，建议放到 `C:\image_batch_processor`
- 右键 install.bat → 以管理员身份运行
- 临时关闭杀毒软件后重试

### 依赖安装失败或超时

使用清华镜像：

```bash
.venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### rembg 安装失败怎么办

先升级 pip：

```bash
python -m pip install --upgrade pip
```

再安装依赖：

```bash
pip install -r requirements.txt
```

如果仍然失败，建议使用 Python 3.11，并重新创建虚拟环境：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

如果出现 `onnxruntime` 或 DLL 相关错误，优先确认没有在 Anaconda 主环境中混装依赖，建议使用上面的项目独立虚拟环境。

### 第一次运行很慢怎么办

`rembg` 第一次运行可能需要下载 AI 模型文件。下载完成后，后续批量处理会复用本地模型和 session。

### 输出图不是白底怎么办

检查 `config.json`：

```json
{
  "background_color": [255, 255, 255],
  "transparent_background": false
}
```

默认输出应为白底图。如果输出 JPG，也会自动合成为白底 RGB 图片。

### 水印不显示怎么办

检查以下项目：

- `path` 是否正确；
- 水印文件是否放在 `watermarks` 文件夹；
- `enabled` 是否为 `true`；
- `opacity` 是否过低；
- `scale_ratio` 是否过小；
- 水印图片是否本身为空白或全透明；
- 查看 `logs/process.log` 是否有水印读取失败记录。

### 光效模板看不出效果怎么办

- 确认 `blend_mode` 设为 `screen`（不是 `normal`）；
- 逐步增大 `opacity`：从 `1.0` 开始，尝试 `3.0`、`5.0`、`10.0`；
- 确认 PSD 文件包含光效图层（非纯色填充）。

### PSD 如何处理

推荐先把 PSD 中的水印图层导出为 PNG，再放入 `watermarks` 文件夹。不要依赖 Photoshop 自动化，远程调试和客户本机部署会更稳定。

如果直接使用 PSD，程序会自动跳过纯色填充层，只提取效果图层。配合 `screen` 混合模式使用。

### 图片抠图效果不理想怎么办

可以尝试：

- 使用背景更干净、主体更清晰的原图；
- 提高原图分辨率；
- 修改 `config.json` 中的 `alpha_matting` 为 `true`；
- 尝试不同的 `rembg_model`，例如 `u2netp` 或 `isnet-general-use`；
- 对特殊品类图片保留人工复核流程。

示例：

```json
{
  "alpha_matting": true,
  "rembg_model": "isnet-general-use"
}
```

不同模型第一次使用时可能需要下载对应模型文件。
