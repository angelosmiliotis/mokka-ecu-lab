# Read-only safety boundary

Version 0.1 allows only SAE Mode 01 reads from a fixed code-owned set. `SafeTransport.exchange` validates at the last public boundary before serial writes. It rejects carriage returns, whitespace, command chaining, extra bytes, empty repeats, arbitrary AT commands and all other diagnostic services. Sensor JSON cannot broaden this boundary.

## Exact live policy

- Support requests: `0100`, `0120`, `0140`. The latter two are sent only if a previous bitmap advertises the next page.
- Sensor requests: `0104`, `0105`, `010B`, `010C`, `010D`, `010F`, `0110`, `0142`, `0146`, `015C`. A sensor request additionally requires advertised ECU support. Decode is checked per ECU.
- Adapter commands: `ATI`, `STI`, `ATE0`, `ATL0`, `ATS1`, `ATH1`, `ATM0`, `ATTP0`, `ATST64`, `ATDP`, `ATDPN`.

`ATI`/`STI` identify the interpreter. E/L/S/H set host-facing formatting. `ATM0` disables saving the last protocol; `ATTP0` tries automatic protocol selection without the persistent save used by `ATSP0`. `ATST64` configures a runtime response timeout (0x64 × 4 ms). DP/DPN describe protocol. This behavior is based on the official [OBDLink Family Reference and Programming Manual](https://www.scantool.net/scantool/downloads/678/obdlink_frpm_e.pdf) and [ELM327 datasheet](https://www.elmelectronics.com/wp-content/uploads/2017/01/ELM327DS.pdf). Genuine hardware has not yet been tested with this implementation.

No bare CR is used: it can repeat a previous command. No ATZ/reset, persistent programmable parameter, ATSP save, custom transmit header, security access, UDS routine, coding, actuator command, DTC clearing, forced regeneration, firmware operation or gateway bypass is present. VIN Mode 09 is absent. Manufacturer queries are absent even when a JSON definition is EXPERIMENTAL or manually relabeled.

## Operation and limitations

Live connections never start on normal program launch. The developer `--smoke-test` flag explicitly uses the default Simulation source only. Total requests, including adapter initialization, are capped at four per second and may be reduced to 0.25 per second. One worker owns the connection. Stop immediately sets the cancellation flag, preventing future sends and interrupting waits. An already-transmitted request cannot be recalled. Serial receive observes cancellation within approximately 50 ms; an in-flight OS serial write has a 300 ms bound. Disk flushing and port open/close are not instantaneous but do not initiate new ECU requests after Stop. Disconnect releases serial in the worker.

No automatic reconnect or baud sweep occurs. Missing prompt, serial disconnect and framing overrun close the transport; reconnect requires a user action. Three consecutive invalid ECU responses stop polling. No uncontrolled retries, PID brute-force scans or unknown address scans are implemented. Protocol autodetection is delegated to the adapter's documented normal OBD procedure.

Read-only OBD traffic still wakes the adapter/ECU and consumes bus and battery resources. This software does not prove OEM gateway compatibility, electrical compatibility or that every firmware version handles the commands identically. It is not a repair, regeneration or emissions-compliance decision system. Validate stationary first and follow the vehicle/adapter instructions. Do not operate the GUI while driving.

Future manufacturer queries require documented read-only semantics, known request/response source, evidence review and explicit user authorization before changing the live policy. Decoder meaning needs independent physical validation. The current build has no mechanism to enable such a request through the GUI.

## Privacy and public sharing

No VIN request, cloud client, telemetry or upload code is present. Local original journals intentionally retain raw bytes. Default JSONL export redacts port, adapter string and ATI/STI reply bytes; decoded CSV excludes vehicle/adapter metadata. A diagnostic support checkbox retains original identifying information. Review raw payloads, ECU addresses, dates, operating patterns and file paths before sharing. Redaction does not guarantee anonymity; timestamps and measurements can still reveal usage patterns. Windows/OneDrive backup is external to the app.
