# Module Updates and Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instalowana PicSyncra aktualizuje tylko potrzebne pliki oraz zbiorczo cofa wybrane moduły z kontrolą zgodności i utrwalonymi wyłączeniami, z WEB i niezależnego launchera.

**Architecture:** Podpisane manifesty opisują rozłączne moduły, zawartość i zależności. Jeden planer i wykonawca należą do kontrolera; WEB i launcher przygotowują wybory oraz zatwierdzają plany. Kod aplikacji jest ładowany z atomowo aktywowanego zestawu, a stabilne narzędzia odzyskiwania znajdują się poza nim.

**Tech Stack:** Python, SQLite, FastAPI, JavaScript, Tkinter, pywin32, PyInstaller onedir, Inno Setup, GitHub Releases, istniejące podpisy Ed25519.

**Spec:** `docs/superpowers/specs/2026-10-05-module-updates-and-rollback-design.md`, zatwierdzona przez użytkownika 2026-10-05.

Status: zatwierdzony; zadania 1–11 wdrożone na dev2, zadanie 12 w odbiorze i przeglądzie.

## Global Constraints

- Portable aktualizuje się przez pobranie nowego EXE.
- Wybór z listy przygotowuje operację. Nie instaluje, nie cofa ani nie przełącza modułu i nie pobiera jego plików.
- Jeden wspólny przycisk **Cofnij wersję modułu** zatwierdza wszystkie przygotowane wybory.
- Konflikt nie upoważnia programu do samodzielnej wymiany dodatkowych modułów.
- Brak deklaracji zgodności blokuje mieszanie wersji zamiast uznawać je za zgodne.
- Launcher umożliwia cofanie także bez działającego backendu WEB.
- Samo kliknięcie „Cofnij wersję modułu” ani „Aktualizuj wszystko” nie udziela zgody na utratę danych.
- Każdy plik ma jednego właściciela; runtime i modele OCR są wersjonowane osobno.
- Wszystkie zmiany aktywnego zestawu oraz utrwalonych wyłączeń należą do jednej transakcji.
- Nie publikować, nie wysyłać do GitHub i nie zmieniać prawdziwych sekretów podpisu bez upoważnienia. Testy używają własnych kluczy.
- W komendach `python` oznacza `.venv/Scripts/python.exe`. Każdy przebieg pytest używa nowego `--basetemp build/pytest-modules-<task>-<uuid>` wewnątrz workspace; nie korzysta z chronionego systemowego katalogu poprzednich testów.

## Review Focus

1. Drugie okno zmienia instalację po przygotowaniu planu: wykonanie starego planu zostaje odrzucone, bez utraty wyborów (zadania 4, 7, 9).
2. Przerwanie zasilania między zmianą kodu a zatwierdzeniem blokad: odzyskiwany jest jeden spójny zestaw i odpowiednia baza (zadania 3, 6, 7).
3. Junction, ścieżka UNC, różnice wielkości liter i blokada pliku przez antywirusa: brak zapisu poza chronionym stagingiem i brak częściowej aktywacji (zadania 2, 5, 6).
4. Kompletna wersja jest lokalnie, lecz źródłowy Release chwilowo niedostępny: launcher pozwala na zweryfikowane cofnięcie offline; brakujące pliki jasno wymagają Internetu (zadania 4, 5, 10).
5. GUI wskazuje wersję istniejącą tylko w niekompletnym lub zmienionym Release: brak możliwości wykonania, widoczny powód, bez osłabiania podpisów (zadania 2, 4, 8, 11).

## Pliki i jednostki wdrożenia

Nowe małe pliki w `picsyncra/installation/`:

| Plik | Odpowiedzialność |
| --- | --- |
| `module_contracts.py` | Niezmienne typy manifestów, aktywnego zestawu, planów i konfliktów |
| `module_definition.py` | Jednoznaczne przypisanie kodu i zasobów do modułów |
| `module_manifest.py` | Walidacja podpisanego formatu modułowego |
| `module_state.py` | Odczyt i atomowa aktywacja zestawu oraz blokad |
| `module_compatibility.py` | Zgodność zestawu, bazy, konfiguracji i runtime |
| `module_planner.py` | Docelowe wersje, konflikty i minimalna lista pobrań |
| `module_content.py` | Pobieranie, chroniony cache i składanie plików |
| `module_migrations.py` | Sprawdzone ścieżki migracji i odtwarzanie danych |
| `module_executor.py` | Dziennikowana transakcja kontrolera |
| `module_service.py` | Wspólna fasada katalogu, planowania i wykonania |
| `module_bootstrap.py` | Wczesne ładowanie wybranych pakietów kodu |
| `module_launcher.py` | Stabilne GUI do aktualizacji i odzyskiwania |

