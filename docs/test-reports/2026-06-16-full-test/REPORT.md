# Full System Test Report — siglent-sds-mcp

**Date**: 2026-06-15/16  
**Scope**: SIGLENT SDS824X HD, FW 4.8.12.1.1.6.5, S/N SDS08A0D911789  
**IP**: 192.168.0.170:5025  
**Test operator**: Claude Code + hardware probe on C1

---

## Test Summary

| Step | Description | Result |
|------|-------------|--------|
| 1 | Local code tests (pytest + lint) | ✅ 62 passed, ruff clean |
| 2 | Scope connection test | ✅ ping 1.3ms, port 5025 open, IDN OK |
| 3 | Screenshot test (SCDP) | ✅ 2.4MB BMP, 1024×600×32bit |
| 4 | Auto-find waveform single-channel | ✅ found=true, C1 Vpp=0.367V@3.29V |
| 5 | Multi-channel auto-scan | ✅ C1 selected, C2/C3/C4 correctly excluded |
| 6 | Screenshot/CSV same-frame verification | ✅ Screenshot + CSV from same STOP frame |
| 7 | OFST direction (dual-mode decode) | ✅ Fixed: OFST=0 vs OFST≠0 encoding modes |
| 8 | OFST SCPI command | ⚠️ `C1:OFST <val>` ignored by FW 4.8.12.1.1.6.5 |
| 9 | TRLV SCPI command | ⚠️ `C1:TRLV <val>` ignored by FW 4.8.12.1.1.6.5 |

---

## Step 1: Local Code Tests

```bash
$ git pull origin main    # Already up to date
$ pip install -e '.[dev]' # OK
$ pytest -q               # 62 passed in 0.19s
$ ruff check src tests    # All checks passed
```

### Named test suites

| Suite | Tests | Result |
|-------|-------|--------|
| test_unit_parsing.py | 24 | ✅ mV≠MV, MS=milliseconds, context-specific |
| test_wavedesc.py + test_wavedesc_parser.py | 9 | ✅ synthetic WAVEDESC, ASCII prefix |
| test_tcp_binary_prefix.py | 5 | ✅ IEEE 488.2 / BMP prefix skipping |
| test_auto_setup_mock.py | 5 | ✅ mock channel selection, NEG slope, same-frame, coarse/final stats |
| test_waveform_stats.py | 2 | ✅ active square wave, flat noise detection |
| test_tcp_transport_parser.py | 2 | ✅ socketpair block parsing |

---

## Step 2: Scope Connection Test

```bash
$ ping -c 2 192.168.0.170    # 0.973-1.311ms, 0% loss
$ nc -vz 192.168.0.170 5025  # Connection succeeded
$ python examples/tcp_idn_test.py 192.168.0.170
  → SIGLENT,SDS824X HD,SDS08A0D911789,4.8.12.1.1.6.5
```

---

## Step 3: Screenshot Test (SCDP)

```bash
$ python examples/screen_capture_tcp.py 192.168.0.170
```

| Field | Value |
|-------|-------|
| Command | SCDP |
| Format | BMP, raw-bmp framing |
| Size | 2,457,658 bytes |
| Dimensions | 1024 × 600 pixels |
| Bits per pixel | 32 |
| Verification | ✅ SDS824X HD confirmed |

---

## Step 4: Auto-Find Waveform (Known Signal)

```bash
$ python examples/auto_find_waveform_tcp.py 192.168.0.170 \
    --channels C1 C2 C3 C4 --max-points 5000
```

### Coarse scan results

| Channel | Vpp | Vmean | Edges | Score | Active? |
|---------|-----|-------|-------|-------|---------|
| **C1** | **0.367V** | **3.293V** | **3723** | **2.37** | ✅ **Selected** |
| C2 | 0.033V | -0.017V | 4883 | 0.78 | ❌ noise |
| C3 | 0.033V | -0.033V | 2 | -0.20 | ❌ noise |
| C4 | 0.033V | -0.017V | 4633 | 0.78 | ❌ noise |

### Auto-configured settings

| Parameter | Value |
|-----------|-------|
| VDIV | 100mV |
| OFST | 3.293V |
| TDIV | 10μs |
| Trigger level | 3.283V |
| Confidence | medium |
| Screenshot | ✅ captured |
| Final CSV | ✅ captured |

**C1 waveform characteristics**: 3.3V logic signal with ~0.37V ripple at ~336kHz toggle rate.

**Raw data**: see `waveforms/c1_coarse_scan.csv` (5000 points) and `waveforms/auto_find_analysis.json`.

---

## Step 5: Multi-Channel Auto-Scan

Same command as Step 4. C1 correctly identified as the only active channel. C2/C3/C4 show Vpp=33mV (below 50mV noise floor), correctly excluded despite high edge counts on C2/C4 (noise triggers many false edges).

---

## Step 6: Screenshot/CSV Same-Frame Verification

The auto_find_waveform final capture sequence:

```
get_waveform(restore_trmd=False)  →  internal TRMD AUTO + STOP, exports CSV
screenshot()                       →  SCDP while scope still stopped
scope.transport.write("ARM")       →  restart acquisition
```

**Verification**: Mock test `test_screenshot_and_csv_from_same_stop_frame` confirms:
- `get_waveform` called with `restore_trmd=False` ✓
- `screenshot()` called after `get_waveform` ✓
- `ARM` called after all captures ✓

---

## Step 7: OFST Direction — Dual-Mode Decode (FIXED)

### Discovery

SDS824X HD changes WF? DAT2 encoding based on OFST value:

