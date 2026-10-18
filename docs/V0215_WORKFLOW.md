# Offline evidence and passive verification

Normal acquisition remains **Connect → Start Session → Finish Session**. Finish retains a healthy CONNECTED IDLE handle without background requests. Disconnect closes it. Unsafe prompt/port/OS conditions fail closed; a later explicit run refreshes its evidence.

Open **PID Evidence Explorer** in the left menu (Ctrl+Alt+P). Import one to sixteen original private Research Bundles. Select the exact checksum/source/context, then search or filter advertised identifiers, positive responses, repeated polling, RAW-only readings, unknown definitions, status/history, configuration, unavailable subfields or stale fields. Expand a PID to see its individual fields. Select a row for plain-language definition, validity, timestamps, cadence and unknowns; complete technical JSON is optional.

Bitmap advertisement, same-responder positive framing, exact length, reserved/layout checks, numeric replay and repeated polling remain separate evidence. The observed CAN address is not an authenticated ECU or vehicle identity. One request can yield many fields and flags; it does not establish a physical sensor count. Numeric validity does not establish calibrated physical accuracy or overall vehicle health.

Definition formulas describe the documented base encoding. Prior supported range configuration can override MAP/MAF scaling; inspect the configuration rows and source references when auditing those values. Definition units and last valid replay units are separate CSV columns, so an unavailable field does not acquire a measured unit. Attempt counts describe functional wire requests in the selected source context and must not be summed across responder groups as additional transmissions.

Age is measured at the end of the selected recorded source context. Intervals are based on actual recorded timestamps, with median/p95/maximum and severe gaps relative to an unambiguously matching worker profile. Discovery and preparation are distinct from recurring polling. Missing profile information is UNKNOWN, never zero. Different recordings and operating conditions are not joined into one trace.

**Export private CSV + JSON** writes fresh files outside Git/link trees without overwriting originals. JSON contains all evidence/definition/unknown fields; CSV has one row per relevant PID field, including RAW-only/no-field identifiers. Private evidence stays local. CLI equivalent:

Source audit distinguishes the SHA-256 of the exact selected input ZIP, the canonical checksum-covered member manifest and the original journal. When a complete run wrapper is selected, its container digest identifies that wrapper, not its inner original ZIP. Equivalent contents remain deduplicated even when ZIP compression or member order differs.

```powershell
python -m mokka_ecu_lab --explorer-bundles C:\Private\original-research.zip --explorer-output C:\Private\evidence.json
```

The offline 0101 paste tool accepts exactly four DATA bytes. It sends nothing and does not associate user-pasted bytes with imported vehicle evidence. Its documented composite source basis and lack of LIVE admission are explicit. Readiness completion does not prove a fault-free monitor or DPF regeneration.

After Finish, optionally press **Verify 60s silent idle** while parked. It observes only the local handle and global admitted-send ledger. The first terminal transition freezes the duration and evidence. **PASSED** means at least sixty seconds of bounded passive continuity and zero admitted send attempts; it does not establish remote ECU liveness. A delayed passive check exceeding fifteen seconds interrupts verification without asserting a specific root cause.

Open the immutable report/folder or copy its exact path. Receipts live under `PostExportEvidence/<session-id>/`, checksum-linked to the unchanged original ZIP. History / Reports offers **Post-Finish verification reports** for the selected run. Later connection state/reason is shown separately. Partial receipt writes never publish a truncated final JSON; retry adopts only byte-identical existing evidence.

Installation still requires exact owner approval of the official SHA-verified build and CURRENT change. The same stable Desktop/Start Menu shortcuts follow that approved CURRENT, with the previous build retained as rollback. Publication alone does not install or activate a release.

Normal LIVE remains READ-ONLY Mode 01 with the existing allowlist, one serialized worker and at most four aggregate requests per second, including initialization. The five/s byte engine remains fake COM only; physical higher-rate tests need a separately reviewed build and fresh exact operator authorization. See [physical readiness gaps](V0214_PHYSICAL_BENCHMARK_READINESS.md).
