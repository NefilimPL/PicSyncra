# Controller startup investigation — 2026-10-05

Reported failure: the installed WEB manager in Windows Sandbox on another
computer displayed "Kontroler instalacji nie uruchomil backendu WWW", including
when started as administrator.

Three independent Windows integration failures were reproduced:

1. The installer `/TR` quoting split a `Program Files` executable path into
   multiple command arguments. Registration now uses one correctly escaped
   task action and checks both scheduler command exit codes.
2. Pipe authorization passed a primary process token to
   `CheckTokenMembership`, which requires an impersonation token. Native
   Windows testing returned error 1309. The caller token is now duplicated
   for membership testing and every acquired handle is closed. The SYSTEM /
   Administrators ACL is unchanged.
3. With authorization working, a real controller start failed at
   `win32job.CreateJobObject(None, None)`: pywin32 rejected the name as a
   non-string. An empty name creates the intended anonymous job. The native
   job regression verifies that closing the job terminates its owned child.

The previous direct frozen WEB smoke test did not exercise these boundaries.
The replacement smoke check invokes the real manager start/stop functions,
named-pipe transport, dispatcher, controller, Windows Job Object and frozen
WEB in an isolated build directory. It verifies the health endpoint and
static UI. Its test pipe permits the current test user only; it does not
create a scheduled task or HKLM registration. Administrator token membership
and Windows task-command parsing are covered by separate native regressions.
The user subsequently confirmed that the corrected installer starts the panel
in Windows Sandbox on the other computer.

Verification results:

- Whole suite: 1906 passed, 3 skipped, 66 subtests passed (25 existing
  deprecation warnings).
- Focused installer, controller and update tests: 32 passed.
- Real manager-to-controller start/stop smoke: passed, with a healthy frozen
  WEB process and a served static UI.
- Executed the packaged controller's embedded bytecode against native Windows
  APIs: anonymous job creation and process-token membership both passed.
- `git diff --check`: passed.
- Final Inno Setup compilation: exit 0, no compiler warnings. The corrected
  artifact is `dist/installer-fixed/PicSyncra-Setup-1-fixed.exe`; the normal
  `dist/installed/PicSyncra-Setup-1.exe` is an identical verified copy.

Publication status checked through the public GitHub API on 2026-10-05:

- Latest release `v0.5.5` has only the three portable EXE assets.
- The active workflow list does not include `build-installer.yml`.
- The local installed-package workflow defines four component ZIP assets
  and a signed manifest, but those assets are not currently published.
- The updater downloads the complete non-OCR release bundle. Installed OCR
  is updated with it; absent OCR is not downloaded. Independent updates of
  only changed WEB/Migrator/LOCAL modules are not implemented.
- The local trusted-public-key mapping is empty, so a local unsigned build
  deliberately cannot accept remote updates.

## Missing OCR/update controls in the installed WEB panel

The installed WEB HTML referenced `installation-updates.js` and
`legacy-migration.js`, but the builder's static-asset list omitted both. The
shipped directory confirmed their absence. Without `InstallationUpdates`,
the renderer returns before creating the installed-update controls, including
the OCR download button. This affects local builds and Actions builds alike.

Both scripts are now packaged. The existing build harness now checks that all
static assets referenced by the packaged main and login pages are present.
It failed on those two missing scripts before the fix and passed afterward.
Verification: 25 focused Python tests and 4 JavaScript updater tests passed;
the real controller/frozen-WEB smoke served both scripts with the expected
contents. Inno Setup compiled the replacement installer successfully.

Artifact: `dist/installer-updates-fixed/PicSyncra-Setup-1-updates-fixed.exe`.
SHA256: `CAAE731E63739A2B342871E1A4EC7CDB5708D8726124338578ACBE469BE9AA6E`.
The button alone does not provide an OCR download source: signed installed
release assets and compiled trusted public keys are still required.

## Modular installer acceptance — 2026-10-05, dev2

The release-only limitation above describes the earlier installer. The current
implementation uses independent module identities, signed schema-2 manifests,
exact HTTP ranges, one controller transaction, and shared WEB/launcher plans.
Rollback selections remain drafts until confirmation; successful rollback pins
those modules across client and controller restarts. LOCAL and Migrator hold an
installation lease before loading application code and throughout their lifetime.

Independent whole-change review found and prompted regression fixes for broken
WEB startup, stale maintenance after interruption, unsafe manual start after
failed recovery, standalone writers, application payload ownership, configuration
inspection, and disk/write preflight. Follow-up review checked the missing-set
recovery path and host-selection race. An unhealthy restored backend is stopped
and remains gated in `recovery_required`.

