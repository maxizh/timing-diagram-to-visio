# timing-diagram-to-visio

芯片时序波形图 ⇄ Visio 可编辑矢量图。

自然语言 / datasheet 截图 / PDF → WaveJSON → 直角方波 SVG，Visio 2024+ `File → Open` 直接打开编辑。
反向可把 datasheet 里的现成时序图**零大模型调用**读回可编辑波形。

## 名字说明

这个项目涉及三个名字，容易混：

| 名字 | 指什么 |
|---|---|
| **timing-diagram-to-visio** | **本仓库**（项目对外名） |
| **wave2visio** | **技能触发名 = 安装目录名** —— 三宿主靠它识别技能，`~/.workbuddy/skills/wave2visio/` 等 |
| **WaveJSON** | **中间数据格式** —— WaveDrom 渲染引擎的官方输入格式，有正式 schema（`wavedrom/schema`，MIT） |

**触发方式**：`@skill:wave2visio`（WorkBuddy）/ `/wave2visio`（Claude Code）/ `$wave2visio`（Codex CLI）。
技能名必须自解释 —— 触发词是用户唯一要敲的东西。

**为什么用 WaveJSON 而不是自造格式**：它是社区标准，输出的 JSON 可以直接粘进
wavedrom.com 在线编辑器打开，工具链不封闭在本项目里。

**本项目用的是 WaveJSON 的方言**：标准字段（`signal[]` / `wave` / `name` / `data` /
`head` / `foot` / `config.hscale`）加上扩展字段（`ruler_step` / `colors` / `x_style` /
`edges` / `delays` 等）—— 扩展字段服务于「复刻厂商图」，标准 WaveDrom 会忽略它们。

⚠️ **渲染器是自研的，不用官方 WaveDrom 引擎**：官方渲染器的电平过渡是斜边梯形
（不是原厂时序图的直角方波）、堆重复字符会画出多余转折、`2`-`9` 彩色数据块还会
吃掉数据线的电平。详见 `skill/references/deep-dive-notes.md`。

## 仓库结构

```
2026-09-14-11-10-22/          ← **本仓库根 = 项目源目录**（不是副本）
├── .workbuddy/skills/wave2visio/    技能本体（唯一真相源）
├── dist/wave2visio-skill/           分发包（**构建产物**，由 build_dist.py 生成）
│   ├── wave2visio/                  技能本体镜像 + install.sh + README
├── build_dist.py                    从源一键重建 dist + zip，并做逐字节校验
├── test-cases/                      测试语料（厂商原图/PDF 不入库）
├── docs/                            需求规格与交接文档
└── README.md
```

⚠️ **源是唯一真相**：`dist/` 是 `python3 build_dist.py` 的输出，不要手改。
改完技能本体后跑一次它，dist 与两个 zip 自动重建并校验一致性
（`python3 build_dist.py --check` 只校验不写，供 CI 用）。

## 能力

**正向生成**
- WaveJSON 方言输出（标准字段 + 扩展字段），不是自定义 DSL
- **直角方波**（原厂时序图风格），连续同电平不多余转折
- 时钟对齐竖虚线：落在数据位边界、贯穿全部信号、画在波形之前
- **边沿斜坡** `sig.edges`：真实 DDR/LPDDR 图的时钟是正弦/梯形波，画成直角就丢了上升沿/下降沿
- **延时标注** `sig.delays`：双向箭头 + 文字（如 `RL = 10`）
- 厂商图复刻扩展：`ruler_step`（DDR 每时钟 4 字符）、`colors`（彩色状态块）、
  `x_style=hatch`（Don't Care 斜纹）、`dash`、`blank`

**反向读取（零大模型、零 OCR）**
- `pdf_trace.py`：直读 PDF 文本层 + 矢量层拿信号名和总线值
- `auto_trace.py`：纯几何解析 PNG / JPG，无框模式自动分行、认时钟、采电平
- 三层架构：L0 判据分流 → L1 几何解析 → L2 视觉模型兜底（模型只认字，不数电平）

**质量保障**
- `selftest.py` 把渲染出的 SVG **反解回每字符电平**逐字符比对，判定口径 = 拓扑逐 bit 等效，不靠肉眼
- 纯标准库，零依赖，离线可跑

## 目录结构

```
2026-09-14-11-10-22/          ← **仓库根 = 项目源目录**（不是副本）
├── .workbuddy/skills/wave2visio/    技能本体（唯一真相源）
│   ├── SKILL.md             # 最小可用技能定义：适用范围/输入/features/输出/调用示例
│   ├── skill_dir.sh         # 打印本机实际安装目录（三宿主通用，别写死路径）
│   ├── scripts/             # 渲染器、PDF/PNG 解析器、自检、构建脚本
│   ├── references/          # full-guide / examples / vision-prompt / deep-dive-notes
│   ├── templates/           # HTML 模板（build_web.py 的源）
│   └── assets/              # 预览器、基准图等生成物
│
├── dist/wave2visio-skill/           分发包（**构建产物**，由 build_dist.py 生成）
│   ├── wave2visio/         # 与源同源
│   ├── install.sh          # 三宿主安装脚本
│   └── README.md
├── dist/wave2visio-skill.zip        # 分发包
│
├── build_dist.py            # 从源一键重建 dist + zip，并做逐字节校验
├── docs/                    # 需求规格与交接文档
└── test-cases/              # 测试语料与实测报告
```

⚠️ **源是唯一真相**：`dist/` 是 `python3 build_dist.py` 的输出，不要手改。
改完技能本体后跑一次它，dist 与两个 zip 自动重建并校验一致性
（`python3 build_dist.py --check` 只校验不写，供 CI 用）。

## 安装

```bash
cd dist/wave2visio-skill
bash install.sh                # 装到 WorkBuddy / Claude Code / Codex CLI 全部三宿主
bash install.sh claude         # 只装 Claude Code
bash install.sh --list         # 查看各宿主安装路径
bash install.sh --uninstall    # 卸载（旧副本保留为 .bak）
```

| 宿主 | 安装路径 | 触发方式 |
|---|---|---|
| WorkBuddy | `~/.workbuddy/skills/wave2visio/` | 自然语言自动命中，或 `@skill:wave2visio` |
| Claude Code | `~/.claude/skills/wave2visio/` | 自动匹配，或 `/wave2visio` |
| Codex CLI | `~/.codex/skills/wave2visio/` | 自动匹配，或 `$wave2visio` |

## 验证安装

```bash
cd ~/.workbuddy/skills/wave2visio    # 或对应宿主的路径
python3 scripts/selftest.py           # 退出码 0 = 通过
```

## 依赖

- Python 3.8+，纯标准库即可运行核心功能（渲染 / 几何解析 / 自检主体）
- 可选：`pymupdf`（PDF 直读）、`matplotlib`（几何解析 / 重新测量基准图）
- 全程离线、零 API Key、零 token

## 能力边界（如实声明）

彩色状态块编码 + 每时钟 4 字符 + T 标号跳号 + 无文本层，四条同现的图
（典型如 JEDEC DDR 状态图）**不做自动转换** —— 提供人工反解的几何量法与范例脚本。
详见 `skill/references/deep-dive-notes.md` 与
`test-cases/real-datasheets/fig15-trial-report.md`。

选通型异步接口（CS/RD 脉冲、无时钟）会明确报错拦下，不硬凑假时钟。

## 版权

厂商 datasheet 原图 / PDF 有版权，**不随仓库分发**（见 `.gitignore`）。
依赖它们的自检组会自动跳过。仓库为私有用途。