Stałe ID modułów: `core`, `ftp`, `sql`, `pimcore`, `slots`, `settings`,
`web_ui`, `ocr`, `ocr_tester`, `migrator`, `local`, `ocr_runtime`, `ocr_models`.
WEB jest aplikacją złożoną z rdzenia i wybranych funkcji, nie dodatkowym
właścicielem tych samych plików. Generatory EXE pozostają diagnostyką.
`local`, `ocr_runtime` i `ocr_models` są opcjonalne. Obsługa OCR w bazowym
WEB nie oznacza instalacji silnika lub modeli.

Reguły własności kodu:

- `ftp`: `picsyncra/services/ftp_*.py`, `picsyncra/desktop_ftp_preview.py`.
- `sql`: `picsyncra/services/sql_*.py`, `picsyncra/services/photo_sql_batch.py`.
- `pimcore`: `picsyncra/services/pimcore_*.py`, `picsyncra/pimcore_*.py`.
- `ocr`: `picsyncra/services/image_dimensions.py`, `picsyncra/services/ocr_*.py`, `picsyncra/ocr_*.py`.
- `settings`: `picsyncra/settings.py`, `picsyncra/storage_settings.py`, nowe `picsyncra/web/static/settings-ui.js`.
- `slots`: nowe `picsyncra/web/static/slot-ui.js`.
- `ocr_tester`: `picsyncra/web/static/ocr-diagnostics.js`, nowe `picsyncra/web/static/ocr-tester-ui.js`.
- `web_ui`: pozostałe statyczne zasoby WEB, po wydzieleniu powyższych plików.
- `core`: pozostały kod aplikacji, poza stabilnym bootstrapem/instalatorem i kodem należącym do powyższych modułów.
- `migrator`, `local`, `ocr_runtime`: hosty EXE i ich rozłącznie opisane wymagania bibliotek; modele należą wyłącznie do `ocr_models`.

Stabilna infrastruktura instalacji obejmuje pakiet `installation`, resolver
rejestracji i minimalne entrypointy. Nie jest ładowana z wybranego modułu
aplikacji. Biblioteki runtime są zasobami opisanymi hashami i ABI; zmieniona
biblioteka nie może być ukrytą zależnością bez wpisu w manifeście.

## Zadanie 1: Granice rzeczywistych modułów i frontend

**Files:** Create `module_definition.py`, `slot-ui.js`, `settings-ui.js`, `ocr-tester-ui.js`; modify `picsyncra/web/static/app.js`, `index.html`, `picsyncra/services/module_build_status.py`; test `tests/test_module_definition.py`, `tests/test_module_boundaries.py`, `tests/js/module-ui-boundaries.test.js`.

**Interfaces:** `ModuleDefinition(module_id: str, label: str, optional: bool)`; `module_owner(relative_path: str) -> str`; `module_definitions() -> tuple[ModuleDefinition, ...]`.

- [ ] Write failing ownership tests: every installed payload file has exactly one owner; FTP and SQL are distinct; generators and stable installation files are excluded; duplicate/case-colliding paths fail.
- [ ] Write frontend characterization tests for slot assignment/movement, settings rendering and OCR diagnostic rendering before extracting their current implementations. Assert existing actions and outputs, not copied function bodies.
- [ ] Run `python -m pytest tests/test_module_definition.py tests/test_module_boundaries.py -q` and `node --test tests/js/module-ui-boundaries.test.js`; observe new tests fail for missing boundaries.
- [ ] Implement the ownership catalog. Move slot functions (`getSlotAssignment`, `setSlotAssignment`, `moveSlotContent`, `createSlotNode`, `renderSlot`, `renderSlots` and their slot-specific helpers), settings renderers and OCR tester renderers out of `app.js` into classic scripts. Preserve existing globals/API and load definitions before `app.js`; no initializer may execute before shared state exists.
- [ ] Update build diagnostics to reference these real modules while keeping source/generator diagnostics informational. Run characterization tests, all existing browser tests and frontend route-boundary tests.
- [ ] Commit the independently testable extraction and ownership map.