Fresh verification of the final source and local build:

- Python: **1972 passed, 3 skipped, 66 subtests passed**, with 25 existing
  deprecation warnings. Log: `build/modular-full-tests-acceptance.log`.
- Browser JavaScript: **39 passed**; edited scripts pass `node --check`.
- Emitted assets reconstructed: **11 modules** in the local no-OCR build;
  controller/content/recovery acceptance: **12 passed**.
- Real Windows named pipe, dispatcher, controller and Job Object launched the
  selected frozen WEB; health and module-related static assets were served.
- Actual frozen launcher EXE with packaged Tcl/Tk read the catalog through a
  real pipe, selected two modules, prepared one rollback plan and canceled it
  with both choices preserved and zero execution requests. The isolated test
  registration provider and UAC bypass are test hooks, absent from production.
- Separate frozen selected-import probe loaded old FTP/current SQL and refused
  startup after the selected FTP file disappeared.
- **22 critical packaged modules** match the reviewed source bytecode in the
  controller, launcher and WEB/Migrator/LOCAL hosts.
- Repeated full installer compilation: exit 0; final Inno compile 306.735 s.
  `git diff --check` passed.

Artifact: `dist/installed/PicSyncra-Setup-1.exe` (378,960,509 bytes).
SHA256: `C91EBED5E96E8164ABE0F6C5545470C1F1A099183AC38965B64C4701EF1BC855`.

The acceptance fixtures do not modify HKLM or register scheduled tasks. Native
Tk smoke required execution outside the test sandbox's Tcl restriction; the
packaged GUI passed. Interruption recovery is tested with injected process
failure and real SQLite/configuration files, not a physical power interruption.
Real GitHub publication/signing secrets and downloading full OCR models remain
external release steps. No Release was published and no production signing key
was created or changed. The local installer has no compiled trusted public key,
so it displays controls but cannot download an official unsigned OCR/update
source. Actions must publish signed complete module assets from the release tag.

## Dev channel and CI import correction — 2026-10-09

The supplied Windows/Python 3.11 Actions log reported 17 collection errors:
`web.app` imported the installed pipe transport, whose global `winerror` import
required pywin32. CI installed build/WEB/Qt requirements but omitted the installed
requirements. CI now installs and caches `requirements-installed.txt`; pushes
to `dev2` also trigger checks. `winerror` is imported only when serving a native
pipe, so portable WEB remains importable without pywin32. A subprocess test
blocks all Windows dependency imports and verifies this boundary.

Initial module-layout metadata carries the release channel. Fresh installations
initialize it, while existing choices and repair selections remain intact. WEB
and the launcher change the shared channel through the controller's authenticated
closed pipe API, which rejects changes while a module operation is running.
Both selectors preserve rollback drafts, their Release links and pins, marking
drafts absent from the new channel as unavailable.

Native hidden Tk GUI acceptance used a real authenticated Windows pipe and an
isolated installation under `build`: channel selection, unavailable drafts,
unchanged active modules/pins and restoration of the displayed channel after
busy rejection passed. No HKLM or scheduled tasks were modified. Python 3.11
Windows x64 wheels for both pinned installed dependencies were downloaded and
verified as available. The local test interpreter is Python 3.13; the new Actions
run remains to be executed after pushing the changes. The installer artifact
listed above predates this correction; a build from the new release tag includes
the updated controls and initialization.

Final validation: **1984 Python tests passed**, 3 skipped, 66 subtests passed;
**40 JavaScript tests passed**. Python compileall, both app/module-panel JS syntax,
workflow trigger sanity and `pip check` passed. Review identified the missing
draft-display case; its regression tests failed before the correction and passed
after it. Follow-up review found no further important issues.

## Release publication timestamp handoff — 2026-10-09

The supplied Actions build successfully packaged the OCR host, then rejected
the publication timestamp `10/09/2026 09:51:54` during module manifest creation.
PowerShell's JSON conversion had produced a DateTime object; implicit string
interpolation emitted a date unsuitable for the ISO/timezone manifest contract.
The release-resolution step now explicitly serializes DateTime/DateTimeOffset
values as invariant ISO UTC timestamps. ISO strings remain intact, and the
manifest's strict date validation is preserved.

