# PicSyncra

Organizator zdjęć produktowych dla pracy lokalnej, FTP, SQL oraz panelu webowego w zaufanej sieci LAN.

[![Build Windows EXE](https://github.com/NefilimPL/PicSyncra/actions/workflows/build-exe.yml/badge.svg?branch=main)](https://github.com/NefilimPL/PicSyncra/actions/workflows/build-exe.yml)
[![CI](https://github.com/NefilimPL/PicSyncra/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/NefilimPL/PicSyncra/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/NefilimPL/PicSyncra?display_name=tag)](https://github.com/NefilimPL/PicSyncra/releases/latest)
[![Release date](https://img.shields.io/github/release-date/NefilimPL/PicSyncra)](https://github.com/NefilimPL/PicSyncra/releases/latest)
[![License](https://img.shields.io/github/license/NefilimPL/PicSyncra)](LICENSE)
[![Last commit](https://img.shields.io/github/last-commit/NefilimPL/PicSyncra)](https://github.com/NefilimPL/PicSyncra/commits/main)
[![Repository size](https://img.shields.io/github/repo-size/NefilimPL/PicSyncra)](https://github.com/NefilimPL/PicSyncra)
[![Open issues](https://img.shields.io/github/issues/NefilimPL/PicSyncra)](https://github.com/NefilimPL/PicSyncra/issues)
[![Top language](https://img.shields.io/github/languages/top/NefilimPL/PicSyncra)](https://github.com/NefilimPL/PicSyncra)
[![CI Python](https://img.shields.io/badge/CI%20Python-3.11-3776AB?logo=python&logoColor=white)](https://github.com/NefilimPL/PicSyncra/blob/main/.github/workflows/ci.yml)
[![EXE build Python](https://img.shields.io/badge/EXE%20build%20Python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white)](https://github.com/NefilimPL/PicSyncra/blob/main/.github/workflows/build-exe.yml)
[![Build requirements](https://img.shields.io/badge/build%20requirements-requirements--build.txt-3776AB?logo=python&logoColor=white)](requirements-build.txt)
[![PyInstaller](https://img.shields.io/badge/PyInstaller-%3E%3D%206.17-FF6F00?logo=python&logoColor=white)](requirements-build.txt)
[![PySide6](https://img.shields.io/badge/PySide6-desktop%20UI-41CD52?logo=qt&logoColor=white)](requirements-qt.txt)
[![FastAPI](https://img.shields.io/badge/FastAPI-LAN%20web-009688?logo=fastapi&logoColor=white)](requirements-web.txt)
[![pytest](https://img.shields.io/badge/pytest-test%20suite-0A9EDC?logo=pytest&logoColor=white)](https://github.com/NefilimPL/PicSyncra/actions/workflows/ci.yml)

<img width="1920" height="1040" alt="PicSyncra desktop" src="https://github.com/user-attachments/assets/8d2f9c31-1103-4368-bea2-7b6899d92761" />

## Co robi aplikacja

- Układa zdjęcia produktów w strukturze katalogów opartej o nazwę, typ, model, kolory, dodatek i EAN.
- Optymalizuje, skaluje, kompresuje i opcjonalnie konwertuje zdjęcia.
- Obsługuje sloty zdjęć, miniatury, statusy LOCAL/FTP/SQL oraz wczytywanie istniejących zdjęć.
- Może wysyłać pliki na FTP i aktualizować ścieżki zdjęć w MS SQL albo MySQL.
- Ma aplikację desktopową oraz osobny panel webowy do pracy w lokalnej sieci.
- Integruje się z Pimcore 6.6 REST do wyszukiwania i tworzenia obiektów produktów.

## Szybki start

Aplikacja desktopowa:

```powershell
python PicSyncra.pyw
```

Panel webowy w LAN:

```powershell
python -m pip install -r requirements-web.txt
python -m uvicorn picsyncra.web.app:app --host 0.0.0.0 --port 8000
```

Na Windows możesz też użyć `START_WEB.bat` i `STOP_WEB.bat`.

## Dokumentacja

| Temat | Plik |
| --- | --- |
| Praca lokalna i aplikacja desktopowa | [docs/local-desktop.md](docs/local-desktop.md) |
| Panel webowy w LAN | [docs/web-panel.md](docs/web-panel.md) |
| Konfiguracja Pimcore REST | [docs/pimcore.md](docs/pimcore.md) |
| Budowanie EXE i GitHub Actions | [docs/building-exe.md](docs/building-exe.md) |
| Wkład w projekt | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Bezpieczeństwo | [SECURITY.md](SECURITY.md) |
| Zasady zachowania | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |

## English Summary

PicSyncra is a Python product photo organiser with desktop and LAN web workflows. It can process images, organise them into product folders, upload to FTP, update SQL image paths and integrate with Pimcore 6.6 REST.

## Licencja

Projekt jest udostępniany na licencji [Apache License 2.0](LICENSE).
