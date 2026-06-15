# Capture recipe: waveform export verification

## Goal

Verify how SDS824X HD exports waveform data over SCPI before enabling `get_waveform` as a default MCP tool.

The upstream reference project uses SDS1000X-E style commands such as:

```text
WFSU SP,0,NP,0,FP,0
C1:WF? DAT2
C1:VDIV?
C1:OFST?
TDIV?
SARA?
```

For this project, these are **candidate commands only** until verified against SDS800X HD Programming Guide and actual SDS824X HD hardware.

## Verification plan

### Step 1: identity and header mode

```text
*IDN?
CHDR OFF
*IDN?
```

Record whether `CHDR OFF` is supported and whether it changes numeric query responses.

### Step 2: simple scalar queries

Candidate queries:

```text
C1:VDIV?
C1:OFST?
TDIV?
SARA?
```

Alternative modern SCPI tree candidates:

```text
:CHANnel1:SCALe?
:CHANnel1:OFFSet?
:TIMebase:SCALe?
:ACQuire:SRATe?
```

### Step 3: waveform setup

Candidate upstream command:

```text
WFSU SP,0,NP,0,FP,0
```

Need to confirm:

- exact parameter meaning
- whether SDS824X HD supports it
- whether it affects current memory or displayed waveform
- whether maximum point count can be controlled safely

### Step 4: waveform query

Candidate upstream command:

```text
C1:WF? DAT2
```

Need to confirm:

- binary block framing
- raw sample width: 8-bit, 16-bit, float, or other
- signedness
- voltage reconstruction formula
- time axis reconstruction formula
- record length behavior
- channel naming: `C1` vs `CHANnel1`

### Step 5: binary block parser

The transport layer should support IEEE 488.2 definite-length block format:

```text
#<digit_count><length_digits><binary_data><trailing terminator>
```

Example:

```text
#9000012345<12345 bytes>
```

## Output format

The MCP should write CSV like:

```csv
time_s,voltage_v
-0.000005,3.298
-0.000004999,3.295
```

and JSON metadata like:

```json
{
  "instrument": "SIGLENT,...",
  "channel": "C1",
  "sample_rate": 1000000000,
  "total_points": 100000,
  "returned_points": 5000,
  "timebase_s_per_div": 0.000001,
  "vertical_scale_v_per_div": 1.0,
  "offset_v": 0.0,
  "source_commands": ["..."]
}
```

## Acceptance criteria

- [ ] exact SDS824X HD waveform commands confirmed from official guide
- [ ] scalar parameter queries verified on real hardware
- [ ] binary block parser tested with captured response
- [ ] voltage conversion validated against front-panel reading
- [ ] time axis validated against known signal frequency/baudrate
- [ ] `get_waveform` tool marked safe only after verification
