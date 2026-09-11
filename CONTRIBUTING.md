# Contributing

Dzięki za chęć pracy nad PicSyncra. Ten projekt jest aplikacją desktopową z dodatkowymi ścieżkami web, FTP, SQL, Pimcore i buildami EXE, więc najlepiej trzymać zmiany możliwie wąsko.

## Przygotowanie środowiska

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Zainstaluj zależności właściwe dla obszaru, nad którym pracujesz:

```powershell
python -m pip install -r requirements-web.txt
python -m pip install -r requirements-qt.txt
python -m pip install -r requirements-build.txt
```

Nie wszystkie zestawy zależności są potrzebne do każdej zmiany.

## Uruchamianie

Aplikacja desktopowa:

```powershell
python PicSyncra.pyw
```

Panel webowy:

```powershell
python -m uvicorn picsyncra.web.app:app --host 0.0.0.0 --port 8000
```

## Testy

Podstawowy zestaw:

```powershell
python -m pytest
```

Przy zmianach w buildach albo workflow sprawdź też odpowiednie testy w `tests/` oraz pliki `.github/workflows/`.

## Zasady zmian

- Nie commituj prawdziwych haseł, tokenów, kluczy API ani prywatnych danych klientów.
- Jeżeli zmieniasz zachowanie aplikacji, dopisz albo zaktualizuj testy.
- Jeżeli zmieniasz obsługę użytkownika, zaktualizuj odpowiedni dokument w `docs/`.
- Trzymaj nowe funkcje w istniejących modułach i wzorcach projektu, dopóki nie ma dobrego powodu na nową strukturę.
- Przy zmianach dotyczących panelu webowego pamiętaj, że jest to panel do zaufanej sieci LAN, a nie publiczna aplikacja internetowa.

## Pull request

W opisie PR podaj:

- co się zmieniło,
- jak to sprawdzić,
- jakie testy zostały uruchomione,
- czy zmiana dotyka konfiguracji, FTP, SQL, Pimcore, panelu webowego albo buildów EXE.
