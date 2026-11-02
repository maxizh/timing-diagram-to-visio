# WaveJSON 常用模板

复制就能用。改改信号名和数据即可。

> **⚠️ 写串行数据线（MOSI/MISO/TX/RX/DQ…）时只许用 `0` 和 `1`。**
> `2`-`9` 会被渲染成彩色**数据块**，把真实的高低电平吃掉 —— 图就跟原波形不等效了。
> `2`-`9` 只留给真正的并行总线（D[7:0] 每周期传一个字节）。
> 约定：**1 个 bit = 2 个字符**，这样 1 个时钟周期正好对齐 1 个数据位。
> 渲染请用 `scripts/wavejson2svg.py`（直角方波，可直接进 Visio）。

## 1. SPI 字节传输 (Mode 0) — MOSI=0x5A, MISO=0xC3

每 bit 2 字符，首尾各留 2 字符空闲电平 → 全部 20 字符对齐。

```json
{
  "head": { "text": "SPI Mode 0 · MOSI=0x5A · MISO=0xC3 · CPOL=0 CPHA=0" },
  "signal": [
    { "name": "CS_n", "wave": "11000000000000000011" },
    { "name": "SCLK", "wave": "00010101010101010100" },
    { "name": "MOSI", "wave": "00001100111100110000" },
    { "name": "MISO", "wave": "00111100000000111100" }
  ],
  "config": { "hscale": 1 },
  "foot": { "text": "MOSI: 0101_1010 = 0x5A · MISO: 1100_0011 = 0xC3 · MSB First" }
}
```

> ❌ 反例：`{"name":"MOSI","wave":"x2345678x","data":["D7",...]}` —— 数据线会变成一排方块。

## 2. I2C 事务

I2C 的 SDA 是单 bit 线，用 `0`/`1`；`2`-`5` 只用于"在这个槽位放一个字节标签"的示意。

```json
{
  "signal": [
    { "name": "SCL", "wave": "0.p......." },
    { "name": "SDA", "wave": "10.2.3.4.1", "data": ["ADDR", "ACK", "DATA"], "node": ".a.b.c.d.e" },
    {},
    { "name": "Event", "wave": "x2.3.4.5.x", "data": ["START", "ADDR", "ACK", "DATA", "STOP"] }
  ],
  "edge": ["a~>b Start condition", "c~>d ACK timing"],
  "config": { "hscale": 2 }
}
```

## 3. UART 帧（8N1 · TX=0x5A · LSB first）

每 bit 2 字符：前导空闲高 → 起始位低 → D0..D7 → 停止位高 → 空闲高。

```json
{
  "head": { "text": "UART 8N1 · TX=0x5A (LSB first)" },
  "signal": [
    { "name": "TX", "wave": "110000110011110011001111" }
  ],
  "config": { "hscale": 1 },
  "foot": { "text": "idle=1 → start=0 → D0..D7 (LSB first) → stop=1 → idle=1" }
}
```

## 4. 总线写周期（含 setup/hold 时序箭头）

```json
{
  "signal": [
    { "name": "ADDR", "wave": "x.2.....x", "data": ["0x100"] },
    { "name": "DATA", "wave": "x...3...x", "data": ["0xAB"], "node": "....a..." },
    { "name": "WR", "wave": "1....01..", "node": ".....bc." },
    { "name": "CS", "wave": "1.0.....1" }
  ],
  "edge": ["a~>b Data setup time", "c~>a Data hold time"]
}
```

## 5. 片选译码（2-bit 地址 → 4 个 CS）

```json
{
  "signal": [
    { "name": "ADDR[1:0]", "wave": "2.3.4.5.", "data": ["00", "01", "10", "11"] },
    {},
    ["Chip Selects (Active Low)",
      { "name": "CS0", "wave": "0.1.1.1." },
      { "name": "CS1", "wave": "1.0.1.1." },
      { "name": "CS2", "wave": "1.1.0.1." },
      { "name": "CS3", "wave": "1.1.1.0." }
    ]
  ],
  "config": { "hscale": 2 }
}
```

## 6. 时钟域跨越（异步 FIFO/双触发器同步）

