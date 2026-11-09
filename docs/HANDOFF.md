# 新会话交接指令

用于把「芯片设计 AI 画图小工具」的需求交接给一个新开的会话。

---

## 情况 A · 在**同一个工作目录**下新开会话（推荐）

不需要粘贴长文。项目记忆会自动加载，新会话开好后只需要发这一句：

```
读 docs/chip-tool-requirements.md，然后按里面的 P1 待办继续。
```

> 原理：`.workbuddy/memory/MEMORY.md` 与 `docs/chip-tool-requirements.md` 都在本工作目录内，
> 新会话启动时会自动注入项目记忆，直接就能接上上下文。

---

## 情况 B · 换了目录 / 想一次性完整交接

新会话开好后，**整段复制下面这个代码块**发过去：

```text
【任务交接】芯片设计「AI 画图 → Visio」小工具

请先读下面几个文件（路径均相对仓库根目录）：
- 需求规格：`docs/chip-tool-requirements.md`
- 项目记忆：`.workbuddy/memory/MEMORY.md`
- 实现资产：`.workbuddy/skills/wave2visio/`（开发源；分发包在 `dist/wave2visio-skill/`）

【背景】
给芯片设计工程师做一个小而专的工具：用自然语言 / 鼠标点选 / 截图输入，
直接产出可进 Visio 编辑的矢量图。目标是 all-in-one 覆盖
waveform / 流程图 / 状态机 / 架构图，目前只有 waveform 跑通。

【主链路】
图片或自然语言 → AI Vision → WaveJSON（中间表示）
→ scripts/wavejson2svg.py（自研渲染器）→ SVG → Visio File→Open

【必须遵守的铁律 —— 违反就出错】
1. WaveDrom 的 2-9 是彩色数据块，不是电平。单 bit 数据线（MOSI/MISO/DQ/TX/RX）
   只能用 0/1；2-9 只留给真正的并行总线（D[7:0]）。
2. 不要用 . 或 x 开头，会渲染成未定义态的斜线阴影。
3. 不用官方 WaveDrom 渲染（斜边梯形 + 字符边界多余尖刺），用自研 wavejson2svg.py。
4. svg.wavedrom.com/{code}/ 的 code 是 URL 编码的原始 JSON，不是 base64。
5. 单 HTML 交付必须 base64 内嵌所有资源（预览面板是单文件服务，相对路径全 404）。
6. 数据对齐约定：1 bit = 2 字符，1 个数据位对齐 1 个 SCLK 周期；
   CPOL=0 每周期写 "01"，CPOL=1 写 "10"；首尾各留 2 字符。

【验收红线】
我说「一模一样」指的是拓扑 / 电平序列逐 bit 等效，不能用「渲染风格差异」搪塞。
验证方式是把 wave 字符串按位还原成 bit 序列再和原图对照，不靠肉眼。
例：bits = [w[k] for k in range(2, 18, 2)]，再校验 int(''.join(bits), 2) 是否等于预期值。

【接下来要做的（P1）】
1. 批量稳定性：一次跑多张 datasheet 时序图，确认识别质量稳定
2. prompt 回归测试：构造一组标准时序图，验证 AI 输出规规矩矩用 0/1
3. Visio 真机实测 File→Open 与 Ungroup 效果

【沟通偏好】
干练直接，结论先行，不要铺垫。先查日志/文档确认现状再动手。
股票/投资场景用中文结构化报告；本项目用中文技术沟通。
```

---

## 情况 C · 只想知道"上次聊了什么"

新会话里发这句即可：

```
读 docs/chip-tool-requirements.md 和 .workbuddy/memory/2026-09-14.md，
给我讲讲这个 waveform 小工具的需求和目前进展。
```
