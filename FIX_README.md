# SIGLENT SDS MCP 修复与测试指南

## 已修复问题

### Python 版本兼容性
- **问题**: `datetime.UTC` 是 Python 3.11+ 特性，旧版本报错
- **修复**: `src/siglent_sds_mcp/artifacts.py:10`
- **修改**: `dt.UTC` → `dt.timezone.utc`

### 波形电压解码每格码值错误（真机实测确认）
- **问题**: `_siglent_byte_to_voltage` 沿用 SDS1000X-E 的 25 码/格，SDS824X HD 实际为 30 码/格，
  导致解码电压系统性偏大约 20%。
- **真机证据**（SDS824X HD, VDIV=0.2V, OFST=-0.24V）:
  - 原始码值范围 [-68, +41]
  - 25 码/格 → [-0.304, +0.568]V（错误）
  - 30 码/格 → [-0.213, +0.513]V，面板实测 [-0.204, +0.515]V（吻合）
  - WAVEDESC.MAX_VALUE = 7680 = 30×256（佐证）
- **修复**: `src/siglent_sds_mcp/sds_tcp_adapter.py` 新增 `CODES_PER_DIV = 30` 常量。

### 波形时间轴起点错误（深存储场景）
- **问题**: 起点用 `-(tdiv·14)/2`（仅屏幕宽度 70µs），而深存储记录长达 500µs，时间轴严重错位。
- **修复**: 改为以触发点为中心 `start_time = -(N/2)·dt`，真机验证记录对称覆盖 ±250µs。

### 抽样丢峰
- **问题**: 简单跨步抽样会漏掉毛刺/峰值（2000 点抽样 PKPK 0.719→0.68）。
- **修复**: 改为 min/max 包络抽样，2000 点抽样仍精确保留 PKPK=0.7267V。

## 测试脚本

### 1. 重启 MCP 服务器
```bash
./restart_mcp.sh
```

### 2. 快速 Python 测试（直接测试波形抓取）
```bash
./quick_test.py
```

### 3. IDE 工具测试（通过 Windsurf MCP 面板）

#### 步骤 1: 连接示波器
```
mcp6_connect_tcp(host='192.168.0.170', port=5025)
```

#### 步骤 2: 识别设备
```
mcp6_identify_tcp()
```

#### 步骤 3: 抓取波形
```
mcp6_get_waveform_tcp(
    channel='C1',
    csv_path='/home/book/.codeium/windsurf/waveform_c1.csv',
    max_points=5000
)
```

#### 步骤 4: 断开连接
```
mcp6_disconnect_tcp()
```

## 已验证功能

| 功能 | 状态 |
|------|------|
| TCP 连接 | ✅ |
| 设备识别 (*IDN?) | ✅ |
| 通道配置查询 | ✅ |
| 采集状态查询 | ✅ |
| 测量 (PKPK/MAX/MIN...) | ✅ |
| 屏幕截图 (SCDP) | ✅ BMP 1024×600 32bpp |
| 波形下载 (修复后) | ✅ 真机验证 PKPK 误差 1% |
| 电压解码 (30 码/格) | ✅ 真机实测吻合 |
| 时间轴 (深存储中心对齐) | ✅ ±250µs 对称 |

## 输出文件位置

- 截图: `artifacts/screenshots/`
- 波形 CSV: `artifacts/waveforms/` 或指定路径
- 日志: `mcp_server.log`
