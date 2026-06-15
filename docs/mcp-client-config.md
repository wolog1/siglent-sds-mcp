# MCP client configuration

## Local Python stdio server

After installing the project locally:

```bash
pip install -e '.[dev]'
```

Use this MCP configuration pattern:

```json
{
  "mcpServers": {
    "siglent-sds": {
      "command": "python",
      "args": ["-m", "siglent_sds_mcp.server"]
    }
  }
}
```

## Docker stdio server

Build locally:

```bash
docker build -t siglent-sds-mcp:local .
```

MCP configuration:

```json
{
  "mcpServers": {
    "siglent-sds": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "siglent-sds-mcp:local"]
    }
  }
}
```

## Typical AI workflow

Once the MCP server is started, ask the AI client to call tools in this order:

```text
connect_tcp(host="<scope-ip>")
identify_tcp()
get_channel_tcp(channel="C1")
configure_channel_tcp(channel="C1", vdiv="1V", offset="0V", coupling="D1M", trace=true, probe=10)
configure_acquisition_tcp(timebase="1US", trigger_mode="SINGLE", trigger_source="C1", trigger_level="1.5V", trigger_slope="NEG", command="single")
screenshot_tcp()
get_waveform_tcp(channel="C1", max_points=5000)
analyze_uart_csv_file(csv_path="<returned csv>", baudrate=2000000)
```

## Notes

- TCP tools assume the oscilloscope is reachable from the machine running the MCP server.
- Candidate default TCP port is `5025`.
- Screenshot/waveform commands are implemented using SDS-style candidate commands and must be verified on SDS824X HD hardware.
