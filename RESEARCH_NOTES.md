# Mokka ECU Lab research notes

[v0.2-discovery.md](research/v0.2-discovery.md) records the consulted primary standard edition, ELM/STN documentation, reported Peugeot DIDs and addressing/session caveats, actual software compatibility evidence still needed, and exact steps for one deferred consolidated standard vehicle session. OEM DIDs remain offline; no session transition or new vehicle support claim was made. Older findings below describe the original delivery.

Research date: 12 October 2026. Vehicle, COM4 and previous app readings below are owner-provided observations. The car was unavailable during development. No serial connection, ECU identity, support bitmap, or manufacturer-specific decoder has been validated on this vehicle.

## Adapter communication evidence

The official [OBDLink Family Reference and Programming Manual, revision E](https://www.scantool.net/scantool/downloads/678/obdlink_frpm_e.pdf), sections 6–8, documents 8N1, carriage-return command termination and the `>` readiness prompt. Wait for that prompt before sending another command. A bare carriage return repeats the last command. Bluetooth baud depends on the device and cannot be changed as USB UART baud can. `ATI` reports ELM compatibility; `STI` reports STN firmware identity. MX+ variants include STN2255/2256, so do not infer hardware identity from the ELM string. Echo, linefeed, space and header controls configure adapter output. `ATM0` disables protocol memory; `ATSP0` explicitly stores the protocol preset, while `ATTP` is a compatibility command for trying a protocol. `ATDP`/`ATDPN` describe the selected protocol. `NO DATA` has several possible causes, including timeout and unsupported requests; it alone does not establish PID support.

The official [Windows connection guide](https://support.obdlink.com/support/solutions/articles/43000727094) supports Windows 11 and distinguishes pairing and application connection. The owner's outgoing COM4 is the preferred selection; COM3 is the incoming port. Close OBDwiz and other clients before using the same outgoing port. Port availability is not evidence of ECU communication.

Project recommendations: use a finite explicit adapter-command allowlist; do not expose a general AT/ST terminal. Disable adapter protocol memory before protocol discovery, and favor a non-saving protocol selection. Host serial baud candidates are compatibility trials, not proof of the MX+ Bluetooth module's physical baud. Log the candidate and result, cap each attempt, and require a prompt and identification response. Never use firmware, programmable-parameter, voltage calibration, identifier-writing, arbitrary-header or gateway-unlock commands.

## Standard Mode 01 evidence

The official [ELM327 datasheet](https://www.elmelectronics.com/wp-content/uploads/2017/01/ELM327DS.pdf), printed pages 32–33, demonstrates `0100`, positive responses `41 PID`, four support bytes, coolant `A-40` and RPM `(256A+B)/4`. It also describes multiple ECU replies. Parse each reply separately, retaining its header and raw bytes. A positive reply must match both service and requested PID.

For a support base `b`, interpret `ABCD` as a big-endian 32-bit mask. Bit 31 represents `b+1`; bit 0 represents `b+32`, including the next support bitmap. Query `0100`, then `0120` only when advertised, then `0140` only when advertised. Those three blocks cover this release's sensors. Track support per ECU, and mark failed discovery unknown rather than assuming every measurement is supported. An absent bit in a valid support response is evidence of non-support for that responder.

The normative registry is [SAE J1979-DA](https://saemobilus.sae.org/standards/j1979da_201702-j1979-da-digital-annex-e-e-diagnostic-test-modes). Its paid annex was not acquired. The following formulas were independently cross-checked against original upstream [python-OBD command definitions](https://github.com/brendan-w/python-OBD/blob/master/obd/commands.py), [decoder implementation](https://github.com/brendan-w/python-OBD/blob/master/obd/decoders.py) and [unit/scaling definitions](https://github.com/brendan-w/python-OBD/blob/master/obd/UnitsAndScaling.py), accessed on the research date. These are implementation references, not vehicle-validation evidence. Mokka ECU Lab uses its own direct serial implementation.

| PID | Meaning | Payload bytes | Formula | Original unit |
|---|---|---:|---|---|
| 04 | Calculated engine load | 1 | `100*A/255` | % |
| 05 | Engine coolant temperature | 1 | `A-40` | °C |
| 0B | Intake manifold absolute pressure | 1 | `A` | kPa absolute |
| 0C | Engine speed | 2 | `(256*A+B)/4` | RPM |
| 0D | Vehicle speed | 1 | `A` | km/h |
| 0F | Intake air temperature | 1 | `A-40` | °C |
| 10 | Mass air flow | 2 | `(256*A+B)/100` | g/s |
| 42 | Control module voltage | 2 | `(256*A+B)/1000` | V |
| 46 | Ambient temperature | 1 | `A-40` | °C |
| 5C | Engine oil temperature | 1 | `A-40` | °C |

`A` and `B` are unsigned data bytes after service and PID, with `A` most significant for two-byte quantities. Exact byte counts and positive response matching must precede numerical decoding. Standard verification means the generic formula is established; vehicle verification additionally requires real raw replies and physical cross-checks. Preserve original units when presenting conversions: °F = 1.8°C + 32, mph = km/h / 1.609344, bar = kPa / 100, kg/h = g/s * 3.6. MAP cannot be labeled gauge boost without a reliable ambient-pressure reference.

## Manufacturer-specific boundary

No Opel/PSA/Stellantis request identifier, address, DID, payload layout, byte order or scaling for DPF, AdBlue/SCR, regeneration state/history, soot estimates, requested boost or differential pressure has been verified. Selecting a Peugeot profile and receiving bytes does not establish that this Mokka has the named ECU or that the profile's interpretation is correct.

The official [Stellantis Independent Operator Portal](https://www.stellantisiop.com/) provides access routes to manufacturer repair information; its [standard access page](https://stellantisiop.com/iop/app/landing/standard_access) routes Opel/Peugeot/Citroën/DS repair information through Service Box. These are research entry points, not published PID evidence. No subscription, purchase, account registration or communication with third parties was performed.

The current app's live allowlist remains limited to selected standardized Mode 01 requests. Manufacturer candidates belong in offline research records only. A future live candidate needs source document/version, matching ECU identity, exact request and expected response, evidence that the request is read-only, decoder validation and explicit owner confirmation; confirmation does not override the current release's technical allowlist.

See [research/hypotheses.md](research/hypotheses.md) for the owner-reported anomalies and reproducible offline experiments. No candidate below is a diagnosis or a trusted vehicle measurement.