Test odbioru `test_independent_service_ownership`: `assert module_owner('picsyncra/services/ftp_service.py') == 'ftp'`; analogicznie SQL → `sql`; powtórne przypisanie pliku wywołuje błąd zamiast wyboru pierwszego właściciela.

## Zadanie 2: Podpisany manifest modułowy i katalog

**Files:** Create `module_contracts.py`, `module_manifest.py`; modify `release_catalog.py`, `release_source.py`, `release_client.py`; test `tests/test_module_manifest.py`, `tests/test_installation_release_catalog.py`.

**Interfaces:** Frozen types `ModuleFile(path: str, sha256: str, size: int, asset_name: str)`, `ModuleRequirement(module_id: str, minimum_api: int, maximum_api: int)`, `MigrationStep(migration_id: str, from_schema: int, to_schema: int, module_id: str, entrypoint: str)`, `ModuleVersion(module_id: str, version_id: str, display_version: str, api: int, requirements: tuple[ModuleRequirement, ...], conflicts: tuple[ModuleRequirement, ...], database_min: int, database_max: int, config_min: int, config_max: int, runtime_abi: str, files: tuple[ModuleFile, ...], source_release_id: int, source_tag: str)`, `ModuleRelease(release_id: int, tag: str, channel: str, minimum_controller: int, minimum_launcher: int, modules: tuple[ModuleVersion, ...], migrations: tuple[MigrationStep, ...])`. `verify_module_manifest(raw: bytes, signature: bytes, keys: Mapping[str, bytes | str], *, key_id: str) -> ModuleRelease`.

- [ ] Write failing tests for a correctly signed schema-2 fixture; mixed source Release provenance; unchanged version across releases; missing compatibility metadata; unknown/duplicate IDs; boolean integer fields; unsafe/UNC/case-colliding paths; altered manifest and wrong key.
- [ ] Run `python -m pytest tests/test_module_manifest.py -q` and verify expected failures.
- [ ] Implement strict schema 2 with Ed25519 verification before parsing. Module API numbers are declared positive integers with inclusive required ranges; display versions are labels, never ordering authorities. Version identity hashes payload and compatibility declarations; source-publication metadata does not change module identity.
- [ ] Keep schema-1 catalogs readable for existing clients but mark them unavailable for independent module mixing. Verify source Release records and file assets against trusted repository/channel metadata. Preserve blocked entries with explicit reasons.
- [ ] Run new tests and existing signature/catalog tests. Commit.

Test odbioru `test_signed_manifest_retains_module_provenance`: `assert parsed.modules[0].source_release_id == 1` mimo `parsed.release_id == 5`; zmiana choć jednego bajtu manifestu daje `ManifestError`. Kroki migracji i deklarowane konflikty podlegają tej samej ścisłej walidacji/podpisowi.

## Zadanie 3: Aktywny zestaw, trwałe blokady i stare instalacje

**Files:** Create `module_state.py`; modify `install_paths.py`, `update_helper.py`, `backups.py`, `restart_handoff.py`, `recovery.py`, `ocr_component.py`; test `tests/test_module_state.py`, existing paths/backup/recovery tests.

**Interfaces:** `ActiveModuleSet(revision: int, set_id: str, release_id: int, modules: tuple[ModuleVersion, ...], pinned: frozenset[str])`; `read_module_set(context: InstallContext) -> ActiveModuleSet`; `activate_module_set(context: InstallContext, target: ActiveModuleSet, *, expected_revision: int) -> None`.

