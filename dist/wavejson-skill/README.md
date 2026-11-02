# wavejson-skill

芯片时序图工具技能包 —— 自然语言 / datasheet 截图 / PDF → WaveJSON → 可进 Visio 编辑的直角方波 SVG；反向可把 datasheet 时序图**零大模型**读回可编辑波形。

遵循 [Agent Skills 开放标准](https://agentskills.io)，同一份技能可装入三个宿主：

| 宿主 | 安装路径 | 触发方式 |
|---|---|---|
| WorkBuddy | `~/.workbuddy/skills/wave2visio/` | 自然语言自动命中，或 `@skill:wavejson` |
| Claude Code | `~/.claude/skills/wave2visio/` | 自动匹配，或 `/wavejson` |
| Codex CLI | `~/.codex/skills/wave2visio/` | 自动匹配，或 `$wavejson` |

> **关于技能名 `wave2visio`**：触发词是用户唯一要敲的东西，必须自解释 —— wave2visio = 波形 → Visio。
> 三宿主触发方式：`@skill:wave2visio`（WorkBuddy）/ `/wave2visio`（Claude Code）/ `$wave2visio`（Codex CLI）。
> 技能目录名（`wave2visio`）就是三宿主识别技能用的名字。
> **WaveJSON** 是**中间数据格式** —— WaveDrom 渲染引擎的官方输入格式，有正式 schema
> （`wavedrom/schema`，MIT），本工具输出的 JSON 可直接粘进 wavedrom.com 在线编辑器打开。
> 本项目用的是它的**方言**：标准字段（`signal[]` / `wave` / `name` / `data` / `head` /
> `foot` / `config.hscale`）+ 扩展字段（`ruler_step` / `colors` / `x_style` / `edges` /
> `delays` 等，服务于复刻厂商图，标准 WaveDrom 会忽略）。
> ⚠️ 渲染器是**自研**的，不用官方 WaveDrom 引擎（官方是斜边梯形、堆重复字符会多转折、
> `2`-`9` 彩块会吃掉数据线电平）—— 详见 `wavejson/references/deep-dive-notes.md`。

## 能力概览

- **正向**：自然语言（"SPI mode 0 传输 0xA5"）→ WaveJSON → 直角方波 SVG（`scripts/wavejson2svg.py`，纯标准库、离线）
- **反向（零大模型、零 OCR）**：
  - 有 datasheet PDF → `scripts/pdf_trace.py` 直读文本层 + 矢量层（信号名、总线值、位网格都是真文字）
  - 只有截图/PNG → `scripts/auto_trace.py` 纯像素几何解析（支持真实 datasheet 的无框排版）
- **自检**：`scripts/selftest.py` 把渲染出的 SVG 反解回每字符电平逐 bit 比对，不靠肉眼
- **边界如实声明**：彩色状态块编码 + 每时钟 4 字符 + T 标号跳号 + 无文本层四条同现的图（典型如 JEDEC DDR 状态图）不做自动转换，提供人工反解的几何量法与范例脚本

## 安装

### 方式一：install.sh（推荐）

```bash
git clone <this-repo> && cd wavejson-skill
bash install.sh                 # 装到本机全部三个宿主
bash install.sh claude          # 只装 Claude Code
bash install.sh --list          # 查看各宿主安装路径
bash install.sh --uninstall     # 卸载（旧副本保留为 .bak，确认后自行删除）
```

仓库托管后支持远程一行安装（把 URL 换成你的托管地址）：

```bash
curl -fsSL <repo>/raw/main/install.sh | bash -s -- --repo <repo>
```

### 方式二：skills CLI

```bash
npx skills add <owner>/wavejson-skill/wavejson --agent claude   # 或 --agent codex
```

### 方式三：手动复制

把 `wavejson/` 目录整个复制到上表任一路径（`SKILL.md` 必须直接位于 `wavejson/SKILL.md`，不要多套一层目录）。

## 验证安装

```bash
cd ~/.claude/skills/wavejson    # 或对应宿主的路径
python3 scripts/selftest.py     # 退出码 0 = 通过；缺 pymupdf / 厂商语料的组会打印跳过
```

## 依赖

- Python 3.8+，纯标准库即可运行核心功能（渲染 / 几何解析 / 自检主体）
- 可选：`pymupdf`（PDF 直读）、`matplotlib`（仅重新测量基准图时）
- 全程离线、零 API Key、零 token

## 目录结构

```
wavejson/
├── SKILL.md              # 技能入口（最小可用版，只含调用方式 + 三条铁律）
├── scripts/              # 渲染器、PDF/PNG 解析器、自检、构建脚本
├── references/           # full-guide / examples / vision-prompt / deep-dive-notes
│                         #   （deep-dive-notes = 全部实测踩坑细节，排障时再读）
├── templates/            # HTML 模板（build_web.py 的源）
└── assets/               # 预览器、基准图等生成物
```

厂商 datasheet 原图/PDF 因版权不随包分发；依赖它们的自检组会自动跳过。
