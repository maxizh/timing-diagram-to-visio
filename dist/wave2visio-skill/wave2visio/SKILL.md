---
name: wave2visio
version: 1.0.0
author: "MaxZheng"

# ── 中文展示字段：中文客户看到的内容（全中文，不混排） ──
display_name: "芯片时序图"
description_zh: "用一句话描述时序，或把数据手册里的波形图变成可编辑版本；输出直角方波矢量图，可直接导入绘图软件编辑。"
examples_zh:
  - "画一个串行外设接口模式 0 传输十六进制 A5 的时序波形，输出可编辑的矢量图"
  - "把这份数据手册第 54 页的时序图还原成可编辑的波形数据"
  - "把这张波形截图转成直角方波图，逐位对齐时钟和数据"

# ── English display fields: shown to English readers only ──
display_name_en: "Timing Diagram"
description: Generate WaveJSON timing diagrams from natural language for chip design specs, and read existing timing diagrams straight out of datasheet PDFs or screenshots without a vision model. Use when user asks to draw SPI/I2C/UART timing, bus waveforms, clock domain crossings, signal sequences, or any digital timing diagram needed in RTL specs, design reviews, or documentation, or to convert a datasheet figure into editable waveforms.
description_en: "Natural language or timing-diagram screenshot/PDF to WaveJSON to Visio-editable SVG"
examples_en:
  - "Draw an SPI mode 0 transfer of 0xA5 as a Visio-editable timing diagram"
  - "Turn the timing figure on page 54 of this datasheet into editable WaveJSON"
  - "Trace this waveform screenshot into a square-wave SVG with bit-aligned signals"
---

# 使用说明

## 中文

把「写一段时序说明」或「把数据手册里的图变成可编辑版本」，从手工画图变成一句话。

**两个方向**

- 正向：用文字描述时序，生成波形数据，再渲染成直角方波矢量图，导入绘图软件后即可编辑。
- 反向：把数据手册文件或波形截图还原成波形数据，全程不调用大模型。

**适用场景**

串行外设接口、内部集成电路总线、通用异步收发器的时序；总线传输、跨时钟域、  
状态机波形、建立与保持时间约束；规格文档配图、设计评审、把厂商现成图变成可编辑版本。

框图与架构图、模拟波形、仿真器里直接查看波形，不在适用范围内。

**试试这样用**

- 画一个串行外设接口模式 0 传输十六进制 A5 的时序波形，输出可编辑的矢量图
- 把这份数据手册第 54 页的时序图还原成可编辑的波形数据
- 把这张波形截图转成直角方波图，逐位对齐时钟和数据

**输出结果**

白底黑线的纯矢量图，导入绘图软件后是一根根可单独选中的线条，需要时拆成形状再另存。  
同时保留波形数据源文件和网页预览。

## English

Turn a timing description — or an existing figure in a datasheet — into an editable  
diagram with a single sentence.

**Two directions**

- Forward: describe the timing in words, produce waveform data, then render it as  
  square-wave vector graphics that open directly in a drawing application.
- Reverse: recover waveform data from a datasheet file or a waveform screenshot,  
  with no large model calls at all.

**Use it for**

SPI, I2C and UART timing, bus transfers, clock-domain crossings, state-machine  
waveforms, and setup/hold constraints; specification figures, design reviews, and  
converting vendor figures into editable versions.

Block diagrams, analog waveforms, and waveforms viewed directly in a simulator are  
out of scope.

**Try these**

- Draw an SPI mode 0 transfer of 0xA5 as an editable timing diagram
- Turn the timing figure on page 54 of this datasheet into editable waveform data
- Trace this waveform screenshot into square-wave graphics with bit-aligned signals

**Output**

Black-on-white vector graphics made of plain paths and text. In a drawing application  
each line is a selectable shape that can be ungrouped and saved in a native format.  
Waveform source data and an HTML preview are included.

---

# 技能实现说明

以下给宿主智能体与开发者看，术语按项目惯例保留英文；上面的用户说明按语言分区，不受影响。

## 名字说明（三个名字，别混）

| 名字                          | 指什么                                                                                                    | 在哪                                        |
| --------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------------------------------- |
| **WaveJSON**                | **中间数据格式**。WaveDrom 渲染引擎的官方输入格式，有正式 schema（`wavedrom/schema`，MIT）。本项目的 JSON 可直接粘进 wavedrom.com 在线编辑器打开 | `.json` 文件 / `wavejson2svg.py`            |
| **wave2visio**              | **技能触发名 = 安装目录名**。`@skill:wave2visio` / `/wave2visio` / `$wave2visio`（三宿主各自的显式触发方式）                    | `~/.workbuddy/skills/wave2visio/` 等       |
| **timing-diagram-to-visio** | **GitHub 仓库名**。项目对外的名字                                                                                 | github.com/maxizh/timing-diagram-to-visio |