- [ ] Write failing tests: two modules/pins activate atomically; stale revision rejected; truncated JSON never accepted; old BOM-free schema-1 marker remains readable; registry/executable mismatch remains rejected.
- [ ] Run `python -m pytest tests/test_module_state.py -q`.
- [ ] Store immutable sets under `sets/<set-id>` and one schema-2 active marker referencing the set/revision. Put pinned IDs inside the activated set, not a separately written settings file. Validate IDs, owned paths and provenance. Use durable no-overwrite publication and atomic marker replacement.
- [ ] Extend receipts/handoffs with exact set identity, revision and pins. Existing schema-1 installations migrate only through a verified complete upgrade; do not synthesize compatibility for their embedded functions. Provide a clear whole-installation bootstrap-upgrade path.
- [ ] Test interruption before/after marker replacement and old receipt recovery. Run existing installer paths/backups/OCR/handoff tests; commit.

Test odbioru `test_stale_activation_keeps_previous_set_and_pins`: po zmianie rewizji `activate_module_set(..., expected_revision=old_revision)` daje błąd; `assert read_module_set(context) == previous`.

## Zadanie 4: Spójny planer aktualizacji i cofania

**Files:** Create `module_compatibility.py`, `module_planner.py`; test `tests/test_module_planner.py`, `tests/test_module_compatibility.py`.

**Interfaces:** `ModuleConflict(code: str, module_id: str, selected_version: str, dependency_id: str | None, dependency_version: str | None, requirement: str)`; `ModuleEnvironment(database_schema: int, config_schema: int, runtime_abi: str, controller_api: int, launcher_api: int)`; `ModulePlan(plan_id: str, action: str, expected_revision: int, target: ActiveModuleSet, conflicts: tuple[ModuleConflict, ...], missing_files: tuple[ModuleFile, ...], download_bytes: int, migration_ids: tuple[str, ...])`; `check_module_compatibility(target: ActiveModuleSet, environment: ModuleEnvironment) -> tuple[ModuleConflict, ...]`; `plan_module_operation(active: ActiveModuleSet, releases: tuple[ModuleRelease, ...], environment: ModuleEnvironment, *, action: str, selected: Mapping[str, str], excluded: frozenset[str], available_hashes: frozenset[str]) -> ModulePlan`.

- [ ] Write failing table tests: rollback of two selections; unchanged unselected modules; selected draft excluded from update but not installed; persisted pins; full update replaces pins only in its target; all dependency/schema/config/runtime conflicts reported together.
- [ ] Test a jump 1→5 with unchanged SQL/models and changed FTP; only missing file hashes are in the plan. Test an offline local rollback, and incomplete/newer releases that must not become an automatic target.
- [ ] Run `python -m pytest tests/test_module_planner.py tests/test_module_compatibility.py -q`.
- [ ] Implement actions `update`, `rollback_modules`, `update_all`, `install_ocr`. Select normal-update targets from one newest complete channel release; preserve pinned/excluded current versions and revalidate the resulting mixture. Rollback uses precisely selected version IDs plus existing other versions. An uninstalled optional module is not included unless explicitly requested.
- [ ] Source dates establish release order; do not order module versions by GitHub numeric IDs or user-facing strings. Return structured conflicts and a distinct full-update proposal; never execute it implicitly.
- [ ] Run planner tests including missing module APIs, contradictory cycles, unsupported schema and absent migration paths. Commit.

Test odbioru `test_rollback_batch_preserves_unselected_sql`: wybór FTP/Pimcore z Release 1 daje docelowe wersje tych dwóch modułów; SQL pozostaje z Release 5; `assert plan.target.pinned == frozenset({'ftp', 'pimcore'})`. Fixture używa zgodnego API/schematu, a druga jej odmiana jawnie konfliktującego API SQL.

## Zadanie 5: Pobieranie tylko brakujących plików i składanie zestawu

**Files:** Create `module_content.py`; modify `downloads.py`; test `tests/test_module_content.py`, `tests/test_installation_downloads.py`.

**Interfaces:** `available_module_hashes(context: InstallContext) -> frozenset[str]`; `stage_module_content(context: InstallContext, plan: ModulePlan, *, open_url: OpenUrl) -> Path`; `materialize_module_set(context: InstallContext, plan: ModulePlan, staging: Path) -> Path`.

