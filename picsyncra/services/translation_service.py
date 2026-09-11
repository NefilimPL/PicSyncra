from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import hmac
import json
import re
from typing import Callable, Mapping
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from ..common import SSL_CONTEXT
from .translation_cache import TranslationCache


@dataclass(frozen=True)
class TranslationResult:
    text: str
    warning: dict[str, str] | None = None


_TRANSLATION_CACHE = TranslationCache()


def clear_translation_cache() -> None:
    _TRANSLATION_CACHE.clear()


def _cache_key(
    source: str,
    target: str,
    provider: str,
    api_key: str,
    api_url: str,
) -> tuple[str, str, str, str]:
    secret_material = "\x1f".join((provider, api_url, api_key)).encode("utf-8")
    settings_fingerprint = hmac.new(
        b"picsyncraftp-translation-cache-v1",
        secret_material,
        hashlib.sha256,
    ).hexdigest()
    return (provider, target, settings_fingerprint, source)


def _language(value: object, *, deepl: bool = False) -> str:
    raw = str(value or "").strip().lower()
    code = {"ua": "uk"}.get(raw, raw)
    return code.upper() if deepl else code


def _source_language(text: str) -> str:
    if re.search(r"[а-яіїєґ]", text.lower()):
        return "uk"
    if re.search(r"[ąćęłńóśźż]", text.lower()):
        return "pl"
    return "en"


def translate_text(
    text: object,
    target_language: object,
    settings: Mapping[str, object],
    *,
    opener: Callable = urlopen,
) -> TranslationResult:
    source = str(text or "")
    target = _language(target_language)
    if not source.strip() or not target:
        return TranslationResult(source)

    provider = str(settings.get("provider") or "google").strip().lower()
    api_key = str(settings.get("api_key") or "").strip()
    api_url = str(settings.get("api_url") or "").strip()
    if provider == "deepl" and not api_key:
        return TranslationResult(
            source,
            {
                "code": "missing_translation_key",
                "message": "Brak klucza API tlumaczen.",
            },
        )

    def load_translation() -> TranslationResult:
        try:
            if provider == "deepl":
                translated = _translate_deepl(
                    source,
                    target,
                    api_key,
                    api_url,
                    opener,
                )
            elif provider == "mymemory":
                translated = _translate_mymemory(source, target, opener)
            else:
                translated = _translate_google(source, target, opener)
            translated = html.unescape(str(translated or "")).strip()
            if not translated:
                raise ValueError("pusta odpowiedz")
            return TranslationResult(translated)
        except Exception as exc:
            return TranslationResult(
                source,
                {
                    "code": "translation_failed",
                    "message": f"Nie udalo sie przetlumaczyc tekstu: {exc}",
                },
            )

    return _TRANSLATION_CACHE.get_or_translate(
        _cache_key(source, target, provider, api_key, api_url),
        load_translation,
    )


def _translate_deepl(
    source: str,
    target: str,
    api_key: str,
    api_url: str,
    opener: Callable,
) -> str:
    endpoint = api_url or (
        "https://api-free.deepl.com/v2/translate"
        if api_key.endswith(":fx")
        else "https://api.deepl.com/v2/translate"
    )
    request = Request(
        endpoint,
        data=urlencode(
            {
                "auth_key": api_key,
                "text": source,
                "target_lang": _language(target, deepl=True),
            }
        ).encode(),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with opener(request, timeout=5, context=SSL_CONTEXT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        return ""
    translations = payload.get("translations")
    if not isinstance(translations, list) or not translations:
        return ""
    first = translations[0]
    return str(first.get("text") or "") if isinstance(first, dict) else ""


def _translate_mymemory(
    source: str,
    target: str,
    opener: Callable,
) -> str:
    endpoint = (
        "https://api.mymemory.translated.net/get"
        f"?q={quote_plus(source)}"
        f"&langpair={_source_language(source)}|{target}"
    )
    request = Request(endpoint, headers={"User-Agent": "Mozilla/5.0"})
    with opener(request, timeout=5, context=SSL_CONTEXT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        return ""
    response_data = payload.get("responseData")
    return (
        str(response_data.get("translatedText") or "")
        if isinstance(response_data, dict)
        else ""
    )


def _translate_google(
    source: str,
    target: str,
    opener: Callable,
) -> str:
    endpoint = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl={target}&dt=t&q={quote_plus(source)}"
    )
    request = Request(endpoint, headers={"User-Agent": "Mozilla/5.0"})
    with opener(request, timeout=5, context=SSL_CONTEXT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list) or not payload:
        return ""
    parts = payload[0] if isinstance(payload[0], list) else []
    return "".join(
        str(item[0])
        for item in parts
        if isinstance(item, list) and item and item[0]
    )