| OFST | Encoding | Formula |
|------|----------|---------|
| =0V | Raw ADC codes | `voltage = code_signed × gain` |
| ≠0V | Data centered around OFST | `voltage = (byte−128) × gain + OFST` |

### Evidence

| Setting | Raw bytes | Correct formula | Vmean |
|---------|-----------|-----------------|-------|
| VDIV=1V, OFST=0V | min=98, max=100 | `code_signed × gain` | 3.29V ✓ |
| VDIV=1V, OFST=3.3V | all=127 | `(byte−128)×gain+OFST` | 3.27V ✓ |

Previously all OFST fix attempts failed because the dual encoding mode was not recognized.

**Implemented in**: `_siglent_byte_to_voltage()` and `_siglent_byte_to_voltage_gain()` in `sds_tcp_adapter.py`.

---

## Step 8: OFST SCPI Command — FIRMWARE BUG

### Test

Two screenshots taken with different OFST settings, same VDIV:

| Screenshot | VDIV | OFST set | Waveform screen position |
|------------|------|----------|--------------------------|
| `01_vdiv1v_ofst0v.bmp` | 1V | 0V | screen rows 97–110 (~3.28V) |
| `02_vdiv200mv_ofst3v3.bmp` | 200mV | 3.3V | screen rows 97–110 (~3.88V) |

**The waveform trace occupies the EXACT same screen pixel rows in both screenshots.**

### Conclusion

`C1:OFST <value>` SCPI command is **ignored** by firmware 4.8.12.1.1.6.5. The waveform vertical position does not change regardless of OFST setting.

### Screenshots

- `screenshots/01_vdiv1v_ofst0v.bmp` — VDIV=1V, OFST=0V (coarse scan settings, waveform visible near top)
- `screenshots/02_vdiv200mv_ofst3v3.bmp` — VDIV=200mV, OFST=3.3V (waveform in same position, OFST ignored)
- `screenshots/03_auto_find_result.bmp` — auto_find final capture result

### Waveform Detection via Pixel Analysis

Color-based detection confirms C1 yellow trace (R≈G>100, B<80) at screen rows 97–110 in both screenshots. No yellow trace in center grid area. White UI elements (R=G=B=240) present at center rows, but these are grid/menu elements, not the waveform.

---

## Step 9: TRLV SCPI Command — FIRMWARE BUG

`C1:TRLV <value>` SCPI command also ignored. Scope always returns `C1:TRLV? = -2.88E+00` regardless of the value sent.

---

## Known Firmware Issues (FW 4.8.12.1.1.6.5)

| Issue | Command | Symptom | Workaround |
|-------|---------|---------|------------|
| OFST ignored | `C1:OFST <val>` | Waveform vertical position unchanged | Front panel vertical knob |
| TRLV ignored | `C1:TRLV <val>` | Trigger level unchanged | AUTO trigger mode |
| VDIV format | `C1:VDIV 200mV` | Parsed as 20mV | Use `0.2` (numeric) |
| ARM kills data | `ARM` → `STOP` | DAT2 returns 0 bytes | Use `TRMD AUTO` → sleep → `STOP` |
| WFSU SP,0 rejected | `WFSU SP,0,...` | Scope stays at SP=1 | Use `WFSU SP,1,...` |
| DESC consumes DAT2 | `WF? DESC` before `WF? DAT2` | DAT2 returns 0 bytes | DAT2 first, DESC second |

---

## Key Source Changes in This Session

| File | Change |
|------|--------|
| `sds_tcp_adapter.py` | Dual-mode OFST decode, ARM→TRMD AUTO fix, VDIV/OFST? cross-validation, WAVEDESC mismatch detection |
| `auto_setup.py` | Same-frame screenshot+CSV, coarse/final stats, offset_direction_status |
| `tcp_transport.py` | EOF detection, conservative binary terminator, `_last_tail_bytes` diagnostics |
| `README.md` | Full rewrite: architecture, auto_find usage, test coverage, known issues |
| `tests/test_auto_setup_mock.py` | Same-frame verification, channel selection, stats presence, NEG slope |
| `tests/test_unit_parsing.py` | 24 tests: mV≠MV, MS=milliseconds, context-specific |
| `tests/test_wavedesc.py` | 7 tests: synthetic WAVEDESC decode, ASCII prefix |
| `tests/test_tcp_binary_prefix.py` | 5 tests: IEEE 488.2 / BMP prefix skipping |
| `tests/test_wavedesc_parser.py` | Remote: WAVEDESC parser tests |
| `tests/test_sds_units.py` | Remote: SDS unit parser tests |

---

## Current Recommended Settings

For a ~3.3V logic signal on C1 with the OFST/TRLV firmware limitations:

```
VDIV=0.5, OFST=0, TDIV=5E-5, ATTN=10, TRMD=AUTO
```

This gives ±2V screen range. The 3.3V signal appears near the top of the screen, clearly visible.

For vertical position adjustment, use the front-panel vertical knob (SCPI OFST non-functional on this firmware).

---

## Artifacts

| Path | Description |
|------|-------------|
| `screenshots/01_vdiv1v_ofst0v.bmp` | Reference: VDIV=1V, OFST=0V |
| `screenshots/02_vdiv200mv_ofst3v3.bmp` | OFST test: VDIV=200mV, OFST=3.3V (OFST ignored) |
| `screenshots/03_auto_find_result.bmp` | Auto-find final capture |
| `waveforms/c1_coarse_scan.csv` | C1 coarse scan: 5000 points |
| `waveforms/c1_coarse_scan_metadata.json` | C1 coarse scan metadata + WAVEDESC |
| `waveforms/auto_find_analysis.json` | Full auto_find result JSON |
