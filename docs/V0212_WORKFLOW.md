# v0.2.12 operator workflow

The application starts disconnected. Ordinary sessions and benchmarks use the
same read-only allowlist, one serialized worker and a hard ceiling of **four
total requests per second**. Filesystem maintenance and offline research do
not connect to the vehicle.

## Set up the stable CURRENT shortcut

Open the portable application's `MokkaECULab.exe` with its `_internal` folder
beside it. Open **App Versions** in the left menu; at compact window widths the
menu label is **Versions**.

1. Download the exact Windows ZIP from the project's GitHub Releases. In
   **App Versions**, enter its exact tag and choose **Install official release
   ZIP…**. Inspect the source, official SHA-256, full file list and new managed
   destination. Approve that copy only when the preview is correct. Installation
   runs an isolated synthetic startup check and does not activate the build.
2. Choose **Inventory / dry-run preview**. Select the verified build in the
   build selector, then **Set as CURRENT…**. Inspect and approve its pointer
   preview. Keep a verified previous stable build locally: selecting a later
   CURRENT retains the preceding CURRENT as ROLLBACK.
3. Select **Desktop shortcut** and, optionally, **Start Menu shortcut**. Choose
   **Preview CURRENT launcher setup…**. Review every new destination, size and
   SHA-256, plus the shortcut target, working directory and icon. Approve only
   that exact setup. Existing shortcuts and launcher files are preserved.
4. Choose **Verify stable launcher**. Close the running application, then open
   **Mokka ECU Lab** from the approved Desktop or Start Menu shortcut.

The stable target is
`%LOCALAPPDATA%\MokkaECULab\Launcher\MokkaECULabLauncher.exe`. Its configuration
selects the verified build through
`%LOCALAPPDATA%\MokkaECULab\Versions\current.json`; it does not point into the
developer `release` folder. Later approved CURRENT changes and **Rollback
preview…** use the same shortcut. Keep the entire managed build and its
`_internal` directory intact. A missing or altered build is blocked. If a new
build fails during startup, the verified previous pointer is restored; launch
that rollback explicitly.

The first launcher setup requires a verified v0.2.12-or-later package containing
the dispatcher. An existing managed launcher requires no new shortcut after an
upgrade. If an existing user shortcut or incomplete setup blocks installation,
inspect its exact files before proposing any replacement; the application does
not overwrite or remove it automatically.

## Normal drive

Choose the intended source in **Connection settings** and confirm the outgoing
Bluetooth port for LIVE use. A Simulation selection remains visibly synthetic.
On **Session Dashboard**:

1. Press **Connect**. Wait for the verified ECU and connection state.
2. Press **Start Session**. Discovery, eligible standard sensors, eligible
   RAW-only polling and recording are automatic. The default profile is
   **Comprehensive · all eligible sensors**. There are no individual PID or RAW
   checkboxes to configure.
3. Before moving, inspect **017A RAW research evidence**. Where supported, check
   that it is actually scheduled and at least two positive RAW replies have
   been stored. Unsupported or unavailable evidence must remain explicit.
4. When safely parked at the end, press **Finish Session**. Wait for finalization
   and the verified private export. Use **History / Reports** to open it.

For a separate cadence comparison, select the optional
**DPF + Turbo · critical subset only** profile before starting the session.
Its smaller selection does not change the four-request ceiling. RAW bytes and
asynchronous correlations do not establish a DPF physical unit, soot/ash value,
regeneration diagnosis or turbo response change.

## Stationary Benchmark

On **Benchmark**, select **1**, **2**, **3** or **4** requests/second, then press
**Start BENCH** only under the stationary conditions stated on the page. The
application handles connection, support confirmation, preparation, the fixed
60-second measurement, countdown, validation and private export. **Stop & save**
preserves a partial run.

With **Keep connected after success · zero idle traffic** selected, a successful
run remains **CONNECTED IDLE** with no idle diagnostic sends. The next explicit
benchmark performs fresh preflight. A normal Session can then use its own full
eligible selection. Use **Disconnect** when finished. A failed COM-open is a
connection failure, distinct from decoder layout errors or measured saturation.

## Reports and one-run sharing

New complete exports use one leaf folder per run under the selected data root:

```text
Reports/
  Drives/YYYY-MM-DD_HH-MM-SS_DRIVE_<stable-id>/
  Benchmarks/YYYY-MM-DD_HH-MM-SS_BENCH_4rps_<stable-id>/
  FailedTests/<timestamp_type_stable-id>/
```

There are no intermediate `YYYY/MM/DD` directories. Folder times use
`Europe/Athens`; metadata retains the original UTC identity. The stable ID
distinguishes runs with the same local timestamp, including daylight-saving
transitions. Each new complete run contains:

