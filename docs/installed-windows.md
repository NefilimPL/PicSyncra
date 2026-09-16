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
do niego dostęp; sprawdzenie odbywa się pod kontem usługi, a nie kontem osoby
instalującej.

## Aktualizacje

Aktualizacje są dostępne wyłącznie w zainstalowanej aplikacji. Wybierz kanał
**stable** albo **dev**, a następnie użyj **Aktualizuj** lub wybierz konkretne
wydanie z listy. Aplikacja akceptuje tylko pakiety z podpisanym manifestem
GitHub Release. Portable nadal aktualizuje się ręcznie przez pobranie EXE.

Przed zmianą wydania powstaje kopia bazy i konfiguracji. Aplikacja zatrzymuje
przyjmowanie nowych zadań, czeka na zakończenie aktualnych, a pozostałym
użytkownikom wyświetla dwuminutowe ostrzeżenie. Administrator może wymusić
anulowanie znanych zadań, gdy zadanie nie kończy się samodzielnie.

Restart backendu i autostart są dostępne z WEB wyłącznie dla administratora.
