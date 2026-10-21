# Instalator i aktualizacje PicSyncra — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Bieżące zlecenie obejmuje przygotowanie planu, nie wykonanie implementacji. Zadania poniżej pozostają niewykonane.

**Goal:** Zbudować instalowaną PicSyncra dla Windows z bezpieczną aktualizacją z GitHub Releases, opcjonalnym OCR/LOCAL, Migratorem, restartem WEB i obsługą cofnięcia wersji.

**Architecture:** Inno Setup instaluje bazowy pakiet onedir, launcher, kontroler i backend jako osobne usługi. Kontroler wykonuje trwałe transakcje wymiany wersji i komponentów z kopią danych, unieważnieniem sesji, konserwacją i możliwością przywrócenia. Portable zachowuje dotychczasowy runtime i proces wydawania.

**Tech Stack:** Python, PyInstaller onedir, Inno Setup, pywin32 dla usług i lokalnego IPC, FastAPI, SQLite Backup API, JavaScript, GitHub Actions/Releases, podpisy Ed25519 w bibliotece cryptography.

**Spec:** [Specyfikacja instalatora i aktualizacji](../specs/2026-09-15-installed-updates-design.md).

## Global Constraints

- Windows x64; instalator wymaga jednorazowej zgody administratora Windows.
- WEB i Migrator są składnikami obowiązkowymi instalatora.
- Instalator pyta o „Wersja lokalna (opcjonalna)”; domyślnie niezaznaczona.
- OCR nie jest pobierany domyślnie. Przycisk „Pobierz i zainstaluj OCR” pobiera runtime i modele zgodne z bieżącym wydaniem.
- GUI zawiera domyślnie wyłączony autostart backendu po uruchomieniu Windows, również bez zalogowanej osoby.
- Po zakończeniu zadań inni obecni użytkownicy otrzymują ostrzeżenie na 120 sekund. Administrator inicjujący operację nie jest liczony. Bez innych użytkowników i zadań operacja rusza natychmiast.
- Przed każdą zmianą wersji zawsze powstaje sprawdzona kopia bazy oraz konfiguracji. Błąd kopii blokuje operację; harmonogram kopii nie może tego wyłączyć.
- Importowane pliki konfiguracji i sekretów są kopiowane do nowych plików zarządzanych przez instalację. Działanie konfiguracji nie może zależeć od pozostawienia katalogu portable.
- Tokeny rozszerzenia przeglądarki zachowują ważność. Gdy jego wersja wymaga wymiany, użytkownik widzi komunikat i możliwość pobrania aktualnego ZIP.
- Dwa kanały: stable i dev; stable jest domyślny. Dostępna jest lista wydań z wybranego kanału, także starszych.
- Pełny zestaw wymagań stanowi specyfikacja, w szczególności granice uprawnień, force, kopie przed przywróceniem i niezmienione portable.

## Sposób realizacji

Zadania 1–4 tworzą instalator i kontrolę uruchamiania, 5–8 mechanizm konserwacji/aktualizacji, 9–10 interfejs i synchronizację klientów, 11–12 publikację oraz odbiór na Windows. Nie publikować instalatora z aktywnym przyciskiem aktualizacji przed ukończeniem całej ścieżki 1–12.

Każdy etap zaczyna się od testu obserwowalnego zachowania, następnie implementacji i wskazanych kontroli. Polecenia zakładają aktywne środowisko developerskie repozytorium; instalacja zależności builda instalowanego jest częścią zadania 3. Testy Windows usług i awarii wykonuje się w izolowanej maszynie wirtualnej, nigdy przez podmianę uruchomionej instalacji dewelopera.

Plan wyznacza odpowiedzialności i kontrakty. Nowe pliki i funkcje wymienione poniżej mają zostać utworzone podczas wykonania; nie są deklaracją ich obecnej dostępności.

## Kontrakty między komponentami

### Typy wspólne — `picsyncra/installation/contracts.py`

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Channel = Literal["stable", "dev"]
Action = Literal["update", "downgrade", "install_ocr", "restart"]
OperationState = Literal[
    "idle", "downloading", "verified", "draining", "countdown",
    "stopping", "backing_up", "installing", "migrating", "validating",
    "committed", "rolling_back", "rolled_back", "recovery_required", "failed",
]

@dataclass(frozen=True)
class InstallContext:
    installation_id: str
    program_root: Path
    state_root: Path
    config_root: Path
    database_path: Path

@dataclass(frozen=True)
class ComponentRef:
    name: str
    component_id: str
    asset_name: str
    sha256: str
    size: int

@dataclass(frozen=True)
class ReleaseChoice:
    release_id: int
    tag: str
    commit: str
    channel: Channel
    source_branch: str
    manifest_sha256: str
    components: tuple[ComponentRef, ...]
    can_install: bool
    blocked_reason: str | None

@dataclass(frozen=True)
class OperationRequest:
    request_id: str
    action: Action
    release_id: int | None
    restore_backup_id: str | None
    acknowledge_data_loss: bool

@dataclass(frozen=True)
class OperationSnapshot:
    operation_id: str
    state: OperationState
    action: Action
    target_release_id: int | None
    active_tasks: int
    queued_tasks: int
    other_users: int
    deadline_utc: str | None
    force_allowed: bool
    error_code: str | None