- [ ] Write failing tests recording network reads: unchanged DLL/model/source file has zero requests; damaged cache is fetched; three consumers of one hash download it once; removed files are absent from the new set; rollback can use validated local files offline.
- [ ] Run `python -m pytest tests/test_module_content.py -q`.
- [ ] Use protected content cache by SHA256. Reverify local content before reuse. Fetch each missing file through signed asset metadata and existing fixed-GitHub redirect checks; publish verified content only. Individual file assets or single-file compressed assets must not force transfer of unrelated files already present.
- [ ] Assemble an inactive complete tree with copies/reflinks only where supported safely; ordinary copy is acceptable. Never modify a hard-linked active file. Reject reparse-point ancestors, case collisions, path escapes, size/hash mismatches and destination overwrite. Ensure space estimates include staging, expanded files and the mandatory backup.
- [ ] Test antivirus/file-lock failures and interrupted downloads: active files/marker remain untouched. Run old download tests; commit.

Test odbioru `test_unchanged_ocr_model_has_zero_transfer`: rejestrator wywołań `open_url` po skoku 1→5 zawiera tylko zmieniony plik FTP; `assert model_asset not in requested_assets`; `assert plan.download_bytes == changed_ftp_size`.

## Zadanie 6: Migracje, kopie i jedna transakcja

**Files:** Create `module_migrations.py`, `module_executor.py`; modify `database.py`, `backups.py`, `journal.py`, `update_transaction.py`, `recovery.py`; test `tests/test_module_migrations.py`, `tests/test_module_executor.py`.

**Interfaces:** Consumes `MigrationStep` from task 2. `migration_path(current_schema: int, target_schema: int, steps: tuple[MigrationStep, ...]) -> tuple[MigrationStep, ...]`; `restore_module_backup(context: InstallContext, backup_id: str) -> None`; `ModuleExecutor(context: InstallContext, *, controller: InstalledController, catalog: Callable[[], tuple[ModuleRelease, ...]], health_check: Callable[[], bool], migration_runner: Callable[[tuple[MigrationStep, ...]], None]).execute(plan_id: str, *, actor_id: str, restore_backup_id: str | None = None, acknowledge_data_loss: bool = False) -> OperationSnapshot`. `InstalledController` is the existing protocol in `operation_service.py`.

- [ ] Write failing tests for a multi-module transaction, second-module failure, migration failure, backup failure, process crash at each durable phase, stale plan and restored previous pins.
- [ ] Test rollback with compatible current DB preserves data. Incompatible DB requires a verified matching backup and explicit acknowledgment; neither rollback nor full-update buttons implicitly acknowledge it.
- [ ] Run `python -m pytest tests/test_module_executor.py tests/test_module_migrations.py -q`.
- [ ] Determine real SQLite schema/migrations from current stores before declaring ranges; add explicit declarative migration registrations rather than importing a store during planning. Bundle cumulative required forward migrations; missing paths fail closed. Do not invent reverse migrations.
- [ ] Implement lock/revalidation, verified backup, controlled migrations, atomic set activation and health validation. On failure restore exact previous set/pins and database/config when mutated, including after a crash. Never commit only part of a multi-module selection.
- [ ] Use current maintenance/presence gates and warnings; block writes and drain known tasks before database access. Test cross-process exclusion as well as thread exclusion. Commit after focused transaction/recovery tests pass.

Test odbioru `test_second_module_failure_restores_entire_set_and_database`: błąd po migracji/pierwszym module daje `assert result.state == 'rolled_back'`, odtwarza oba poprzednie ID, poprzednie blokady oraz rekord SQLite zmieniony w testowej migracji.

## Zadanie 7: Kontroler jako właściciel aktualizacji

**Files:** Create `module_service.py`; modify `control_protocol.py`, `control_pipe.py`, `controller_host.py`, `controller.py`, `launcher.py`, `operation_service.py`; test `tests/test_module_service.py`, `tests/test_installation_control_protocol.py`, `tests/test_installation_controller_host.py`.

**Interfaces:** `ModuleOperationService.catalog() -> dict[str, object]`; `.prepare(payload: Mapping[str, object], *, actor_id: str) -> dict[str, object]`; `.execute(plan_id: str, *, actor_id: str, restore_backup_id: str | None, acknowledge_data_loss: bool) -> dict[str, object]`; `.operation(operation_id: str) -> dict[str, object]`. Pipe commands: `module_catalog`, `module_plan`, `module_execute`, `module_operation`.

