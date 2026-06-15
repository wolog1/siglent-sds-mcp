# Capture recipe: screenshot verification

## Goal

Verify the SDS824X HD screenshot command and image data format before exposing `screenshot` as a default MCP tool.

The upstream reference project uses:

```text
SCDP
```

and receives BMP image data, then converts it to PNG for MCP image output.

For SDS824X HD, `SCDP` is a candidate command until verified.

## Verification plan

### Step 1: query identity

```text
*IDN?
```

Record model and firmware.

### Step 2: execute candidate screenshot command

```text
SCDP
```

Record response form:

- plain raw BMP starting with `BM`
- IEEE 488.2 binary block containing BMP/PNG/JPEG
- error response
- timeout

### Step 3: parse image header

If response starts with BMP magic:

```text
0x42 0x4D = "BM"
```

Read:

- file size
- pixel offset
- width
- height
- bits per pixel
- compression type

If response starts with `#`, parse as IEEE 488.2 definite-length block first.

### Step 4: convert to PNG

Use a robust image conversion path:

- Python: Pillow optional dependency
- Node upstream pattern: sharp
- fallback: store raw BMP and return file path

## Output format

```text
artifacts/screenshots/<timestamp>_sds824xhd.png
artifacts/screenshots/<timestamp>_sds824xhd.raw.bmp
```

Metadata:

```json
{
  "instrument": "SIGLENT,...",
  "command": "SCDP",
  "raw_format": "BMP",
  "width": 1024,
  "height": 600,
  "converted_format": "PNG"
}
```

## Acceptance criteria

- [ ] screenshot command confirmed from SDS800X HD Programming Guide
- [ ] response framing confirmed on real SDS824X HD
- [ ] image parser handles BMP and IEEE binary block cases
- [ ] output PNG can be displayed by MCP client
- [ ] raw binary artifact is retained for debugging