**技能名为什么叫 wave2visio**：触发词是用户唯一要敲的东西，必须自解释。  
`wave2visio` = 波形 → Visio，一眼看出干什么；技能栏显示名是「芯片时序图 / Timing Diagram」。  
（早期曾把**格式名**当成技能名，用户看到会一脸茫然 —— 技能名 ≠ 格式名，这是改名的原因。）

**本项目用的是 WaveJSON 的方言**：标准字段（`signal[]` / `wave` / `name` / `data` /  
`head` / `foot` / `config.hscale`）**加上 10 个扩展字段**  
（`config.ruler_step` / `ruler_offset` / `ruler_pad` / `grid_step` / `x_style` / `x_line` /  
`ruler` / `sig.colors` / `sig.dash` / `sig.blank` / `sig.edges` / `sig.delays`）。  
扩展字段在标准 WaveDrom 里会被忽略 —— 它们服务于「复刻厂商图」，不是通用需求。

⚠️ **渲染器不依赖 WaveDrom**：本项目用自研渲染器（`wavejson2svg.py` / `renderer.js`），  
不用官方 WaveDrom 渲染引擎。原因见 `references/deep-dive-notes.md`：  
官方渲染器的电平过渡是斜边梯形（不是原厂时序图的直角方波）、堆重复字符会画出多余转折、  
且 `2`-`9` 彩色数据块会吃掉数据线的电平。

## 适用范围

**用**：SPI / I2C / UART 时序、总线传输、CDC 跨时钟域、状态机波形、setup/hold 约束；  
spec 文档配图；设计评审；把厂商 datasheet 的现成图变成可编辑版本。

**不用**：

- 框图 / 架构图 / 流程图 → Draw.io
- 模拟波形 → LTspice
- 仿真器直接看 → Modelsim / Vivado

## 输入

| 入口        | 输入形式            | 备注                 |
| --------- | --------------- | ------------------ |
| 自然语言      | 对话里描述时序         | 默认入口，零配置           |
| WaveJSON  | `.json` 文件      | 精确控制每一拍            |
| datasheet | `.pdf` + 页码     | **优先**，信号名/总线值是真文字 |
| 波形图       | `.png` 截图       | 走像素几何              |
| 仿真输出      | `.vcd` / `.csv` | 直接读跳变表，别画成图再读回来    |

## Features

**正向生成**

- WaveJSON 标准输出，不是自定义 DSL
- **直角方波渲染**（原厂时序图风格），连续同电平不多余转折，Visio 直接打开就是一根根线
- 时钟对齐竖虚线：落在数据位边界、贯穿全部信号、画在波形之前 → 一眼确认「第 k 位 == 第 k 个时钟」
- 复刻厂商图的扩展字段：`ruler_step`（DDR 图每时钟 4 字符）、`colors`（彩色状态块）、`x_style=hatch`（Don't Care 斜纹）、`dash`、`blank`
- **边沿斜坡** `sig.edges[]`：真实 DDR/LPDDR 图的时钟是**正弦/梯形波**，边沿是斜的  
  （直角方波画不出「上升沿/下降沿在哪、占多宽」）。格式：  
  |  |  |  |  
  | --- | --- | --- |  
  `{"at": 字符位(可小数), "from": 0|1, "to": 0|1, "width": 斜坡占的字符数}`
- **延时标注** `sig.delays[]`：`{"from": 字符位, "to": 字符位, "label": "RL = 10"}`  
  → 画成双向箭头 + 居中文字，用于标注读延时（RL）、间隔等

> ⚠️ `edges` 与 wave 的配合：wave 只提供「哪段高、哪段低」，**边沿位置与形状由 edges 决定**。  
> 字符粒度要选得让边沿落在**整数位**（否则 wave 表达不了「高平台占 1.5 字符」，  
> 渲染会多画一竖）。实测 LPDDR4 Fig.15：1 周期 = 8 字符、cell = 13px 时，  
> 高平台 39px = 3 字符、斜坡 13px = 1 字符，边沿正好整数对齐。

**反向读取（零大模型）**

- `pdf_trace.py`：直读 PDF 文本层 + 矢量层拿信号名和总线值，融合像素几何求电平
- `auto_trace.py`：纯几何解析 PNG/JPG，无框模式自动分行、认时钟、采电平
- 三层架构：L0 判据分流 → L1 几何解析 → L2 视觉模型兜底（模型只认字，**不数电平**）

**质量保障**

- `selftest.py` 把 SVG **反解回每字符电平**逐字符比对，判定口径 = 拓扑逐 bit 等效，不靠肉眼
- 纯标准库，零依赖，离线可跑

**输出**

