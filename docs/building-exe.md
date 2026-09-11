# Budowanie EXE i GitHub Actions

Ten dokument zbiera informacje o lokalnym budowaniu plików EXE oraz workflow GitHub Actions.

## Lokalne budowanie EXE

Aplikację można zamrozić za pomocą PyInstaller. Przy budowaniu trzeba dołączyć katalog `Localization`, aby po konwersji do `.exe` nadal działało przełączanie języka.

Pomocnicze skrypty w `Generator exe/` automatyzują lokalne budowanie i generują plik PyInstaller `--version-file`, dzięki czemu właściwości Windows zawierają opis pliku, wersję, nazwę produktu, firmę, copyright, nazwę wewnętrzną i oryginalną nazwę pliku.

Przykład ręcznego budowania:

```bash
pyinstaller PicSyncra.pyw \
  --name PicSyncra \
  --noconsole \
  --add-data "picsyncra/Localization;picsyncra/Localization"
```

Runtime szuka tłumaczeń obok pliku wykonywalnego, w katalogu tymczasowym PyInstaller oraz w zainstalowanym pakiecie. Można więc dołączyć albo zaktualizować katalog `Localization` obok `PicSyncra.exe` bez ponownego budowania. Plik `local_settings.json` nadal jest tworzony obok programu.

Panel webowy używa biblioteki `msal` do uwierzytelniania aplikacji Microsoft Entra i wysyłania przez Microsoft Graph. Zależność jest zadeklarowana w `requirements-web.txt` oraz `requirements-build.txt`; musi być zainstalowana w środowisku, z którego PyInstaller buduje `PicSyncra-WEB.exe`. Workflow instaluje ją przed analizą statyczną i pakowaniem aplikacji. Jeżeli lokalny build korzysta z własnego pliku `.spec` albo zmienionego polecenia PyInstaller, nie należy wyłączać wykrytego statycznie importu MSAL.

Obecność MSAL w EXE zapewnia tylko obsługę protokołu. Sama wysyłka Graph wymaga skonfigurowanej aplikacji Entra z aplikacyjnym uprawnieniem Microsoft Graph `Mail.Send` i udzieloną przez administratora dzierżawy zgodą administracyjną. Dane logowania i adres nadawcy są ustawiane już w panelu webowym, a nie podczas budowania EXE.

## Workflow CI

Workflow `.github/workflows/ci.yml` działa na `push` i `pull_request` dla gałęzi `main`, `master` i `dev`. Sprawdza składnię Pythona i JavaScriptu, krytyczne testy `pytest`, smoke testy panelu webowego, integralność UI, importy desktopowe i lekkie ścieżki wydajnościowe.

## Workflow Build Windows EXE

Workflow `.github/workflows/build-exe.yml` buduje:

- desktopowe `PicSyncra-<tag>.exe`,
- webowe `PicSyncra-WEB-<tag>.exe`,
- paczkę `PicSyncra-web-<tag>.zip`.

Build uruchamia się ręcznie albo po publikacji GitHub Release. Przy release workflow próbuje podpiąć wygenerowane pliki do wydania przez GitHub API.

Przed buildem workflow sprawdza dostępność self-hosted runnerów z etykietami `self-hosted`, `Windows` i `X64`, statusem `online` oraz `busy: false`. Desktop EXE i web EXE/ZIP są budowane jako równoległe joby matrix. Jeżeli nie ma wolnego runnera albo API GitHuba nie pozwala odczytać listy runnerów, joby przechodzą na `windows-latest`.

## Token do self-hosted runnerów

Aby workflow mógł sprawdzać dostępność runnerów, dodaj sekret `ACTIONS_RUNNER_READ_TOKEN`.

Najlepszy zakres tokenu:

- fine-grained personal access token,
- dostęp tylko do tego repozytorium,
- uprawnienie **Administration: Read-only**.

Dodanie sekretu:

1. Wejdź w repozytorium na GitHubie.
2. Otwórz **Settings -> Secrets and variables -> Actions**.
3. Kliknij **New repository secret**.
4. Ustaw nazwę `ACTIONS_RUNNER_READ_TOKEN`.
5. Wklej token jako wartość.

Token nie jest potrzebny do samego builda EXE. Bez niego wykrywanie self-hosted runnerów może dostać `403`, a workflow przejdzie na `windows-latest`.

## Przygotowanie self-hosted runnera

Na self-hosted runnerach workflow używa lokalnie zainstalowanego Pythona zamiast `actions/setup-python`, ponieważ `setup-python` może wymagać uprawnień do rejestru Windows przy instalacji do tool cache.

Preferowany jest Python 3.14. Akceptowane fallbacki to Python 3.13, 3.12 i 3.11.

Instalacja kontrolna:

```powershell
winget install -e --id Python.Python.3.14 --scope machine
py -3.14 -m pip install --upgrade pip
py -3.14 -m pip install -r requirements-build.txt -r requirements-web.txt
```

Po instalacji zrestartuj usługę runnera. Aplikacja GitHub Actions runnera powinna być aktualna, bo workflow używa wersji akcji kompatybilnych z Node 24.

Workflow tworzy izolowany virtualenv w katalogu tymczasowym runnera dla każdego joba matrix i instaluje zależności Pythona przy każdym uruchomieniu. Powyższe `pip install` służy głównie do sprawdzenia, czy Python i pobieranie pakietów działają.

## Artefakty i release

Workflow wykonuje próbny upload małego artefaktu z retencją jednego dnia dla każdego targetu matrix. Jeżeli GitHub odrzuci upload, zwykle przez limit miejsca albo uprawnienia, build EXE nadal się kończy, a właściwe artefakty są pomijane albo oznaczone jako częściowo nieudane.

Zwykłe artefakty EXE mają retencję siedmiu dni. Release assets są wysyłane przez GitHub API, więc GitHub CLI (`gh`) nie musi być zainstalowany na self-hosted runnerach. Wersja widoczna w GUI i webie jest pobierana z taga release.

## Ręczny build w GitHub Actions

1. Wypchnij workflow do repozytorium.
2. W **Settings -> Actions -> General** upewnij się, że Actions są włączone.
3. Jeżeli używasz self-hosted runnerów, sprawdź etykiety `self-hosted`, `Windows` i `X64`.
4. Dodaj opcjonalny sekret `ACTIONS_RUNNER_READ_TOKEN`.
5. Otwórz **Actions -> Build Windows EXE**.
6. Kliknij **Run workflow**.
7. W podsumowaniu sprawdź sekcję **Runner selection**.
8. Po zakończeniu pobierz artefakty `PicSyncra-windows`, `PicSyncra-web-exe` albo `PicSyncra-web`, jeżeli upload artefaktów był dostępny.
9. Aby opublikować pliki przy wydaniu, utwórz i opublikuj release z tagiem, np. `v1.2.3`.

Zależności builda są w `requirements-build.txt`. Zależności panelu webowego są w `requirements-web.txt`.
