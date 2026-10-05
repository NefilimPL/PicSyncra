# PicSyncra instalowana na Windows

Wersja instalowana działa jako zwykły program Windows. WEB i Migrator są
instalowane zawsze, a komponent LOCAL jest opcjonalny. OCR nie jest częścią
instalacji bazowej: administrator pobiera go z zakładki **Wersje modułów**.
Przycisk **Pobierz i zainstaluj OCR** pobiera podpisany pakiet silnika i modeli
z Release odpowiadającego aktywnemu wydaniu aplikacji. Wymaga opublikowanego
pakietu OCR oraz publicznego klucza podpisu wbudowanego w instalowaną aplikację.
Samo lokalne wygenerowanie EXE nie zapewnia źródła tego pakietu.

## Dane i konfiguracja

Podczas instalacji można wskazać istniejącą bazę. Import konfiguracji portable
jest osobną, domyślnie niezaznaczoną opcją. Po jej zaznaczeniu instalator prosi
o istniejący katalog konfiguracji. Wybrane pliki są kopiowane do katalogu
zarządzanego przez instalację, więc usunięcie starego folderu portable nie
usuwa sekretów ani ustawień używanych przez zainstalowaną aplikację.
Bez importu aplikacja korzysta z domyślnej konfiguracji w ProgramData.

Lokalizacja zdjęć może nadal wskazywać udział sieciowy. Konto usługi musi mieć
do niego dostęp; WEB instalowany przez kontroler działa jako `SYSTEM`. Użyj
ścieżki UNC (na przykład `\\serwer\\zdjecia`) i nadaj uprawnienie kontu
komputera lub skonfiguruj dostęp do udziału dla `SYSTEM`. Dyski mapowane tylko
w sesji osoby instalującej nie są widoczne dla usługi.

## Aktualizacje

Aktualizacje są dostępne wyłącznie w zainstalowanej aplikacji. Wybierz kanał
**stable** albo **dev**, a następnie użyj **Aktualizuj** lub wybierz konkretne
wydanie z listy. Aplikacja akceptuje tylko pakiety z podpisanym manifestem
GitHub Release. Portable nadal aktualizuje się ręcznie przez pobranie EXE.

Workflow `.github/workflows/build-installer.yml` przygotowuje osobne archiwa
`web.zip`, `migrator.zip`, `local.zip` i `ocr.zip` oraz podpisany manifest.
Obecny aktualizator przełącza cały zestaw modułów wydania: pobiera WEB,
Migrator i LOCAL, a także OCR, jeśli OCR był już zainstalowany. Nie pobiera
instalatora EXE, ale nie pomija jeszcze niezmienionych modułów. Sam OCR można
doinstalować osobno. Aktualizacja wyłącznie WEB lub wyłącznie Migratora nie
jest obecnie osobną operacją.

Tabela **Wersje modułów** porównuje obecnie commity kodu z gałęzią GitHub.
Wpisy takie jak FTP, SQL i Pimcore są częściami aplikacji, a nie osobnymi
paczkami do pobrania. Tabela nie zastępuje katalogu podpisanych wydań.
Pomijanie niezmienionych plików oraz wybór wersji pojedynczego modułu w WEB
i w lokalnym launcherze wymagają rozszerzenia aktualizatora.

Publikowanie tych paczek wymaga aktywnego workflow w repozytorium oraz
konfiguracji środowiska `installed-release-signing`: publicznych kluczy
`PICSYNCRA_RELEASE_PUBLIC_KEYS` i prywatnego sekretu
`PICSYNCRA_RELEASE_SIGNING_KEY`. Lokalny build bez wstrzykniętych publicznych
kluczy nie akceptuje aktualizacji. Same pliki portable EXE w Release nie
wystarczają do aktualizacji instalowanej aplikacji.

Przed zmianą wydania powstaje kopia bazy i konfiguracji. Aplikacja zatrzymuje
przyjmowanie nowych zadań, czeka na zakończenie aktualnych, a pozostałym
użytkownikom wyświetla dwuminutowe ostrzeżenie. Administrator może wymusić
anulowanie znanych zadań, gdy zadanie nie kończy się samodzielnie.

Jeżeli OCR był już doinstalowany, aktualizacja programu pobiera również
podpisany komponent OCR zgodny z nowym wydaniem i przełącza go w tej samej
transakcji. Instalacja bez OCR nie pobiera modeli automatycznie.

Restart backendu i autostart są dostępne z WEB wyłącznie dla administratora.
Instalator rejestruje zadanie `PicSyncra Controller primary-installation`,
które jest właścicielem tylko uruchomionego przez siebie procesu WEB. Kontroler
najpierw potwierdza żądanie administracyjne, a następnie restartuje WEB z
aktywnego wydania; nie używa `taskkill` ani nie zatrzymuje procesu zajmującego
ten sam port.

Lokalne okno zarządzania WEB może zatrzymywać lub uruchamiać backend po
uruchomieniu jako administrator. Zwykły użytkownik nie ma dostępu do pipe’a
kontrolera; zdalny restart pozostaje operacją administratora zalogowanego w
WEB.

Jeżeli menedżer zgłasza błąd kontrolera, uruchom go opcją **Uruchom jako
administrator** i sprawdź zadanie `PicSyncra Controller primary-installation`
w Harmonogramie zadań. Instalator sprawdza teraz wynik utworzenia i uruchomienia
tego zadania; błąd rejestracji przerywa instalację z komunikatem zamiast
pozostawiać instalację bez kontrolera.