- [ ] Write failing protocol tests for strict payloads, unauthenticated peer, foreign installation, arbitrary URL/path/command, stale revision, double-submit idempotence and backend-independent execution.
- [ ] Run `python -m pytest tests/test_module_service.py tests/test_installation_control_protocol.py -q`.
- [ ] Extend the closed protocol for IDs/choices, not general commands. Preserve SYSTEM/Administrators ACL and native token checks. Bound message sizes; page catalogs or use bounded projections rather than exceeding pipe limits with file manifests.
- [ ] Move executor ownership out of WEB into the long-lived controller. WEB becomes a client; its current maintenance/presence/task data is transferred through a bounded readiness handshake. Broken WEB can be recovered locally while still obtaining DB exclusivity and stopping only owned processes.
- [ ] Perform restart/health completion in controller, not in the backend being replaced. Preserve operation journal/idempotent request IDs. Revalidate authoritative state immediately before execution, including when a second client races.
- [ ] Run native pipe/Job Object regressions and transaction tests; commit.

Test odbioru `test_controller_executes_rollback_without_web`: brak procesu WEB nie blokuje kompletnego lokalnego planu; końcowy snapshot operacji pochodzi z kontrolera. Test nie podmienia wykonawcy na działający serwer HTTP.

## Zadanie 8: Rzeczywiste ładowanie niezależnych wersji

**Files:** Create `module_bootstrap.py`, `installer/module-hosts.spec`, `PicSyncra-Installed-WEB.py`, `PicSyncra-Installed-LOCAL.py`, `PicSyncra-Installed-Migrator.py`; modify `install_paths.py`, `controller_host.py`, `picsyncra/web/app.py`, `ocr_component.py`, `ocr_runtime.py`; test `tests/test_module_bootstrap.py`, `tests/test_installed_module_hosts.py`.

**Interfaces:** `initialize_module_runtime(executable: Path) -> InstallContext | None`; `module_static_root(context: InstallContext) -> Path`; `installed_module_entrypoint(context: InstallContext, app_id: str) -> Path`.

- [ ] Write failing fresh-process tests: switch only FTP between two fixtures while SQL/Pimcore versions stay unchanged; import uses selected source before any application import; missing/corrupt selected code must not fall back to embedded newer code.
- [ ] Run `python -m pytest tests/test_module_bootstrap.py tests/test_installed_module_hosts.py -q`.
- [ ] Bootstrap from HKLM registration and verified active set before `common`, settings or store imports. Add a bounded importer for exact catalog-owned Python module names; never override installation/bootstrap/stdlib modules. Verify selected payload and reject already-imported conflicting versions. Immutable files are used for the process lifetime.
- [ ] Build thin installed hosts with explicit third-party dependencies and selected application code outside the embedded PYZ. Assemble selected static files into one verified static root. Resolve OCR using module compatibility/ABI instead of demanding an identical whole-release ID.
- [ ] Keep original portable entrypoints/builds unchanged. Run true frozen-host mixed-version smoke, not only source tests, before continuing to installer publication. Commit.

Test odbioru `test_frozen_host_imports_selected_ftp_only`: dwa podpisane moduły testowe zwracają odróżnialne znaczniki; `assert loaded_ftp_marker == 'ftp-old'` i `assert loaded_sql_marker == 'sql-current'`. Zniknięcie pliku FTP blokuje start, bez wykorzystania kodu wbudowanego w EXE.

## Zadanie 9: WEB — wybory, linki i zbiorcze cofanie

**Files:** Create `picsyncra/web/static/module-updates-panel.js`; modify `installation-updates.js`, `app.js`, `app.css`, `index.html`, `picsyncra/web/installation_api.py`, `picsyncra/web/app.py`; test `tests/js/module-updates-panel.test.js`, `tests/test_installation_api.py`.

**Interfaces:** `window.PicSyncra.ModuleUpdatesPanel.create({requestJson, onChanged}) -> {element, refresh}`; GET `/api/installation/modules`; POST `/api/installation/module-plans`; POST `/api/installation/module-plans/{plan_id}/execute`; existing operation-status endpoint remains supported.