```json
{
  "signal": [
    ["Clock Domain A",
      { "name": "CLK_A", "wave": "p........" },
      { "name": "DATA_A", "wave": "x.1......", "data": ["valid"], "node": ".a......" }
    ],
    {},
    ["Clock Domain B",
      { "name": "CLK_B", "wave": "n........" },
      { "name": "SYNC_0", "wave": "x..1.....", "node": "...b....." },
      { "name": "SYNC_1", "wave": "x....1...", "node": ".....c..." },
      { "name": "DATA_B", "wave": "x......1.", "data": ["output"] }
    ]
  ],
  "edge": ["a->b First stage", "b->c Second stage", "c->a Sync complete"]
}
```

## 7. DDR 读时序（双倍数据率）

```json
{
  "signal": [
    { "name": "CK", "wave": "p.P......" },
    { "name": "CK_N", "wave": "n.N......" },
    { "name": "DQS", "wave": "z.=.=.=z." },
    { "name": "DQ", "wave": "z.=..=..z", "data": ["D0", "D1"] }
  ],
  "config": { "hscale": 1.5 }
}
```

## 8. 上电时序（电源 → 复位 → 时钟 → CPU 启动）

```json
{
  "signal": [
    { "name": "Power", "wave": "0.1......." },
    { "name": "PowerGood", "wave": "0..1.....", "node": ".a.b...." },
    { "name": "RESETn", "wave": "0...10....", "node": "....c..." },
    { "name": "CLK", "wave": "0....p...." },
    { "name": "CPU_RDY", "wave": "0.....10." }
  ],
  "edge": ["a->c Power good to reset release", "c->d Reset to clock stable"],
  "config": { "hscale": 2 }
}
```

## 9. 状态机波形（Moore FSM）

```json
{
  "signal": [
    { "name": "state", "wave": "2...3...4", "data": ["IDLE", "READ", "WRITE"] },
    { "name": "valid", "wave": "0.1.0.1.0" },
    { "name": "ready", "wave": "1.0.1.0.1" }
  ]
}
```

## 10. SDRAM 读写突发

```json
{
  "signal": [
    { "name": "CK", "wave": "p........" },
    { "name": "CS_N", "wave": "1.0.....1" },
    { "name": "RAS_N", "wave": "1.0.1...." },
    { "name": "CAS_N", "wave": "1..0.1..." },
    { "name": "WE_N", "wave": "1...01..." },
    { "name": "ADDR", "wave": "x.=..=..x", "data": ["ROW", "COL"] },
    { "name": "DQ", "wave": "x....=..x", "data": ["DATA"] }
  ],
  "edge": ["RAS_N~>CAS_N t_RCD", "CAS_N~>DQ t_CAS"],
  "config": { "hscale": 1.5 }
}
```

## 11. 复位 + 启动序列

```json
{
  "signal": [
    { "name": "POR", "wave": "0.1......." },
    { "name": "PLL_LOCK", "wave": "0..1......", "data": ["stable"], "node": "..a...." },
    { "name": "RSTn", "wave": "0...10.....", "node": "....b..." },
    { "name": "CPU_RUN", "wave": "0.....1...." }
  ],
  "edge": ["a->b PLL stable then reset release"]
}
```

## 12. AXI4 写事务（精简）

```json
{
  "signal": [
    ["Write Address Channel",
      { "name": "AWVALID", "wave": "0.1....0" },
      { "name": "AWREADY", "wave": "0..1...0" },
      { "name": "AWADDR", "wave": "x.=..x", "data": ["0x1000"] }
    ],
    {},
    ["Write Data Channel",
      { "name": "WVALID", "wave": "0...1..0" },
      { "name": "WREADY", "wave": "0.....0" },
      { "name": "WDATA", "wave": "x....=x", "data": ["0xDEADBEEF"] }
    ],
    {},
    ["Write Response",
      { "name": "BVALID", "wave": "0....10" },
      { "name": "BREADY", "wave": "0....01" }
    ]
  ]
}
```

---

## 速查：常用信号字符

| 字符 | 含义 |
|------|------|
| `0` `1` | 固定低/高 |
| `x` `z` | 未知/高阻 |
| `p` `n` | 上升沿/下降沿时钟 |
| `=` | 数据标签持续位 |
| `2`-`9` | 多 bit 数据 |
| `P` `N` | 带箭头标记的时钟 |
| `u` `d` | 上拉/下拉 |
| `.` `|` | spacer / 时段分隔 |
