# Changelog

本文件记录所有重要变更，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased]

### 待办
- 支持更多 SDS 型号的 WAVEDESC 布局差异自动检测

---

## [0.3.0] - 2026-06-15

### 新增
- **WAVEDESC 自适应解码**：从二进制描述符 `MAX_VALUE` 字段推导 `codes_per_div`，
  无需硬编码型号特定参数。解码公式：
  `voltage = code × (VDIV / (MAX_VALUE/256)) - VERTICAL_OFFSET`
- **自动重连**：`_require_tcp()` 检测断连后自动以缓存参数重建连接，`disconnect_tcp` 后禁止自动重连
- **时基扫描探测**：实现了从粗到细扫描时基、定位 AC 信号的探测算法

### 修复
- WAVEDESC `VERTICAL_GAIN` 字段语义修正：SDS824X HD 存储的是 V/div 而非 V/code，
  需配合 `MAX_VALUE` 换算（之前版本直接当 V/code 使用导致解码偏差 ×30）
- `HORIZ_OFFSET` 正确使用 float64（8字节）读取，而非 float32

### 删除
- 移除 `server.py` 中的 PyVISA scaffold 工具：`scope_idn`、`scope_run`、`scope_stop`、
  `scope_single`、`scope_setup_uart`、`scope_measure_basic`、`scope_fetch_waveform`
  （TCP 路径已完全验证，PyVISA 工具为早期占位实现）
- 删除一次性调试脚本：`scripts/audit_probe.py`、`scripts/audit_probe2.py`、`scripts/audit_verify.py`

### 真机验证（SDS824X HD, 固件 4.8.12）
- WAVEDESC 自适应解码：CSV PKPK = 0.7133V，面板 = 0.714V，误差 **0.09%**
- 自动重连：断连后透明重建；`disconnect_tcp` 后不触发重连

---

## [0.2.0] - 2026-06-14

### 修复
- **波形电压解码每格码值**：SDS824X HD 实测为 30 码/格（非旧型号 25 码/格），
  解码误差从 ~20% 降至 <1%
  - 真机证据：原始码值 [-68, +41]，VDIV=0.2V，30 码/格 → [-0.213, +0.513]V，
    面板实测 [-0.204, +0.515]V 吻合；WAVEDESC.MAX_VALUE = 7680 = 30×256
- **波形时间轴起点**：深存储场景改为触发点居中 `start_time = -(N/2)·dt`，
  修复时间轴与实际触发位置的严重偏差
- **抽样丢峰**：简单跨步抽样改为 min/max 包络抽样，2000 点抽样仍精确保留 PKPK

### 修复
- **Python 版本兼容性**：`datetime.UTC`（Python 3.11+）→ `datetime.timezone.utc`

---

## [0.1.0] - 2026-06-12

### 新增
- 初始版本，支持 SDS824X HD / SDS800X HD TCP SCPI 通信
- TCP 连接管理 (`connect_tcp` / `disconnect_tcp`)
- 通道配置、采集控制、测量、截图、波形下载
- UART 2Mbps 捕获与分析
- RS485 差分对分析
- Modbus RTU 时序计算
- Markdown 报告生成