- [ ] Write failing UI tests: changing multiple selects makes no download/execute requests; each row changes its Release link; one rollback button submits the whole selection; normal update excludes draft rows without installing selected old versions; pinned status survives refresh.
- [ ] Test conflict list/buttons, canceled dialog, full-update revalidation, stale-plan error preserving selections, separate DB-restore acknowledgment, CSRF/admin checks and unavailable/offline catalogs.
- [ ] Run `node --test tests/js/module-updates-panel.test.js` and `python -m pytest tests/test_installation_api.py -q`.
- [ ] Implement panel outside the large `app.js`; expose existing installed-mode gating and insert panel in module settings. Use text-safe DOM construction and validated repository Release links. Lists show current/older available versions plus **Bez zmiany**; unavailable versions show reasons.
- [ ] Use one **Cofnij wersję modułu** button and conflict choices **Aktualizuj wszystko** / **Nie aktualizuj**. No selection-triggered execution. Show actual current/target versions and transfer bytes; operation polling survives WEB restart and refreshes version data on completion.
- [ ] Update route snapshot only for the approved new routes; run all existing browser/static/API tests. Commit.

Test odbioru JS `selecting versions does not execute and rollback submits all selections`: po dwóch zdarzeniach `change` liczba żądań wykonania wynosi `0`; po kliknięciu jednego przycisku przesłany wybór ma oba ID. Link każdego wiersza wskazuje Release z jego manifestu.

## Zadanie 10: Stabilny launcher i odzyskiwanie offline

**Files:** Create `module_launcher.py`, `PicSyncra-Launcher.pyw`; modify `picsyncra/web_manager.py`, `launcher.py`, `installer/PicSyncra.iss`; test `tests/test_module_launcher.py`, `tests/test_installation_launcher.py`.

**Interfaces:** `ModuleLauncherModel(client: InstallationControlClient)` with `.select(module_id: str, version_id: str | None) -> None`, `.prepare(action: str) -> dict[str, object]`, `.execute(plan_id: str, *, restore_backup_id: str | None = None, acknowledge_data_loss: bool = False) -> dict[str, object]`; `main(argv: list[str] | None = None) -> int`.

- [ ] Write failing model tests equivalent to WEB semantics: selection causes zero execution calls; all selected versions submitted together; links match Release; conflict cancel preserves choices; full update is explicitly replanned.
- [ ] Run `python -m pytest tests/test_module_launcher.py tests/test_installation_launcher.py -q`.
- [ ] Add Tkinter version rows/comboboxes with current/latest/pin labels, Release links and one shared rollback button. Use worker threads with UI-thread updates for I/O; do not freeze the window. Error/operation states reflect controller state, never inferred success.
- [ ] Install the launcher under stable `launcher/` and point shortcuts there; choose active entrypoints for WEB/LOCAL/Migrator rather than retaining original release paths. It imports only stable infrastructure, not application code from the broken active set.
- [ ] Test stopped/crashed backend, no Internet with complete local catalog, missing local file, unavailable controller and Windows elevation. Smoke actual GUI via an isolated registered test setup without changing normal installation. Commit.

Test odbioru `test_launcher_selection_is_draft_until_shared_button`: `model.select('ftp', 'old-id')` nie wywołuje wykonania klienta; `model.prepare('rollback_modules')` przekazuje kompletny wybór, a dopiero `.execute(plan_id)` wysyła pojedyncze żądanie wykonania.

## Zadanie 11: Budowanie i publikowanie pełnej zawartości

**Files:** Create `tools/build_installed_modules.py`, `tools/generate_module_release_manifest.py`, `installer/module-compatibility.json`; modify `installer/build_installer.ps1`, `.github/workflows/build-installer.yml`, signing tools as needed; test `tests/test_installed_module_builder.py`, `tests/test_installed_release_workflow.py`, `tests/test_installed_build_script.py`.

**Interfaces:** `build_module_payloads(source_root: Path, build_root: Path) -> tuple[ModuleVersion, ...]`; `generate_module_release_manifest(*, release_metadata: Mapping[str, object], modules: tuple[ModuleVersion, ...]) -> bytes`. CLI emits schema-2 manifest and payload assets matching every declared hash.