Regression tests execute the workflow's metadata step with a stub GitHub CLI
and a JSON conversion wrapper exercising string, DateTime and DateTimeOffset
representations in en-US and pl-PL cultures. The DateTime case reproduced the
exact supplied error before the fix. All six representations now preserve the
publication instant and pass the real Python manifest builder. Local tests use
Windows PowerShell 5.1 and emulate PowerShell 7's date deserialization. The
existing signing/provenance workflow checks remain in place. A new Release tag
containing this correction is needed; re-running the old tagged workflow does
not incorporate the fix. Complete hosted build/publication remains external.

Validation: **52 targeted tests passed**, including the six timestamp cases,
repeated installed-build harnesses, module manifests and release/workflow checks.
`git diff --check` passed. This correction changes metadata handoff only; it
does not rebuild or publish release assets locally.

## Launcher OCR progress and pipe disconnect correction — 2026-10-09

The supplied log identifies GET `/api/installation` failing in native
`ReadFile` with Windows error 233. A real Windows test with the server context
closing immediately after dispatch and a delayed client read reproduced the
same exception. DisconnectNamedPipe discarded the unread response. The final
transport waits for a receipt after the complete client read, with a two-second
bound on request/receipt input. This avoids both lost responses and an unbounded
FlushFileBuffers wait when a live client stops reading. Silent clients,
malformed receipts, disconnected clients and simultaneous clients are covered
by native tests. Connection setup retries never replay a transmitted operation.
ACL checks, caller SID validation and exclusive pipe ownership remain intact.

Native transport failures become ControlPipeError instead of leaking pywin32
exceptions through WEB. Status and operation routes report service unavailable;
the module tab offers a retry. Installed module layouts now bypass portable
build diagnostics, including misleading missing-build messages. Portable still
uses its existing comparison. Static resource versions invalidate old caches.

Module downloads report unique missing byte counts while streaming verified
ranges. Small atomic progress snapshots live separately from the transaction
journal. Both launcher and WEB show translated phases, download percentage and
bytes, lock mutation controls throughout the operation and discover ongoing
accepted work on reopening. A controller restart before deferred work begins
reports that accepted operation as failed, requiring a freshly confirmed plan;
it does not automatically execute an old approval or mutate another host's
queued-operation metadata.

Review found the stalled-reader case, orphaned accepted work and missing retry.
Their regression tests failed before the respective corrections and passed
afterward. Isolated native Tk acceptance covers preparation, streamed OCR
bytes/percent, installing/completed phases, locked controls and a second launcher
joining the same operation. No HKLM registration or scheduled task changes are
made by the acceptance harness. OCR payloads are test fixtures; this checks the
download/install flow without claiming to exercise Paddle inference.

Final verification: **2006 Python tests passed**, 3 skipped, 66 subtests passed;
**45 JavaScript tests passed**. Compileall, JS syntax checks and git diff checks
passed. A fresh isolated PyInstaller launcher build returned exit code 0, and
the actual EXE passed the authenticated-pipe streamed OCR GUI acceptance with
packaged Tcl/Tk. Test hooks exist only in ignored acceptance build directories,
not in the production builder. The old local full Setup artifact is unchanged;
GitHub Actions must build a new Release tag containing this correction.

## OCR model preparation source correction — 2026-10-12

The supplied portable WEB-OCR Actions log failed before PyInstaller, while
downloading `PP-OCRv5_mobile_det`. Hugging Face's Xet CAS reconstruction failed;
the AIStudio fallback then returned repository-not-found (404). The missing
ccache warning was unrelated to the failure.

All three OCR preparation entrypoints (Actions, the local WEB EXE generator,
and the installed builder) now prefer PaddleX's official BOS model archives.
Root-host availability probes are disabled: a rejected root HEAD must not
exclude a working archive endpoint. Actual downloads and the existing complete
fast/accurate profile checks remain required. Hugging Face fallback disables
Xet and uses regular HTTP downloads. Variables are set before importing Paddle.

The regression harness executes the actual PowerShell preparation blocks with
a substituted model downloader, checks import-time source configuration, and
confirms that a missing accurate recognizer still fails the build. It does not
claim to run Paddle inference or build a complete OCR EXE locally. Read-only
network probes confirmed that all four required official BOS archives answer
with valid tar headers. The complete hosted build must be verified in Actions
from a commit containing this correction; rerunning an old tagged workflow
keeps its old downloader configuration.

Validation: **45 targeted Python tests passed**, including complete and
incomplete preparation for all three entrypoints. Both complete PowerShell
scripts parsed without errors; `git diff --check` passed. No complete OCR EXE
was built or published locally.