- 白底黑线纯 `<path>`/`<text>` SVG，无 pattern（Visio 对 pattern 导入不可靠）
- 另有 WaveJSON 源文件、HTML 预览器、验收报告

## 调用示例

**默认示例（未指定用途时用这个）**：

> 用 wave2visio 给我画个 SPI mode 0 传输 0xA5 的波形

→ 输出 WaveJSON + 渲染成直角方波 SVG。Visio 2024+ `File → Open` 打开即可编辑，需要时 `Ungroup` 拆成形状、`Save As .vsdx`。

**其他入口**：

```bash
# 自动探测本机安装目录（同一份技能可装到 .workbuddy / .claude / .codex 任一）
SKILL="$(bash "$(dirname "$0")/skill_dir.sh")" 2>/dev/null || SKILL=~/.workbuddy/skills/wave2visio

# 渲染：WaveJSON → Visio 友好 SVG
python3 $SKILL/scripts/wavejson2svg.py input.json -o out.svg --cell 26 --row 62

# 读 datasheet PDF（优先这条）
python3 $SKILL/scripts/pdf_trace.py --pdf spec.pdf --page 54 \
    --wavejson out.json --svg out.svg --verbose

# 读波形图 PNG
python3 $SKILL/scripts/auto_trace.py --png fig.png --out out.json --svg out.svg -v

# 自检（验收口径：逐 bit 反解比对）
python3 $SKILL/scripts/selftest.py            # 看退出码 0/1
python3 $SKILL/scripts/selftest.py --html     # 出可视化验收报告
```

> `$SKILL` 不要写死。三宿主安装路径不同（`~/.workbuddy` / `~/.claude` / `~/.codex`），  
> `skill_dir.sh` 会按实际存在的安装位置判定，找不到时明确报错而不是跑到空目录。

## 三条铁律

**1. 数据线只用 `0` / `1`，绝不用 `2-9`。**  
`2`-`9` 在 WaveDrom 里是**彩色数据块**、不是电平。单 bit 信号（MOSI/MISO/DQ/DIN/DOUT）  
用了会让高低电平整段消失、变成一排方块，图形与原图完全不等效。

```jsonc
{"name": "MOSI", "wave": "00001100111100110000"}   // ✅ 每 bit 2 字符的真实电平
{"name": "MOSI", "wave": "x23456789x"}              // ❌ 数据线全变成数据块
```

也别用 `.` / `x` 开头（没有前值可延续，会渲染成未定义斜线），开头写实 `0`。

**2. 渲染器改两份。** `scripts/renderer.js`（网页用）和 `scripts/wavejson2svg.py`（CLI 用）  
必须同步改，自检第 5 组会校验两者一致，只改一份会被当场抓出来。  
改 `references/vision-prompt.md`（规则权威源）后跑 `python3 scripts/build_web.py` 重建  
`assets/*.html`，产物不要手改。

**3. 反向链路有明确能力边界，别承诺「自动转换」。**  
彩色状态块编码、每时钟 4 字符的 DDR 图、T 标号跳号、无文本层无灰底 —— 这类特征  
`pdf_trace.py` / `auto_trace.py` 解不了。正确做法是**人工反解 + 几何测量后重绘**，  
并对用户如实说明「这是重绘，不是自动读图」。  
选通型异步接口（CS/RD 脉冲、无时钟）会被明确报错拦下，不会硬凑假时钟。

## 参考

以下文件都在**本技能目录下**，完整路径 = `$SKILL/`（用 `bash skill_dir.sh` 打印实际目录）。  
需要时再读，不必预先加载：

| 文件（相对技能目录）                      | 内容                                                               |
| ------------------------------- | ---------------------------------------------------------------- |
| `references/full-guide.md`      | 完整生成规则、输出格式、常见场景                                                 |
| `references/examples.md`        | SPI / I2C / Bus / CDC / 状态机现成模板                                  |
| `references/vision-prompt.md`   | 识别/生成规则**权威源**（改规则只改这里，再跑 `build_web.py`）                        |
| `references/deep-dive-notes.md` | 深读笔记：PDF 直读七坑、无框模式四坑、灰梯形判据、适用性闸门、LPDDR4 人工反解量法（**排障 / 改解析器时必读**） |
| `skill_dir.sh`                  | 打印本机实际安装目录（三宿主通用，别写死路径）                                          |

同一份技能可装到三个宿主（`~/.workbuddy/skills/` · `~/.claude/skills/` · `~/.codex/skills/`），  
**`skill_dir.sh` 帮你判定，不用手改文档**。

`assets/paste-to-visio.html` 是浏览器版主工具（图片 → AI → WaveJSON → Visio 全链路，  
视觉模型可选、支持国内直连模型）。不想填 Key 就把图直接丢进对话，走 skill 路径。