- [ ] Write failing two-build tests: FTP-only edit changes FTP identity, not SQL/model identities; new source Release preserves unchanged module identity; dependency/API edit changes its identity; every manifest file is recoverable from the published assets.
- [ ] Run `python -m pytest tests/test_installed_module_builder.py tests/test_installed_release_workflow.py tests/test_installed_build_script.py -q`.
- [ ] Declare tested module API/dependency/database/config/runtime ranges explicitly in versioned compatibility input. Do not generate unrestricted compatibility from current commit history. Build disjoint external-code payloads, independent runtime/model content and stable hosts/launcher.
- [ ] Create content assets named by hash with exact uncompressed sizes. Reuse previously published content only through verified signed provenance; future targets remain reconstructible without installing intermediate releases. Publish complete manifest/signature last and base Setup EXE as a Release asset.
- [ ] Preserve `installed-release-signing`, public-key injection and private signing secret separation. Keep portable workflow separate. Verify release tag/channel/commit match and manual dispatch identifies its actual target Release; never publish a manifest for a different checkout.
- [ ] Run a clean and repeated build, validate all HTML asset references and independently reconstruct a target from emitted assets. Commit; actual GitHub publication remains a separate authorized action.

Test odbioru `test_ftp_only_build_preserves_sql_and_models`: porównaj dwa buildy z jedną zmianą źródła FTP; `assert before['sql'].version_id == after['sql'].version_id`; identycznie `ocr_models`, a FTP ma inne ID. Weryfikacja manifestu działa na rzeczywistych wygenerowanych bajtach.

## Zadanie 12: Odbiór całej instalacji i dokumentacja

**Files:** Create `tests/test_module_updates_end_to_end.py`, `tools/smoke_installed_module_updates.py`; modify `docs/installed-windows.md`, `docs/installer-controller-diagnostics.md`.

- [ ] Add signed test fixtures for releases 1–5, a compatible mixed set, contradictory dependencies, changed schema and unchanged OCR models. Observe end-to-end acceptance tests fail before completing any missing integration.
- [ ] Exercise WEB and launcher against the same controller: selection-only, two-module rollback/pins, normal update skipping pins, conflict cancel/full update, offline rollback after broken WEB, crash recovery and stale cross-client plan.
- [ ] Record exact HTTP requests/bytes for the 1→5 update; assert zero transfer of unchanged libraries/models and no downloads of application releases 2–4. Validate actual loaded function versions in frozen hosts after each operation.
- [ ] Run the full Python suite with a unique workspace-owned `--basetemp`, all `tests/js/*.test.js`, `node --check` for edited scripts and `git diff --check`. Run full installer compilation and frozen controller/launcher/WEB smoke. Report actual results and remaining environment limitations.
- [ ] Update user documentation: OCR source, version rows, temporary choices versus persisted pins, conflict decisions, transfer scope, data-loss confirmation, offline recovery and portable EXE policy. Preserve previous controller-startup regressions.
- [ ] Commit verified integration; obtain a fresh whole-change review using the chosen execution workflow, resolve material findings, then finish the development branch without unrequested merge/push/publication.

Test odbioru `test_both_clients_observe_atomic_rollback_and_pins`: po wykonaniu z launchera odczyt WEB ma te same aktywne ID i blokady; po restarcie nadal są identyczne. Ten test używa wspólnego katalogu instalacji i kontrolera, nie dwóch niezależnych stanów w pamięci.

## Zależności i sposób wykonania

Zadania 1–4 tworzą kontrakty i granice; 5–8 zapewniają pobieranie, transakcje
i rzeczywistą zamianę kodu. WEB/launcher (9–10) korzystają z tych samych
kontraktów; publikacja i odbiór (11–12) zamykają cały przepływ.

Zalecane wykonanie: **Native**, w tej sesji. Wspólne interfejsy i istniejący
kontroler wymagają spójnych zmian; jedna implementacja z testami kolejnych
zadań i niezależnym przeglądem całości ogranicza ponowne czytanie repozytorium.
Alternatywa **Subagent-driven** zapewnia osobny przegląd każdego zadania
kosztem dodatkowych kontekstów. Po wyborze nie ma kolejnych pytań
„czy kontynuować” między zadaniami.
