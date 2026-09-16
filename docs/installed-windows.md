# PicSyncra instalowana na Windows

Wersja instalowana działa jako zwykły program Windows. WEB i Migrator są
instalowane zawsze, a komponent LOCAL jest opcjonalny. OCR nie jest częścią
instalacji bazowej: administrator pobiera go z zakładki **Wersje modułów**.

## Dane i konfiguracja

Podczas instalacji można wskazać istniejącą bazę. Gdy instalator znajdzie bazę,
pyta również o katalog konfiguracji. Wybrane pliki są kopiowane do katalogu
zarządzanego przez instalację, więc usunięcie starego folderu portable nie
usuwa sekretów ani ustawień używanych przez zainstalowaną aplikację.

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
