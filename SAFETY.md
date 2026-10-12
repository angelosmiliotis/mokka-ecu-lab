# Read-only safety boundary

v0.2.2 uses exactly the v0.2.0 request permissions below. Preset preparation, checkbox edits and offline trends never send requests. Explicit Start rechecks ECU-specific support and valid numeric fields. Separate RAW-only 017A/0188 opt-ins require a complete prior positive response from that ECU after completed discovery and have fixed weight 1; they cannot create measurements or a health/SCR verdict. Frame/negative/transport failures retain the stop/reconnect rule. Cached RPM/speed context requires no extra query. OEM candidates stay offline. Journey markers are local journal events. Research Bundle export requires a closed session, is local, redacts identifiers/free-text notes by default and preserves original journals. See [DRIVE_CAPTURE.md](DRIVE_CAPTURE.md).

Version 0.2 allows only SAE Mode 01 reads from fixed code-owned sets. `SafeTransport.exchange` validates at the last public boundary before serial writes. It rejects carriage returns, whitespace, command chaining, extra bytes, empty repeats, arbitrary AT commands and all other diagnostic services. Sensor JSON cannot broaden this boundary.

## Exact live policy

- Support requests: `0100`, `0120`, `0140`. The latter two are sent only if a previous bitmap advertises the next page.
- Sensor requests: `0104`, `0105`, `010B`, `010C`, `010D`, `010F`, `0110`, `0142`, `0146`, `015C`. A sensor request additionally requires advertised ECU support. Decode is checked per ECU.
- Adapter commands: `ATI`, `STI`, `ATE0`, `ATL0`, `ATS1`, `ATH1`, `ATM0`, `ATTP0`, `ATST64`, `ATDP`, `ATDPN`.

`ATI`/`STI` identify the interpreter. E/L/S/H set host-facing formatting. `ATM0` disables saving the last protocol; `ATTP0` tries automatic protocol selection without the persistent save used by `ATSP0`. `ATST64` configures a runtime response timeout (0x64 × 4 ms). DP/DPN describe protocol. This behavior is based on the official [OBDLink Family Reference and Programming Manual](https://www.scantool.net/scantool/downloads/678/obdlink_frpm_e.pdf) and [ELM327 datasheet](https://www.elmelectronics.com/wp-content/uploads/2017/01/ELM327DS.pdf). Genuine hardware has not yet been tested with this implementation.

No bare CR is used: it can repeat a previous command. No ATZ/reset, persistent programmable parameter, ATSP save, custom transmit header, security access, UDS routine, coding, actuator command, DTC clearing, forced regeneration, firmware operation or gateway bypass is present. VIN Mode 09 is absent. Manufacturer queries are absent even when a JSON definition is EXPERIMENTAL or manually relabeled.

## Explicit standard Discovery scope

Initialization retains the basic policy above. Explicit user-started CAN Discovery enables continuation pages 0160/0180/01A0/01C0/01E0 only through the selected ECU's preceding advertised chain. Fixed standard reads 0173/0178/0179/017A/017B/017C/017F/0183/0185/0186/0188/018B require that ECU's support. Unsupported and unknown requests are not probed. The scope closes on scan completion; monitoring requires another explicit action. Stop revokes the scope.

Fixed ATCAF1/ATCFC1/ATAL configure documented automatic formatting, adapter ISO-TP flow control and long-message reception during Discovery. No manual CAN/flow-control frames or arbitrary headers are exposed. The application cap remains 4 requests/s; interpreter-generated CAN transport frames are not individual application requests. Headerless or legacy live advanced discovery is disabled.

D525/D526/D52F/D532 remain offline candidates without numeric decoders. No UDS session/security/OEM request is allowed. Future approval requires exact ECU hardware/software/calibration evidence and reviewed read-only semantics; another PSA vehicle's address is insufficient. See [research and consolidated validation steps](research/v0.2-discovery.md).

## Operation and limitations

Live connections never start on normal program launch. The developer `--smoke-test` flag explicitly uses the default Simulation source only. Total requests, including adapter initialization, are capped at four per second and may be reduced to 0.25 per second. One worker owns the connection. Stop immediately sets the cancellation flag, preventing future sends and interrupting waits. An already-transmitted request cannot be recalled. Serial receive observes cancellation within approximately 50 ms; an in-flight OS serial write has a 300 ms bound. Disk flushing and port open/close are not instantaneous but do not initiate new ECU requests after Stop. Disconnect releases serial in the worker.

No automatic reconnect or baud sweep occurs. Missing prompt, serial disconnect and framing overrun close the transport; reconnect requires a user action. Three consecutive invalid or negative ECU responses stop polling and latch an explicit-reconnect requirement. `7F 01 22` is Conditions Not Correct, not a transport timeout or proof of ignition state. Cached measurements are marked stale when stopped/rejected. No automatic NRC retry, pending-response retry, PID brute-force scan or unknown address scan is implemented. Protocol autodetection is delegated to the adapter's documented normal OBD procedure.

Before switching ignition off: Stop Recording and Stop polling, then Disconnect. Finish session submits Stop polling followed by Stop Recording; either manual Stop order is supported. Disconnect/application shutdown finalizes an open journal and SQLite session. Optional weights 1–4 divide the unchanged aggregate rate among existing selected supported PIDs; they cannot authorize a new request. Simulation and replay are labeled separately from live ECU readings, and stale values do not count as current connection coverage.

Read-only OBD traffic still wakes the adapter/ECU and consumes bus and battery resources. This software does not prove OEM gateway compatibility, electrical compatibility or that every firmware version handles the commands identically. It is not a repair, regeneration or emissions-compliance decision system. Validate stationary first and follow the vehicle/adapter instructions. Do not operate the GUI while driving.

Future manufacturer queries require documented read-only semantics, known request/response source, evidence review and explicit user authorization before changing the live policy. Decoder meaning needs independent physical validation. The current build has no mechanism to enable such a request through the GUI.

## Privacy and public sharing

Private vehicle bundles, raw logs, CSVs, route timelines, supplied analysis and derived private reports must remain outside the public repository and release packages. Public fixtures are independently constructed isolated responses with artificial values, no session/device/route identity and no route chronology. Software validation summaries and screenshots use simulation only. Local trend import does not extract ZIP members or write back to the input; CSV checksums are checked when supplied in the bundle.

No VIN request, cloud client, telemetry or upload code is present. Local original journals intentionally retain raw bytes. Default JSONL export redacts port, adapter string and ATI/STI reply bytes; decoded CSV excludes vehicle/adapter metadata. A diagnostic support checkbox retains original identifying information. Review raw payloads, ECU addresses, dates, operating patterns and file paths before sharing. Redaction does not guarantee anonymity; timestamps and measurements can still reveal usage patterns. Windows/OneDrive backup is external to the app.