The accompanying report of only “Bez zmiany” in an installed dev.1 launcher
was investigated separately. Public API records and all manifest sidecars for
dev.1/dev.2 downloaded with the production fetchers. Read-only range downloads
of the WEB host (about 9 MB each, not the full content packs) verified the host
hashes; inspection of embedded bytecode constants, without executing downloaded
code, confirmed the same public key in both builds. Both manifest signatures,
module identities and source asset sizes passed the real catalog validation.
Reconstructing the initial dev.1 module selection yielded available dev.2
updates and a trusted current version in each rollback dropdown. The user's
`/api/installation/modules` response subsequently confirmed `offline: true`,
no cached catalog, no blocked releases and `latest: null`. A browser on the
same machine successfully fetched the public release API. This establishes a
controller-side catalog fetch failure; the old code discarded the underlying
exception. Newer versions intentionally appear as updates, not rollback choices.

## Controller HTTPS trust and catalog failure diagnostics — 2026-10-12

Installed transports previously used only default system trust. Fresh Windows
Sandbox and SYSTEM profiles may not have public roots populated yet, while the
main application already uses bundled certifi. A real local TLS server with an
empty system store reproduced certificate verification failures in all four
installed transports (release API, signed manifests, module content ranges and
legacy assets). They now share an explicit verified context which retains
system trust and adds bundled certifi roots. Hostname and certificate validation
remain required, as do the existing trusted redirect hosts, signatures, file
hashes and exact range checks.

Catalog fallback now retains a bounded diagnostic code/message for rate limits,
HTTP failures, certificate failures, DNS errors, timeout and connection failure.
Both launcher and WEB display that cause alongside the local-cache explanation.
Successful online refresh clears the prior failure. Refresh shows a loading
message; the launcher also animates its progress indicator. No raw network error
or proxy configuration is sent to WEB. The exact original exception on the
user's old controller is still unavailable, so this is not evidence that every
possible local proxy/firewall problem is resolved.

The five real TLS acceptance cases pass, including rejection of a trusted
certificate for the wrong hostname. An isolated freshly built PyInstaller EXE
with empty simulated system trust downloaded and accepted both live signed
dev.1/dev.2 catalogs with `offline=False`. It used the public key extracted from
the released host; downloaded host bytecode was inspected only, never executed.
Native Tk/authenticated-pipe OCR acceptance also passed after the refresh change.
The stable controller and launcher need replacement by a new Setup containing
this correction; a module-only update cannot replace that stable infrastructure.

Final validation: **2026 Python tests passed**, 3 skipped, 66 subtests passed;
**46 JavaScript tests passed**. Installation Python compileall, module-panel
JavaScript syntax and git diff checks passed. The full OCR EXE build remains
to be run in Actions from the new commit.

## Installed version mismatch and offline OCR preparation — 2026-10-12

Setup infrastructure repair deliberately retains an existing schema-2 active
module set and its pins. Installing dev.2 over dev.1 therefore does not itself
update the selected WEB UI, settings or core module. The reported core version
`1.004321f94424` belongs to dev.1; dev.2's core is `1.a66c7618c667`.
The old WEB still includes portable build comparison diagnostics above the
installed panel. Current installed routing bypasses that comparison, but its
new code must become active through a module update after the stable controller
can retrieve the catalog.

The released dev.2 commit is `2c10ec4`; it does not contain the later HTTPS trust
and downloader-source corrections (`6638bdb` and `1a86104`). A new Setup built
from the current branch is needed for those infrastructure corrections. Repair
must not reset pinned modules or overwrite the user's selected versions.

An unknown online version was also incorrectly labelled "brak podpisanego
wydania" while the controller was offline. Both UIs now say the catalog was
unavailable, or explicitly identify a cached version. Preparing OCR without any
accepted cached catalog now returns the bounded catalog failure cause rather
than asserting the signed releases do not exist. No plan is stored or operation
started in that case. WEB regressions cover the pending preparation indicator,
visible preflight errors and preservation of a terminal download error after
automatic refresh.

Read-only verification of the released signed manifests produced compatible
OCR plans for both dev.1 and dev.2 (schema 17), adding only OCR runtime and models.
Each needs 5138 distinct missing files, about 813.4 MB, when base files are
already present. This verifies catalog and planning, not a full production OCR
download or inference run. The portable WEB-OCR EXE is not required by these
module plans: they reference the signed content pack instead.

Validation: **51 targeted Python tests passed**, **49 JavaScript tests passed**;
both signed release catalogs and OCR plans passed the independent diagnostic.