@dataclass(frozen=True)
class BackupReceipt:
    backup_id: str
    operation_id: str
    database_sha256: str
    config_sha256: str
    schema_version: int
    release_id: int
    verified: bool
```

`InstallContext` jest wewnętrzny: API nie serializuje ścieżek. `request_id` jest kluczem idempotencji; to samo żądanie oddaje ten sam identyfikator operacji. Dla restartu `release_id` jest puste. Dla instalacji OCR oznacza bieżące wydanie. Tożsamość inicjatora jest ustalana przez serwer, nie przyjmowana z JSON przeglądarki. Dla kopii bazy sprzed pierwszego zarządzanego wydania `release_id=0` oznacza import, a zgodność ustala się według schematu.

### Protokół API — `picsyncra/web/installation_api.py`

| Metoda i ścieżka | Wejście | Wynik |
|---|---|---|
| GET `/api/installation` | administrator | kanał, build, komponenty, autostart, możliwości |
| GET `/api/installation/releases?channel=stable` | administrator | lista `ReleaseChoice`, bez prywatnych ścieżek |
| POST `/api/installation/operations` | `OperationRequest` | 202 i identyfikator operacji |
| GET `/api/installation/operations/{id}` | administrator | `OperationSnapshot` |
| POST `/api/installation/operations/{id}/force` | CSRF, administrator | 202 lub 409, anulowanie w ramach tej samej operacji |
| POST `/api/installation/channel` | `channel` | zapisany kanał; nie rozpoczyna aktualizacji |
| POST `/api/installation/autostart` | `enabled: bool` | faktyczny stan po potwierdzeniu z SCM |
| GET `/api/installation/presence` | zalogowana sesja, heartbeat | stan konserwacji i build, bez listy kont |
| GET `/api/installation/public-status` | bez sesji | stan, build/epoka, termin; bez diagnostyki prywatnej |

Mutacje wymagają rzeczywistego logowania admina i CSRF. Backend odrzuca żądania aktualizacji w portable, niezależnie od GUI. Kontrakt statusu jest dostępny tylko dla instalowanego runtime. Gdy backend jest zatrzymany, przeglądarka zachowuje komunikat i ponawia połączenie z ograniczonym opóźnieniem; nie obiecujemy ciągłego HTTP z wyłączonego backendu.

## Zadanie 1: Ścieżki instalacji bez regresji portable

**Utwórz:** `picsyncra/install_paths.py`, `picsyncra/installation/__init__.py`, `picsyncra/installation/contracts.py`, `tests/test_install_paths.py`.

**Zmień:** `picsyncra/common.py`, `picsyncra/settings.py`, `picsyncra/config.py`, `picsyncra/bootstrap.py`, `picsyncra/storage_settings.py`.

**Interfejsy:** `resolve_install_context(executable: Path) -> InstallContext | None`; `resolve_config_root(executable: Path) -> Path | None`. Resolver używa wyłącznie biblioteki standardowej oraz kontraktów, bez importów `common`, `settings` i `config`.

- [ ] Napisz testy ścieżek portable/development i instalowanego EXE przy rejestracji HKLM, nieważnym wpisie i obcym EXE. Testuj także odrzucenie podszycia się samą zmienną środowiskową.
- [ ] Uruchom `python -m pytest -q tests/test_install_paths.py` i potwierdź błąd wynikający z braku implementacji.
- [ ] Zaimplementuj resolver i wspólne użycie przed odczytem `APP_SECRET` w `common.py` oraz w `settings.py`. Zachowaj dotychczasowy fallback portable; oddziel pliki bootstrap od wybranego katalogu zdjęć/bazy.
- [ ] Zaimplementuj typy kontraktów i odczyt `active.json` z walidacją identyfikatorów i ścieżek wewnątrz instalacji.
- [ ] Uruchom `python -m pytest -q tests/test_install_paths.py tests/test_runtime_paths.py tests/test_settings.py tests/test_config.py tests/test_storage_settings.py`.
- [ ] Zapisz etap w osobnym commicie `feat: add installed runtime paths`.

**Odbiór:** oba miejsca odczytu konfiguracji wskazują ten sam nowy katalog; portable czyta swoje obecne pliki i nie otrzymuje możliwości aktualizacji.

## Zadanie 2: Import bazy, konfiguracji i sekretów

**Utwórz:** `picsyncra/installation/config_import.py`, `tests/test_installed_config_import.py`.

**Zmień:** `picsyncra/storage_settings.py`, `picsyncra/sqlite_backup.py`, `picsyncra/common.py` w zakresie ponownego kodowania importowanego sekretu.

**Interfejsy:** `copy_configuration(source_root: Path, destination_root: Path) -> list[Path]`; `validate_import(context: InstallContext) -> dict[str, str]`. Pierwsza funkcja kopiuje rozpoznane pliki, waliduje odwołania i publikuje nowe pliki atomowo; nie usuwa źródła. Druga zwraca bezpieczne stany `ok`/`needs_configuration` dla integracji bez wartości sekretów.

- [ ] Przygotuj fixture przenośnej konfiguracji z testowym sekretem, plikiem certyfikatu i zewnętrzną ścieżką zdjęć oraz fixture SQLite z konfiguracją w bazie.
- [ ] Napisz test: import, usunięcie tylko źródłowego katalogu konfiguracji w `tmp_path`, świeży proces aplikacji, poprawny odczyt testowego sekretu z nowych plików. Test musi obejmować odczyt przy imporcie `common.py`.
- [ ] Napisz przypadki pominięcia konfiguracji, niewłaściwego sekretu, starej konfiguracji w JSON, odwołań względnych, błędu kopiowania i istniejącego docelowego pliku. Kopia źródła ma pozostać niezmieniona po błędzie.
- [ ] Uruchom `python -m pytest -q tests/test_installed_config_import.py`, a następnie zaimplementuj kopiowanie przez staging i przepisanie ścieżek konfiguracji. Zachowaj logiczne wartości kluczy; nie zastępuj niedostępnych sekretów wartościami domyślnymi.
- [ ] Dodaj wykrycie bazy przed jej otwarciem przez backend. Kopię przed pierwszą migracją wykonuj istniejącym mechanizmem SQLite; nie uruchamiaj migracji przy samym wykrywaniu.
- [ ] Uruchom `python -m pytest -q tests/test_installed_config_import.py tests/test_sqlite_backup.py tests/test_storage_settings.py tests/test_config.py`.
- [ ] Zapisz commit `feat: import portable configuration into installed storage`.

**Odbiór:** usunięcie starej konfiguracji nie psuje instalacji; źródła zdjęć i jawnie wskazana baza nie są samowolnie przenoszone.

## Zadanie 3: Kontroler Windows, backend i launcher

**Utwórz:** `requirements-installed.txt`, `picsyncra/installation/windows_service.py`, `picsyncra/installation/control_protocol.py`, `picsyncra/installation/controller.py`, `picsyncra/installation/launcher.py`, `tests/test_installation_controller.py`, `tests/test_installation_control_protocol.py`.

**Zmień:** `picsyncra/web_manager.py`, `PicSyncra-WEB.pyw`, `requirements-build.txt` tylko jeśli wspólny build wymaga wyraźnego rozdzielenia extras.

**Interfejsy:** `InstallationController.start_backend() -> None`, `stop_backend(force: bool) -> bool`, `set_autostart(enabled: bool) -> bool`, `snapshot() -> dict[str, object]`. IPC przyjmuje wyłącznie zamknięty zestaw poleceń i identyfikator własnej instalacji.

- [ ] Dodaj zależności pywin32 i cryptography do osobnego pliku instalowanego; ustal i przypnij wersje po sprawdzeniu zgodności z interpreterem używanym w bieżącym workflow.
- [ ] Napisz testy z adapterem SCM: ręczny/automatyczny start, restart procesu należącego do instalacji, zajęty port przez obcy proces i brak zgody na zabicie tego procesu.
- [ ] Napisz testy protokołu: obca tożsamość, obca instalacja, pole z komendą shell, dowolny URL/ścieżka, za duża wiadomość oraz nieobsługiwana wersja protokołu są odrzucone.
- [ ] Uruchom `python -m pytest -q tests/test_installation_controller.py tests/test_installation_control_protocol.py`.
- [ ] Zaimplementuj kontroler SCM, backend pod ograniczonym kontem i prywatny potok z ACL. Dla instalowanego menedżera zastąp sterowanie `schtasks` wywołaniami kontrolera; portable nadal używa obecnej ścieżki.
- [ ] Uruchamiaj pomocnicze procesy niewidocznie, z jawną listą argumentów. Backendowi przekaż poprawny kontekst PyInstaller bez środowiska odziedziczonego po innej wersji.
- [ ] Sprawdź start po restarcie Windows z opcją wyłączoną/włączoną oraz dostęp UNC i SQL pod wskazanym kontem. Nie udostępniaj poświadczeń w logach ani konfiguracji WEB.
- [ ] Uruchom `python -m pytest -q tests/test_installation_controller.py tests/test_installation_control_protocol.py tests/test_web_manager.py` i zapisz commit `feat: supervise installed backend with Windows services`.

**Odbiór:** kontroler może zatrzymać i odtworzyć backend bez procesu GUI; żaden przycisk WEB nie daje możliwości wykonania dowolnego polecenia systemowego.

## Zadanie 4: Instalator bazowy i deinstalacja

**Utwórz:** `installer/PicSyncra.iss`, `installer/installed.spec`, `installer/build_installer.ps1`, `picsyncra/installation/setup_cli.py`, `tests/test_installer_layout.py`.

**Zmień:** `docs/building-exe.md`, `docs/local-desktop.md` w zakresie opisu przyszłej dystrybucji po wdrożeniu.

**Interfejsy:** CLI `PicSyncra-SetupHelper.exe inspect`, `import-config`, `register`, `verify-access`, `unregister`; wejście strukturalne przez chroniony plik konfiguracji instalatora, nie hasła w argumentach. Zależność od resolvera, importera i kontrolera z zadań 1–3.

- [ ] Napisz test zawartości instalatora: WEB/Migrator obowiązkowe, LOCAL opcjonalny, OCR nieobecny w bazowej paczce, autostart domyślnie wyłączony, stały identyfikator produktu.
- [ ] Uruchom `python -m pytest -q tests/test_installer_layout.py`.
- [ ] Zbuduj oddzielny pakiet onedir i skrypt Inno z katalogami Program Files/ProgramData, wpisem HKLM, ACL, skrótami i deinstalatorem. Włącz ekrany wyboru danych, istniejącej bazy i importu konfiguracji z przyciskiem pominięcia.
- [ ] Zintegruj sprawdzanie i proponowanie UNC oraz test pod kontem backendu. Pokaż oddzielnie lokalizację konfiguracji i bazy, szczególnie jeżeli baza pozostaje w portable.
- [ ] Dodaj blokadę równoległego uruchomienia instalatora i kontrolera aktualizacji. Naprawa/reinstalacja nie nadpisuje danych domyślnymi plikami.
- [ ] Zbuduj przez `powershell -NoProfile -File installer/build_installer.ps1` i wykonaj instalację, naprawę i deinstalację w VM bez Pythona.
- [ ] Potwierdź pozostawienie danych i kopii po deinstalacji oraz usunięcie wyłącznie usług/reguł własnej instalacji. Zapisz commit `feat: package installed PicSyncra with optional local app`.

## Zadanie 5: OCR jako pobierany komponent

**Utwórz:** `picsyncra/installation/ocr_component.py`, `picsyncra/installation/ocr_runtime.py`, `installer/ocr.spec`, `tests/test_installed_ocr.py`, `tests/test_ocr_runtime_protocol.py`.

**Zmień:** `picsyncra/services/ocr_worker_process.py`, `picsyncra/services/image_dimensions.py`, `picsyncra/services/ocr_worker.py`, miejsca wywołań OCR w `picsyncra/web/app.py`.

**Interfejsy:** `resolve_ocr_component(context: InstallContext) -> Path | None`; `InstalledOcrWorker.start()`, `submit(payload: dict[str, object])`, `poll() -> list[dict[str, object]]`, `stop(force: bool)`. Adapter zachowuje obecne wyniki diagnostyki, postępu i anulowania.

- [ ] Napisz testy bazowego WEB bez PaddleOCR, handshake poprawnej/niezgodnej wersji, przerwanego procesu, limitów i anulowania.
- [ ] Zapisz protokół JSON: `hello` zawiera protocol/build/component ID; komendy `job`, `update_limits`, `stop`; odpowiedzi `ready`, `stage_started`, wynik lub błąd. Ogranicz wielkość komunikatów i dozwolone pliki robocze do zasobów zadania.
- [ ] Uruchom `python -m pytest -q tests/test_installed_ocr.py tests/test_ocr_runtime_protocol.py`.
- [ ] Wydziel punkt wejścia OCR z bibliotekami/modelami w samowystarczalnym onedir i zaimplementuj adapter instalowanego runtime. Kieruj przez niego wszystkie ścieżki OCR, nie tylko kolejkę dopracowywania.
- [ ] Zbuduj OCR EXE i sprawdź offline na maszynie bez Python/Paddle, włącznie z testerem oraz odczytem wymiarów. Użyj małego obrazu testowego z rozpoznawalnym tekstem i sprawdź rzeczywisty wynik, nie tylko start procesu.
- [ ] Uruchom `python -m pytest -q tests/test_installed_ocr.py tests/test_ocr_runtime_protocol.py tests/test_ocr_queue.py tests/test_ocr_slot_queue.py tests/test_ocr_settings.py`.
- [ ] Zapisz commit `feat: support separately installed OCR runtime`.

**Odbiór:** doinstalowanie podpisanego zgodnego komponentu umożliwia OCR bez wymiany portable i bez instalowania pakietów Python na komputerze użytkownika. Pobieranie i aktywacja zostaną podłączone w zadaniach 7–9.

## Zadanie 6: Konserwacja, drain i wymuszone zakończenie

**Utwórz:** `picsyncra/installation/maintenance.py`, `picsyncra/installation/presence.py`, `tests/test_installation_maintenance.py`, `tests/test_installation_presence.py`.

**Zmień:** `picsyncra/web/app.py`, `picsyncra/web/process_queue.py`, `picsyncra/services/ocr_queue.py`, `picsyncra/services/ocr_slot_queue.py`, `picsyncra/sqlite_coordination.py`, `picsyncra/app.py`, `picsyncra/offline_migrator_gui.py`.

**Interfejsy:** `MaintenanceGate.begin(operation_id: str, initiator_id: str) -> None`; `try_admit(kind: str) -> bool`; `snapshot() -> dict[str, object]`; `force_cancel() -> None`; `PresenceRegistry.heartbeat(user_id: str, session_id: str) -> None`; `other_user_count(initiator_id: str) -> int`.

- [ ] Napisz deterministyczne testy z podstawianym zegarem: aktywne zadanie, zadanie w kolejce, drugi użytkownik, tylko inicjator, 120 s po drain, TTL obecności 60 s i heartbeat 15 s.
- [ ] Dodaj testy rozpoczęcia uploadu w tym samym momencie co konserwacja: zadanie musi być albo przyjęte i policzone, albo odrzucone, nigdy pominięte.
- [ ] Uruchom `python -m pytest -q tests/test_installation_maintenance.py tests/test_installation_presence.py`.
- [ ] Zaimplementuj wspólną blokadę przyjmowania mutacji i rejestr czynnych operacji dla WEB, OCR, harmonogramów, rozszerzenia, LOCAL i Migratora. Zarejestruj długie wywołania FTP/SQL/importu, nie tylko kolejki obrazów.
- [ ] Dodaj kooperatywne anulowanie, 30 s na zakończenie, a następnie zabicie wyłącznie znanych procesów. Zapisz status przerwania i operacje o niepewnym wyniku; nie ponawiaj zewnętrznej wysyłki automatycznie.
- [ ] Zaimplementuj licznik innych użytkowników i trwały termin konserwacji. Nie skracaj rozpoczętego odliczania i nie przyjmuj nowych zapisów z karty wracającej z uśpienia.
- [ ] Testuj obcy proces korzystający z bazy: operacja blokowana, bez zabijania procesu i bez podmiany bazy.
- [ ] Uruchom `python -m pytest -q tests/test_installation_maintenance.py tests/test_installation_presence.py tests/test_process_queue.py tests/test_sqlite_coordination.py tests/test_offline_migrator_processes.py` i zapisz commit `feat: coordinate installed maintenance and task draining`.

## Zadanie 7: Katalog wydań i weryfikacja pobierania

**Utwórz:** `picsyncra/installation/release_catalog.py`, `picsyncra/installation/release_manifest.py`, `picsyncra/installation/downloads.py`, `tests/test_installation_releases.py`, `tests/test_installation_downloads.py`.

**Zmień:** `picsyncra/github_status.py` tylko przez wydzielenie/reużycie transportu HTTP, bez zmiany interpretacji portable.

**Interfejsy:** `list_releases(channel: Channel, context: InstallContext) -> list[ReleaseChoice]`; `verify_manifest(raw: bytes, signature: bytes) -> dict[str, object]`; `download_release(choice: ReleaseChoice, staging: Path) -> Path` zwraca zweryfikowany manifest staging.

- [ ] Napisz testy katalogu dla main/stable, dev/prerelease, innej gałęzi testowej, niekompletnego release, kolejnych stron API, starych wydań bez manifestu i wersji niezgodnej z zestawem OCR/LOCAL.
- [ ] Napisz testy kryptografii na tymczasowych kluczach testowych: zły klucz, podmieniony bajt manifestu, hash/rozmiar pakietu, podmiana release ID, replay obcego komponentu i minimalna wersja kontrolera.
- [ ] Napisz testy pobierania: urwanie strumienia, brak miejsca, limit API, zły host po przekierowaniu, traversal, symlink/reparse point, zbyt duża rozpakowana paczka i podmiana pliku po pierwszej weryfikacji.
- [ ] Uruchom `python -m pytest -q tests/test_installation_releases.py tests/test_installation_downloads.py`.
- [ ] Zaimplementuj podpisany manifest, paginowany katalog, selekcję dwóch kanałów i kompletu komponentów. Jawny wybór starszej wersji jest dozwolony tylko po kontroli zgodności.
- [ ] Zaimplementuj pobieranie do pliku tymczasowego, weryfikację przed publikacją w chronionym staging oraz ponowną kontrolę przez helper; brak dowolnych URL od klienta WEB.
- [ ] Uruchom `python -m pytest -q tests/test_installation_releases.py tests/test_installation_downloads.py tests/test_github_status.py tests/test_module_build_status.py` i zapisz commit `feat: fetch and verify installed release packages`.

## Zadanie 8: Obowiązkowe kopie, transakcja i rollback

**Utwórz:** `picsyncra/installation/backups.py`, `picsyncra/installation/journal.py`, `picsyncra/installation/update_transaction.py`, `picsyncra/installation/update_helper.py`, `tests/test_installation_backups.py`, `tests/test_installation_transaction.py`, `tests/test_installation_recovery.py`.

**Zmień:** `picsyncra/sqlite_backup.py`, `picsyncra/sqlite_maintenance.py`, `picsyncra/installation/controller.py`.

**Interfejsy:** `create_operation_backup(context: InstallContext, operation_id: str) -> BackupReceipt`; `submit_operation(request: OperationRequest, actor_id: str) -> OperationSnapshot`; `recover_pending_operation(context: InstallContext) -> OperationSnapshot | None`; `read_operation(operation_id: str) -> OperationSnapshot`.

- [ ] Napisz testy przejść stanów z podmienianym adapterem systemowym. Dwie operacje dają jedną transakcję albo konflikt; powtórzony `request_id` oddaje ten sam wynik.
- [ ] Napisz testy kopii dla wyłączonego harmonogramu, WAL, restartu, instalacji OCR, upgrade, downgrade, pierwszej migracji istniejącej bazy i przywrócenia kopii. Brak miejsca/uszkodzona kopia muszą uniemożliwić wymianę.
- [ ] Napisz testy awarii po każdym trwałym kroku: kopia, zapis nowego aktywnego kompletu, migracja, start backendu, kontrola zdrowia i zapis commit. Uruchom odzyskiwanie dwukrotnie, sprawdzając idempotencję.
- [ ] Uruchom `python -m pytest -q tests/test_installation_backups.py tests/test_installation_transaction.py tests/test_installation_recovery.py`.
- [ ] Zaimplementuj kopię bazy przez SQLite Backup API z kontrolą integralności, kopię konfiguracji i chroniony rejestr metadanych. Wyłącz kopie transakcyjne ze zwykłej retencji harmonogramu.
- [ ] Zaimplementuj trwały dziennik, wyłączną blokadę, przełączenie `active.json`, migracje przed udostępnieniem zapisów i kontrolę release/commit, schematu, konfiguracji, kolejki oraz OCR.
- [ ] Zaimplementuj cofnięcie: dla zgodnej bazy zachowaj dane; dla niezgodnej wymagaj `restore_backup_id` i `acknowledge_data_loss=true`. Najpierw utwórz kopię stanu zastępowanego.
- [ ] Przed automatycznym rollbackiem zabezpiecz stan po nieudanej migracji; jeśli to niemożliwe, przejdź w `recovery_required`, zachowując wcześniejszą kopię i nie nadpisując bazy.
- [ ] Dodaj helper wymiany kontrolera oraz regułę startu po awarii: najpierw recovery, dopiero później backend. Testuj brak jednoczesnego uruchomienia dwóch wersji.
- [ ] Uruchom `python -m pytest -q tests/test_installation_backups.py tests/test_installation_transaction.py tests/test_installation_recovery.py tests/test_sqlite_backup.py tests/test_sqlite_maintenance.py tests/test_sqlite_lifecycle.py` i zapisz commit `feat: apply installed updates with mandatory backups and recovery`.

**Odbiór:** każda operacja kończy się zatwierdzonym kompletem, poprawnym rollbackiem lub jawnym trybem odzyskiwania. Wymuszenie zadań nie omija kopii ani integralności danych.

## Zadanie 9: API administracyjne i „Wersje modułów”

**Utwórz:** `picsyncra/web/installation_api.py`, `picsyncra/web/static/installation-updates.js`, `tests/test_installation_api.py`, `tests/js/installation-updates.test.js`.

**Zmień:** `picsyncra/web/app.py`, `picsyncra/web/static/app.js`, `picsyncra/web/static/module-build-status.js`, `picsyncra/web_manager.py`, odpowiednie pliki lokalizacji `picsyncra/Localization/pl.json`, `eng.json`, `ua.json`.

**Interfejsy:** API z tabeli powyżej; `InstallationUpdates.normalizeSnapshot(payload)`, `renderStatus(snapshot)`, `loadReleases(channel)`, `submitOperation(request)` w wydzielonym module JS. Endpointy w osobnym routerze z wstrzykniętymi zależnościami jak obecny `runtime_api.py`.

- [ ] Napisz testy portable/development, admina, zwykłego użytkownika, wyłączonego logowania, brakującego CSRF, nieznanej operacji i ponownego kliknięcia przycisku.
- [ ] Napisz testy JS: kanał nie instaluje automatycznie, OCR dobierany do bieżącego wydania, brak zgodnego OCR blokuje, lista wcześniejszych wydań i wyraźne potwierdzenie przywrócenia starszej bazy.
- [ ] Uruchom `python -m pytest -q tests/test_installation_api.py` i `node --test tests/js/installation-updates.test.js`.
- [ ] Dodaj w „Wersjach modułów”: wersję/kanał, listę wydań, „Aktualizuj”/„Zainstaluj wybraną wersję”, OCR „Pobierz i zainstaluj”, „Uruchom ponownie”, postęp, oczekiwanie, 120 s ostrzeżenia, force i wynik ostatniej operacji.
- [ ] Oddziel informację o nowszych commitach gałęzi od faktycznie dostępnego pakietu instalacyjnego. Zwykły klik sam pobiera i wykonuje aktualizację; potwierdzenie dodatkowe jest tylko dla jawnie niszczącej migracji/odtworzenia danych.
- [ ] Dodaj opcję autostartu w lokalnym GUI i administracyjnym WEB jako ten sam stan SCM. Zapis widoku następuje po potwierdzeniu faktycznej zmiany przez kontroler.
- [ ] Podczas przerwy HTTP zachowaj ekran konserwacji i ponawiaj połączenie; po powrocie pobierz wynik z dziennika. Nie oznaczaj zerwania połączenia automatycznie jako nieudanej instalacji.
- [ ] Uruchom `python -m pytest -q tests/test_installation_api.py tests/test_module_build_status_api.py tests/test_web_runtime_api.py tests/test_web_ui_integrity.py` i `node --test tests/js/installation-updates.test.js tests/js/module-build-status.test.js`.
- [ ] Zapisz commit `feat: manage installed updates and restart from web settings`.

## Zadanie 10: Sesje, nowy build i zgodność rozszerzenia

**Utwórz:** `picsyncra/installation/session_epoch.py`, `tests/test_installed_sessions.py`, `tests/test_installed_browser_cache.py`, `tests/test_extension_compatibility.py`, `tests/js/installed-session.test.js`.

**Zmień:** `picsyncra/web/app.py`, `picsyncra/web_data.py`, `picsyncra/web/static/app.js`, `picsyncra/web/static/runtime-status.js`, `picsyncra/browser_extension/background.js`, `picsyncra/browser_extension/popup.js`, `picsyncra/browser_extension/manifest.json`, `picsyncra/browser_extension/README.txt`.

**Interfejsy:** `read_session_epoch(context: InstallContext) -> int`; `advance_session_epoch(context: InstallContext) -> int` wykonywane przez kontroler. Instalowane sesje zawierają epokę; `session_version` i `extension_token_version` pozostają odrębnymi mechanizmami.

- [ ] Napisz test: sesja administratora i użytkownika przed aktualizacją działa, po zmianie epoki obie są odrzucone, a przywrócenie starej bazy ich nie reaktywuje. `APP_SECRET` i token rozszerzenia nie zmieniają się.
- [ ] Napisz test mutacji ze starym build ID, starego HTML/JS, uśpionej karty, konserwacji przy wyłączonym logowaniu i braku prywatnych danych w publicznym statusie.
- [ ] Napisz test zgodnego starego rozszerzenia oraz niezgodnego klienta: pierwsze działa po powrocie backendu, drugie dostaje komunikat wymagający pobrania aktualizacji; oba mają zablokowane zapisy w konserwacji.
- [ ] Uruchom `python -m pytest -q tests/test_installed_sessions.py tests/test_installed_browser_cache.py tests/test_extension_compatibility.py`.
- [ ] Zaimplementuj epokę poza przywracaną bazą, kontrolę mutacji według build ID, nowe adresy JS/CSS, rewalidację HTML i przeładowanie klienta na zmianę epoki/buildu.
- [ ] Dodaj metadane zgodności do ping rozszerzenia. Przy nowych klientach przesyłaj wersję/protokół; istniejące klienty bez pola obsługuj jako legacy według manifestu. Informację o wymaganej aktualizacji wyświetl w WEB i, jeśli klient to obsługuje, w popupie.
- [ ] Przy kopiowaniu ZIP zachowaj obecny model spersonalizowanych parametrów, bez publikowania tokenów w release. Nie dodawaj obietnicy automatycznej aktualizacji rozpakowanego rozszerzenia.
- [ ] Uruchom `python -m pytest -q tests/test_installed_sessions.py tests/test_installed_browser_cache.py tests/test_extension_compatibility.py tests/test_web_data_users.py tests/test_browser_extension_package.py` i `node --test tests/js/installed-session.test.js tests/js/browser-extension-popup.test.js`.
- [ ] Zapisz commit `feat: refresh installed sessions and browser clients after maintenance`.

## Zadanie 11: GitHub Releases i publikacja kompletnego zestawu

**Utwórz:** `.github/workflows/build-installer.yml`, `tools/generate_installed_release_manifest.py`, `tools/sign_installed_release_manifest.py`, `tests/test_installed_release_workflow.py`, `tests/test_installed_release_manifest.py`.

**Zmień:** `.github/workflows/ci.yml`, `docs/building-exe.md`. Portable `.github/workflows/build-exe.yml` zmieniaj tylko w razie wymaganej integracji wyzwalania; nie zmieniaj dotychczasowych nazw i zawartości jego EXE.

**Interfejsy:** generator tworzy schema 1 zgodną z `release_manifest.py`; podpisujący narzędzie dostaje ścieżkę manifestu i odczytuje klucz z chronionego środowiska CI. Job publikacji działa dopiero po sukcesie wszystkich wymaganych buildów i testów.

- [ ] Napisz testy schematu, podpisu dokładnych bajtów, kanału main/inna gałąź, sprzecznego prerelease, istniejącego taga i nierozstrzygniętej gałęzi wymagającej jawnego wejścia.
- [ ] Napisz test struktury workflow: build wskazanego SHA, brak sekretu podpisującego w niezaufanym buildzie/PR, publikacja manifestu na końcu, porażka dowolnego wymaganego pakietu bez znacznika gotowości.
- [ ] Uruchom `python -m pytest -q tests/test_installed_release_workflow.py tests/test_installed_release_manifest.py`.
- [ ] Zaimplementuj matrix base/LOCAL/OCR, instalator zawierający base i opcjonalny LOCAL, hashe, rozmiary, manifest zgodności i podpis.
- [ ] Przechowuj klucz podpisujący w chronionym środowisku GitHub; job podpisujący korzysta z zaufanych narzędzi, nie wykonuje kodu dowolnej gałęzi dev mając dostęp do klucza. Ustal rotację przez key ID i publikację następnego zaufanego klucza przed jego użyciem.
- [ ] Zaimplementuj przesłanie pakietów, ich kontrolę przez API i publikację manifestu jako ostatni krok. Nie zastępuj zaakceptowanych pakietów innymi bajtami pod tym samym identyfikatorem wydania.
- [ ] Przeprowadź release testowy w repozytorium/środowisku testowym i sprawdź katalog stable/dev oraz pobranie z rzeczywistego przekierowania GitHub.
- [ ] Uruchom `python -m pytest -q tests/test_installed_release_workflow.py tests/test_installed_release_manifest.py tests/test_build_exe_workflow.py tests/test_module_build_status.py` i zapisz commit `ci: publish signed installed release packages`.

## Zadanie 12: Odbiór Windows, dokumentacja i wydanie pilotażowe

**Utwórz:** `docs/installed-windows.md`, `docs/installed-recovery.md`, `tests/windows/installed-acceptance.ps1`.

**Zmień:** `README.md`, `docs/web-panel.md`, `docs/local-desktop.md`, `docs/building-exe.md`, `SECURITY.md` w zakresie kanału podpisanych pakietów i zgłaszania awarii aktualizacji.

- [ ] Przygotuj izolowaną VM Windows x64 bez Pythona, kontrolowane konta administracyjne/zwykłe, dwa klienty przeglądarkowe i udział sieciowy. Skrypt odbioru wymaga jawnego katalogu testowego i nie usuwa danych spoza niego.
- [ ] Sprawdź instalację bez LOCAL/OCR, z LOCAL, import bazy/sekretów, pominięcie sekretów, zewnętrzną bazę i uruchomienie po usunięciu źródłowego katalogu konfiguracji.
- [ ] Sprawdź autostart on/off po restarcie Windows i dostęp sieciowy pod innym kontem niż instalujące; uruchom WEB/Migrator/LOCAL bez uprawnień do zmiany kodu.
- [ ] Przetestuj pełne operacje: dodanie OCR, upgrade, restart, downgrade zgodny, downgrade z odtworzeniem bazy i brak zgodnej kopii. Każda wykonana operacja ma sprawdzoną kopię oraz wpis historii.
- [ ] Podczas uploadu, FTP, OCR i otwartego LOCAL sprawdź drain, force, licznik i 120 s; odłącz klienta, uśpij kartę, zaloguj innego użytkownika w czasie konserwacji.
- [ ] Przerwij zasilanie VM w stanach `backing_up`, `installing`, `migrating`, `validating` i `rolling_back`; potwierdź odzyskanie oraz brak dwóch procesów zapisujących różne schematy.
- [ ] Sprawdź uszkodzony podpis, niepełny release, brak miejsca, blokadę EXE, awarię usługi, zmianę kontrolera i nieudane odtworzenie. Potwierdź zachowanie danych w `recovery_required`.
- [ ] Sprawdź komunikat rozszerzenia, ponowne logowanie wszystkich użytkowników, cache JS/CSS i odrzucenie zapisu ze starej karty. Potwierdź zachowanie tokenu rozszerzenia.
- [ ] Uruchom pełne kontrole repozytorium: `python -m pytest -q` oraz `node --test tests/js/*.test.js` w środowisku wspierającym rozwinięcie wzorca. W PowerShell użyj `node --test (Get-ChildItem -LiteralPath tests/js -Filter *.test.js | ForEach-Object FullName)`.
- [ ] Zbuduj istniejące portable i wykonaj ich smoke test: ręczna aktualizacja, dotychczasowe ścieżki, brak nowego zarządzania instalacją, OCR w dotychczasowym wariancie i brak rejestracji usług instalatora.
- [ ] Uzupełnij instrukcję instalacji, importu, kanałów, OCR, kopii, rollbacku i ręcznego uruchomienia usługi. Opisz brak aktualizacji starych portable-only releases i brak automatycznej aktualizacji ZIP rozszerzenia.
- [ ] Zapisz wyniki odbioru z wersjami Windows/buildów i ograniczeniami, a dokumentację w commicie `docs: describe installed deployment and recovery`.
- [ ] Przygotuj wydanie pilotażowe na kanale dev. Publikacja do stable jest osobnym krokiem wykonawczym po pomyślnym odbiorze i autoryzacji publikacji.

## Macierz pokrycia wymagań

| Wymaganie | Zadania | Dowód odbioru |
|---|---|---|
| WEB + Migrator, opcjonalny LOCAL | 3, 4, 11, 12 | czysta instalacja obu wariantów |
| OCR pobierany na żądanie i zachowany po aktualizacji | 5, 7, 8, 9, 11, 12 | OCR offline i brak niezgodnego kompletu |
| Autostart sterowany GUI i udziały sieciowe | 3, 4, 9, 12 | reboot on/off i dostęp konta usługi |
| Jeden przycisk aktualizacji/restartu | 6, 8, 9 | operacja asynchroniczna po jednym żądaniu |
| Oczekiwanie, force i ostrzeżenie 120 s | 6, 9, 12 | zegar testowy i rzeczywiste długie zadania |
| Kopia zawsze, także przed cofnięciem | 2, 8, 12 | brak możliwości kontynuacji po błędzie kopii |
| Samodzielne kopie konfiguracji i sekretów | 1, 2, 4, 12 | świeży start po usunięciu źródła konfiguracji |
| Stable/dev, lista wcześniejszych wydań | 7, 8, 9, 11 | filtrowanie i zgodny/niezgodny downgrade |
| Wylogowanie, cache i aktualne dane | 8, 10, 12 | stare tokeny/buildy odrzucone po rollbacku |
| Komunikat o aktualizacji rozszerzenia | 9, 10, 12 | zgodny token działa, niezgodny klient widzi pobranie |
| Bezpieczeństwo i odporność na przerwanie | 3, 7, 8, 11, 12 | próby nieautoryzowane i awaria każdego etapu |
| Portable bez zmian | 1, 3, 5, 9, 10, 11, 12 | istniejące testy i smoke test EXE |

## Warunki zakończenia implementacji

Wszystkie kryteria specyfikacji mają potwierdzenie w macierzy. Przycisk aktualizacji nie jest uznany za ukończony bez testu faktycznej wymiany builda, kopii, rollbacku i ponownego logowania na Windows. Wynik testów Python/JS nie zastępuje testu instalatora, kont usługowych i odzyskiwania po przerwaniu zasilania.