- `original-research.zip`: recorded evidence and its integrity information.
- `report.json`: structured offline analysis.
- `report.html`: readable offline report.
- `run-metadata.json`: identity, outcome, source hashes and time information.

On **History / Reports**, select one row and choose **Open report**, **Open
folder**, or **Export this run ZIP…**. The last action creates one private share
wrapper at the fresh destination you choose; another wrapper is not generated
automatically after each run. Optional annotations are explicitly user-reported
offline notes. An **EXPORT_PARTIAL** result retains evidence and can be repaired
with **Retry report offline**. Previously preserved partial legacy companion
backups remain available even if that means the repaired legacy folder contains
additional `source-report` files.

To flatten old deep report folders, use **Organize Reports… → Flatten existing
Reports…**. Inspect the exact old/new mapping, hashes, copy bytes and index
changes before approving. This copies and verifies, then selects one canonical
History location per identity. Original deep folders, recording journals,
session databases, labels and annotations remain available. Repeated verified
imports reuse the same History identity.

**Cancel copy migration** stops between safe checkpoints. After cancellation or
restart, choose **Organize Reports… → Resume report migration…**, select the
interrupted checkpoint and approve its complete stored plan again. It resumes
the same verified copies rather than starting another migration. **Rollback
report migration…** previews index pointer changes only; both old and copied
folders are retained. Removing old originals would require a separate exact
preview and approval.

## Review the actual developer release workspace

**Workspace / Storage** (compact label **Workspace**) is separate from
**App Versions**. Visiting it does not scan, move or delete anything.

1. Use **Choose exact release…** to select the actual Git checkout's `release`
   folder. Choose **Inventory exact folder**. Review each path, policy,
   file count, bytes, tree SHA-256 and reason. The private export contains the
   detailed file inventory. **REVIEW** indicates unverified provenance, not that
   a folder is disposable.
2. Preserve the current official package, a verified local rollback, active
   executables and any unknown or personal content. **KEEP** and **BLOCKED**
   entries cannot be selected. Review the contents of each remaining candidate
   yourself before checking it and acknowledging the review checkbox.
3. Choose a fresh private quarantine directory on the same volume, outside the
   entire checkout and its sync boundary. Choose **Preview checked moves…**.
   Inspect the exact source/destination list, retained entries, bytes and hashes.
   **Export private inventory / plan…** saves a fresh local review file outside
   Git. No move occurs until the explicit approval button is pressed.
4. Approval performs reversible atomic moves and verifies every byte. The
   private quarantine's `operation.json` records progress. **Cancel between
   entries** finishes the current atomic item and leaves remaining items in
   place. **Resume receipt preview…** requires a new explicit review of the
   saved receipt. **Restore receipt preview…** reverses approved moves only
   when the original paths are free and the preserved hashes match.

Quarantine removes clutter from the selected workspace but frees **zero disk
bytes**: its files still exist on the same disk. No deletion API or background
purge is provided. Original journals, databases and detected private/unknown
research evidence are excluded from cleanup candidates. Inventory, approval
and export files themselves are private and must remain outside public GitHub,
public screenshots and release assets.

## Development output boundaries

The source checkout is for code. Managed CURRENT/ROLLBACK builds live under
`%LOCALAPPDATA%\MokkaECULab\Versions`; ordinary personal data defaults to
`%LOCALAPPDATA%\MokkaECULab\data`. Developer candidates and validation outputs
default under `%LOCALAPPDATA%\MokkaECULab\Development\v0.2.12`, outside the
checkout and OneDrive. These locations serve different purposes.

`build.ps1` accepts a fresh output directory. Its default **Candidates** cache
stops after three retained candidates and requests explicit review instead of
deleting old outputs. Its fresh per-invocation PyInstaller scratch is removed
after checking the cleanup boundary. Default development validation helpers
also stop after three outputs per purpose; an explicit fresh `--output-dir`
is an operator choice. Existing `release` entries are not cleaned by a build.

## Higher-rate research remains offline

Open **Higher-rate research** (compact label **Higher rate**).
**Experimental LIVE · LOCKED** has no hardware action or configuration unlock.
**Run OFFLINE model** models constructed rates from 1 to 6, with virtual time,
fault injection and **Stop model**. Its actual OBD transmission count is zero.

**Export engineering brief** describes a proposed separate, stationary
five-request/second, 60-second experiment and its explicit authorization and
engineering review requirements. A later six-request experiment needs a new
review and authorization. These controls do not change ordinary LIVE limits or
prove hardware capacity. See [the experimental boundary and proposal](V0212_EXPERIMENTAL_BENCHMARK.md).

This workflow describes the implemented controls. It does not assert that a
particular computer has already been cleaned, a shortcut installed, a real
hardware trial completed or a release published.
