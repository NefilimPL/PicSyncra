"""Discover and download product images from external web pages."""

from __future__ import annotations

import html as html_lib
from html.parser import HTMLParser
import io
import ipaddress
import mimetypes
import os
import re
import shutil
import socket
import subprocess
from typing import Callable, Iterable
from urllib.parse import unquote, urldefrag, urljoin, urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .common import SSL_CONTEXT

try:  # pragma: no cover - optional runtime dependency
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover
    Image = None
    ImageOps = None


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".avif",
}
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_CANDIDATES = 140
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
CURL_META_MARKER = b"\n---PICSYNCRAFTP-CURL-META-0b57754a---\n"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)

IMAGE_ATTRS = {
    "src",
    "href",
    "content",
    "data-src",
    "data-original",
    "data-lazy",
    "data-lazy-src",
    "data-full",
    "data-full-src",
    "data-image",
    "data-image-src",
    "data-image-large-src",
    "data-large",
    "data-large-src",
    "data-zoom-image",
    "data-zoom-src",
    "data-src-large",
    "data-thumb",
    "poster",
}
SRCSET_ATTRS = {"srcset", "data-srcset", "data-lazy-srcset"}
THUMBNAIL_HINTS = (
    "thumb",
    "thumbnail",
    "small",
    "mini",
    "cart_default",
    "home_default",
    "small_default",
)
IMAGE_URL_RE = re.compile(
    r"""(?P<url>(?:https?:)?//[^\s"'<>\\)]+?\.(?:jpe?g|png|webp|gif|bmp|tiff?|avif)(?:\?[^\s"'<>\\)]*)?)""",
    re.IGNORECASE,
)
BACKGROUND_URL_RE = re.compile(
    r"""url\(\s*['"]?(?P<url>[^'")]+)['"]?\s*\)""",
    re.IGNORECASE,
)
QUOTED_IMAGE_URL_RE = re.compile(
    r"""["'](?P<url>(?:https?:)?//[^"'<>\s\\]+?\.(?:jpe?g|png|webp|gif|bmp|tiff?|avif)(?:\?[^"'<>\s\\]*)?|/[^"'<>\s\\]+?\.(?:jpe?g|png|webp|gif|bmp|tiff?|avif)(?:\?[^"'<>\s\\]*)?)["']""",
    re.IGNORECASE,
)
DOCUMENT_URL_RE = re.compile(r"(?:https?:)?//[^\s\"'<>\\]+", re.IGNORECASE)
CLOUDFLARE_CHALLENGE_HOST = "challenges.cloudflare.com"


class ImageImportError(ValueError):
    """Raised when a web image import request cannot be completed safely."""


def _text(value: object) -> str:
    return str(value or "").strip()


def validate_public_http_url(url: object) -> str:
    """Return a cleaned public HTTP(S) URL or raise ImageImportError."""

    text = _text(url)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ImageImportError("Podaj pelny adres strony http:// albo https://.")
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise ImageImportError("Adres lokalny nie jest dozwolony.")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise ImageImportError(f"Nie udalo sie rozwiazac hosta: {host}") from exc
    for item in addresses:
        raw_ip = item[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        ):
            raise ImageImportError("Adres wskazuje na siec lokalna lub prywatna.")
    return text


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _urlopen(request: Request, timeout: int = 12):
    if SSL_CONTEXT is None:
        return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)
    return build_opener(
        _NoRedirectHandler(),
        HTTPSHandler(context=SSL_CONTEXT),
    ).open(request, timeout=timeout)


def _request_headers(request: Request) -> dict[str, str]:
    return {key: value for key, value in request.header_items()}


def _redirect_location(exc: HTTPError) -> str:
    if exc.code not in REDIRECT_STATUS_CODES:
        return ""
    header_getter = getattr(exc.headers, "get", None)
    if not callable(header_getter):
        return ""
    return str(header_getter("Location") or header_getter("location") or "").strip()


def _response_url(response: object) -> str:
    getter = getattr(response, "geturl", None)
    if callable(getter):
        return str(getter() or "").strip()
    return str(getattr(response, "url", "") or "").strip()


def _open_validated_request(
    request: Request,
    timeout: int,
    *,
    opener: Callable[[Request, int], object],
    validator: Callable[[object], str],
) -> object:
    current = request
    for _redirect_count in range(MAX_REDIRECTS + 1):
        try:
            response = opener(current, timeout)
        except HTTPError as exc:
            location = _redirect_location(exc)
            if not location:
                raise
            redirected_url = validator(urljoin(current.full_url, location))
            current = Request(redirected_url, headers=_request_headers(current))
            continue
        final_url = _response_url(response)
        if final_url and final_url != current.full_url:
            try:
                validator(final_url)
            except Exception:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
                raise
        return response
    raise ImageImportError("Za duzo przekierowan podczas pobierania URL.")


def _read_limited(response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(1024 * 256, max_bytes - total + 1))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise ImageImportError("Pobrany plik jest zbyt duzy.")
    return b"".join(chunks)


def _page_referer(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/"


def _page_request_headers(url: str, *, retry: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    if retry:
        headers.update(
            {
                "Referer": _page_referer(url),
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
        )
    return {key: value for key, value in headers.items() if value}


def _challenge_error() -> ImageImportError:
    return ImageImportError(
        "Strona blokuje automatyczne pobieranie (Cloudflare/challenge 403). "
        "Backend nie moze pobrac HTML-a tej strony bez sesji przegladarki."
    )


def _is_cloudflare_challenge(
    status_code: int,
    headers: object = None,
    body: bytes = b"",
) -> bool:
    if status_code != 403:
        return False
    header_getter = getattr(headers, "get", None)
    if callable(header_getter):
        mitigated = str(header_getter("cf-mitigated", "") or "").lower()
        server = str(header_getter("server", "") or "").lower()
        if mitigated == "challenge":
            return True
        if "cloudflare" in server and mitigated:
            return True
    lowered = body[:20_000].lower()
    if b"cf-mitigated" in lowered:
        return True
    document = _decode_html_bytes(body[:20_000], "text/html")
    return any(
        urlparse(candidate).hostname == CLOUDFLARE_CHALLENGE_HOST
        for candidate in DOCUMENT_URL_RE.findall(document)
    )


def _decode_html_bytes(data: bytes, content_type: str = "", charset: str = "") -> str:
    encoding = charset.strip()
    if not encoding and content_type:
        match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
        if match:
            encoding = match.group(1).strip("\"'")
    return data.decode(encoding or "utf-8", errors="replace")


def _validate_image_pixel_limit(width: int, height: int, max_pixels: int | None) -> None:
    if not max_pixels or width <= 0 or height <= 0:
        return
    limit = max(1, int(max_pixels))
    pixels = int(width) * int(height)
    if pixels > limit:
        raise ImageImportError(
            f"Obraz ma {pixels} pikseli ({width}x{height}), limit to {limit} pikseli."
        )


def _curl_executable() -> str:
    return shutil.which("curl.exe") or shutil.which("curl") or ""


def _fetch_page_html_with_curl(url: str) -> str:
    executable = _curl_executable()
    if not executable:
        raise ImageImportError("Nie udalo sie pobrac strony: curl nie jest dostepny.")
    write_out = (
        CURL_META_MARKER.decode("ascii")
        + "%{http_code}\n%{content_type}\n"
    )
    command = [
        executable,
        "--silent",
        "--show-error",
        "--compressed",
        "--connect-timeout",
        "8",
        "--max-time",
        "24",
        "-A",
        USER_AGENT,
        "-H",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "-H",
        "Accept-Language: pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        "-H",
        "Cache-Control: no-cache",
        "-H",
        "Pragma: no-cache",
        "-H",
        f"Referer: {_page_referer(url)}",
        "--write-out",
        write_out,
        url,
    ]
    run_kwargs = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=28,
            **run_kwargs,
        )
    except Exception as exc:
        raise ImageImportError(f"Nie udalo sie pobrac strony: {exc}") from exc
    output = completed.stdout or b""
    body, separator, meta = output.rpartition(CURL_META_MARKER)
    if not separator:
        body = output
        meta = b""
    if len(body) > MAX_PAGE_BYTES:
        raise ImageImportError("Pobrany plik jest zbyt duzy.")
    meta_lines = _decode_html_bytes(meta, "text/plain").splitlines()
    status_code = 0
    if meta_lines:
        try:
            status_code = int(meta_lines[0].strip())
        except ValueError:
            status_code = 0
    content_type = meta_lines[1].strip() if len(meta_lines) > 1 else ""
    if completed.returncode != 0:
        message = _decode_html_bytes(completed.stderr or b"", "text/plain").strip()
        raise ImageImportError(f"Nie udalo sie pobrac strony: {message or completed.returncode}")
    if _is_cloudflare_challenge(status_code, body=body):
        raise _challenge_error()
    if status_code in REDIRECT_STATUS_CODES:
        raise ImageImportError("Strona zwrocila przekierowanie, ktore nie zostalo pobrane przez curl.")
    if status_code >= 400:
        raise ImageImportError(f"Nie udalo sie pobrac strony: HTTP Error {status_code}")
    if "html" not in content_type and "xml" not in content_type and content_type:
        raise ImageImportError("Podany adres nie zwrocil strony HTML.")
    return _decode_html_bytes(body, content_type)


def fetch_page_html(
    url: object,
    *,
    opener: Callable[[Request, int], object] = _urlopen,
    validator: Callable[[object], str] = validate_public_http_url,
) -> str:
    """Download a page as HTML."""

    cleaned_url = validator(url)
    last_error: Exception | None = None
    for retry in (False, True):
        request = Request(cleaned_url, headers=_page_request_headers(cleaned_url, retry=retry))
        try:
            with _open_validated_request(
                request,
                12,
                opener=opener,
                validator=validator,
            ) as response:
                headers = response.headers
                content_type = headers.get("content-type", "")
                if "html" not in content_type and "xml" not in content_type and content_type:
                    raise ImageImportError("Podany adres nie zwrocil strony HTML.")
                data = _read_limited(response, MAX_PAGE_BYTES)
                charset_getter = getattr(headers, "get_content_charset", None)
                charset = charset_getter() if charset_getter else None
                return _decode_html_bytes(data, content_type, charset or "")
        except HTTPError as exc:
            last_error = exc
            if exc.code == 403 and not retry:
                continue
            if _is_cloudflare_challenge(exc.code, exc.headers):
                try:
                    return _fetch_page_html_with_curl(cleaned_url)
                except ImageImportError as curl_exc:
                    if "Cloudflare/challenge" in str(curl_exc):
                        raise curl_exc from exc
            if exc.code == 403:
                try:
                    return _fetch_page_html_with_curl(cleaned_url)
                except ImageImportError as curl_exc:
                    last_error = curl_exc
            raise ImageImportError(f"Nie udalo sie pobrac strony: HTTP Error {exc.code}: {exc.reason}") from exc
        except ImageImportError:
            raise
        except Exception as exc:
            last_error = exc
            raise ImageImportError(f"Nie udalo sie pobrac strony: {exc}") from exc
    raise ImageImportError(f"Nie udalo sie pobrac strony: {last_error}")


def _without_fragment(url: str) -> str:
    return urldefrag(url)[0]


def _normalize_url(base_url: str, url: object) -> str:
    text = _text(url).replace("&amp;", "&").strip(" '\"\n\r\t")
    if not text or text.startswith(("data:", "javascript:", "mailto:", "tel:")):
        return ""
    if text.startswith("//"):
        base_scheme = urlparse(base_url).scheme or "https"
        text = f"{base_scheme}:{text}"
    absolute = urljoin(base_url, text)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return _without_fragment(absolute)


def _image_ext_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    return os.path.splitext(path)[1].lower()


def looks_like_image_url(url: str) -> bool:
    if _image_ext_from_url(url) in IMAGE_EXTENSIONS:
        return True
    lowered = url.lower()
    return any(f".{ext.lstrip('.')}" in lowered for ext in IMAGE_EXTENSIONS)


def filename_from_url(url: str, fallback: str = "web-image") -> str:
    path = unquote(urlparse(url).path)
    name = os.path.basename(path).strip(" .")
    if not name:
        extension = mimetypes.guess_extension(mimetype_from_url(url) or "") or ".jpg"
        return f"{fallback}{extension}"
    if not os.path.splitext(name)[1]:
        name = f"{name}.jpg"
    return name


def mimetype_from_url(url: str) -> str:
    guessed, _encoding = mimetypes.guess_type(urlparse(url).path)
    return guessed or ""


def _parse_dimension(value: object) -> int:
    match = re.search(r"\d+", _text(value))
    return int(match.group(0)) if match else 0


def _parse_srcset(value: object) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for raw_part in _text(value).split(","):
        part = raw_part.strip()
        if not part:
            continue
        parts = part.split()
        candidate = parts[0].strip()
        if candidate:
            width = 0
            for descriptor in parts[1:]:
                descriptor = descriptor.strip().lower()
                if descriptor.endswith("w"):
                    try:
                        width = int(float(descriptor[:-1]))
                    except ValueError:
                        width = 0
                    break
            result.append((candidate, width))
    return result


def _kind_from_source(url: str, source: str, width: int = 0, height: int = 0) -> str:
    lowered = f"{url} {source}".lower()
    if any(hint in lowered for hint in THUMBNAIL_HINTS):
        return "thumbnail"
    if width and height and max(width, height) <= 320:
        return "thumbnail"
    return "image"


def _expanded_url_variants(url: str) -> Iterable[str]:
    replacements = [
        ("-small_default/", "-large_default/"),
        ("-home_default/", "-large_default/"),
        ("-cart_default/", "-large_default/"),
        ("-medium_default/", "-large_default/"),
        ("-small_default/", "-thickbox_default/"),
        ("-home_default/", "-thickbox_default/"),
        ("-cart_default/", "-thickbox_default/"),
        ("-medium_default/", "-thickbox_default/"),
    ]
    for old, new in replacements:
        if old in url:
            yield url.replace(old, new)
    yield re.sub(r"([?&])(width|height|w|h)=\d+&?", r"\1", url)


class _ImageCandidateParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.candidates: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        width = _parse_dimension(attr_map.get("width"))
        height = _parse_dimension(attr_map.get("height"))
        for key in SRCSET_ATTRS:
            for item, item_width in _parse_srcset(attr_map.get(key)):
                self._add(item, f"{tag}.{key}", item_width or width, height)
        for key in IMAGE_ATTRS:
            value = attr_map.get(key)
            if not value:
                continue
            if key == "href" and tag not in {"a", "link"}:
                continue
            if key == "content" and tag != "meta":
                continue
            if tag == "link" and key == "href":
                rel = attr_map.get("rel", "").lower()
                as_value = attr_map.get("as", "").lower()
                if "image" not in rel and as_value != "image":
                    continue
            self._add(value, f"{tag}.{key}", width, height)

    def _add(self, raw_url: object, source: str, width: int = 0, height: int = 0) -> None:
        url = _normalize_url(self.base_url, raw_url)
        if not url or not looks_like_image_url(url):
            return
        self.candidates.append(
            {
                "url": url,
                "source": source,
                "width": width,
                "height": height,
                "kind": _kind_from_source(url, source, width, height),
            }
        )
        for variant in _expanded_url_variants(url):
            normalized = _normalize_url(self.base_url, variant)
            if normalized and normalized != url and looks_like_image_url(normalized):
                self.candidates.append(
                    {
                        "url": normalized,
                        "source": "expanded",
                        "width": 0,
                        "height": 0,
                        "kind": _kind_from_source(normalized, "expanded"),
                    }
                )


def _html_url_candidates(base_url: str, html: str) -> list[dict[str, object]]:
    parser = _ImageCandidateParser(base_url)
    parser.feed(html)
    texts = [html]
    unescaped = html_lib.unescape(html)
    if unescaped != html:
        texts.append(unescaped)
    slash_unescaped = unescaped.replace("\\/", "/")
    if slash_unescaped not in texts:
        texts.append(slash_unescaped)
    for text in texts:
        for match in BACKGROUND_URL_RE.finditer(text):
            parser._add(match.group("url"), "style.background")
        for match in IMAGE_URL_RE.finditer(text):
            parser._add(match.group("url"), "html.url")
        for match in QUOTED_IMAGE_URL_RE.finditer(text):
            parser._add(match.group("url"), "html.quoted-url")
    return parser.candidates


def probe_image_url(
    url: str,
    referer: str = "",
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_pixels: int | None = None,
) -> tuple[int, int, int, str]:
    """Download an image and return width, height, size and MIME type."""

    cleaned_url = validate_public_http_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(cleaned_url, headers=headers)
    try:
        with _open_validated_request(
            request,
            12,
            opener=_urlopen,
            validator=validate_public_http_url,
        ) as response:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            data = _read_limited(response, max_bytes)
    except ImageImportError:
        raise
    except Exception as exc:
        raise ImageImportError(f"Nie udalo sie pobrac obrazu: {exc}") from exc
    width = 0
    height = 0
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as image:
                if ImageOps is not None:
                    try:
                        image = ImageOps.exif_transpose(image)
                    except Exception:
                        pass
                width, height = image.size
                content_type = content_type or Image.MIME.get(image.format, "")
        except Exception as exc:
            raise ImageImportError("Pobrany plik nie jest obslugiwanym obrazem.") from exc
    _validate_image_pixel_limit(width, height, max_pixels)
    if content_type and not content_type.startswith("image/"):
        raise ImageImportError("Pobrany plik nie jest obrazem.")
    return width, height, len(data), content_type or mimetype_from_url(url) or "image/jpeg"


def download_image_bytes(
    url: str,
    referer: str = "",
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_pixels: int | None = None,
) -> tuple[bytes, str, str, int, int]:
    """Download an image and return bytes, filename, MIME type, width and height."""

    cleaned_url = validate_public_http_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(cleaned_url, headers=headers)
    try:
        with _open_validated_request(
            request,
            12,
            opener=_urlopen,
            validator=validate_public_http_url,
        ) as response:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            data = _read_limited(response, max_bytes)
    except ImageImportError:
        raise
    except Exception as exc:
        raise ImageImportError(f"Nie udalo sie pobrac obrazu: {exc}") from exc
    width = 0
    height = 0
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                content_type = content_type or Image.MIME.get(image.format, "")
        except Exception as exc:
            raise ImageImportError("Pobrany plik nie jest obslugiwanym obrazem.") from exc
    _validate_image_pixel_limit(width, height, max_pixels)
    if content_type and not content_type.startswith("image/"):
        raise ImageImportError("Pobrany plik nie jest obrazem.")
    return (
        data,
        filename_from_url(cleaned_url),
        content_type or mimetype_from_url(cleaned_url) or "image/jpeg",
        width,
        height,
    )


def _normalized_scan_filters(filters: object) -> dict[str, object]:
    if not isinstance(filters, dict):
        filters = {}

    def positive_int(key: str) -> int:
        try:
            value = int(float(str(filters.get(key) or 0).strip()))
        except (TypeError, ValueError):
            return 0
        return max(0, value)

    url_filter = _text(filters.get("url_filter") or filters.get("urlFilter"))
    url_include, url_exclude = _parse_url_filter_terms(url_filter)
    return {
        "min_width": positive_int("min_width") or positive_int("minWidth"),
        "min_height": positive_int("min_height") or positive_int("minHeight"),
        "min_kb": positive_int("min_kb") or positive_int("minKb"),
        "url_include": url_include,
        "url_exclude": url_exclude,
        "hide_thumbnails": bool(
            filters.get("hide_thumbnails")
            or filters.get("hideThumbnails")
        ),
    }


def _parse_url_filter_terms(value: object) -> tuple[list[list[str]], list[list[str]]]:
    include: list[list[str]] = []
    exclude: list[list[str]] = []
    for match in re.finditer(r"!?<[^>]+>|[^\s,;]+", _text(value).lower()):
        part = match.group(0).strip()
        if not part:
            continue
        target = include
        if part.startswith("!") and len(part) > 1:
            target = exclude
            part = part[1:]
        if part.startswith("<") and part.endswith(">"):
            terms = [term.strip() for term in part[1:-1].split("|") if term.strip()]
        else:
            terms = [part]
        if terms:
            target.append(terms)
    return include, exclude


def _candidate_matches_url_filter(item: dict[str, object], filters: dict[str, object]) -> bool:
    include = [
        [str(term) for term in group if str(term)]
        for group in filters.get("url_include") or []
    ]
    exclude = [
        [str(term) for term in group if str(term)]
        for group in filters.get("url_exclude") or []
    ]
    if not include and not exclude:
        return True
    url = str(item.get("url") or "")
    haystack = " ".join(
        [
            url,
            filename_from_url(url, ""),
            str(item.get("filename") or ""),
            str(item.get("source") or ""),
        ]
    ).lower()
    if any(any(term in haystack for term in group) for group in exclude):
        return False
    return all(any(term in haystack for term in group) for group in include)


def _candidate_passes_scan_filters(
    item: dict[str, object],
    filters: dict[str, object],
    *,
    unknown_passes: bool,
) -> bool:
    min_width = int(filters.get("min_width") or 0)
    min_height = int(filters.get("min_height") or 0)
    min_kb = int(filters.get("min_kb") or 0)
    width = int(item.get("width") or 0)
    height = int(item.get("height") or 0)
    size_bytes = int(item.get("size_bytes") or 0)
    if not _candidate_matches_url_filter(item, filters):
        return False
    if filters.get("hide_thumbnails") and _kind_from_source(
        str(item.get("url") or ""),
        str(item.get("source") or ""),
        width,
        height,
    ) == "thumbnail":
        return False
    if min_width:
        if width and width < min_width:
            return False
        if not width and not unknown_passes:
            return False
    if min_height:
        if height and height < min_height:
            return False
        if not height and not unknown_passes:
            return False
    if min_kb:
        if size_bytes and size_bytes < min_kb * 1024:
            return False
        if not size_bytes and not unknown_passes:
            return False
    return True


def discover_image_candidates(
    page_url: str,
    html: str,
    *,
    image_probe: Callable[[str, str], tuple[int, int, int, str]] | None = None,
    limit: int = MAX_CANDIDATES,
    probe_images: bool = True,
    filters: object = None,
) -> list[dict[str, object]]:
    """Return de-duplicated image candidates from HTML with optional dimensions."""

    probe = image_probe or probe_image_url
    scan_filters = _normalized_scan_filters(filters)
    seen: set[str] = set()
    result: list[dict[str, object]] = []
    for raw in _html_url_candidates(page_url, html):
        url = str(raw.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        width = int(raw.get("width") or 0)
        height = int(raw.get("height") or 0)
        size_bytes = 0
        mime_type = mimetype_from_url(url)
        raw_item = {
            "url": url,
            "source": raw.get("source") or "",
            "width": width,
            "height": height,
            "size_bytes": 0,
        }
        if not _candidate_passes_scan_filters(raw_item, scan_filters, unknown_passes=True):
            continue
        if probe_images:
            try:
                probed_width, probed_height, probed_size, probed_mime = probe(url, page_url)
                width = probed_width or width
                height = probed_height or height
                size_bytes = probed_size
                mime_type = probed_mime or mime_type
            except Exception:
                pass
        item = {
            "url": url,
            "filename": filename_from_url(url),
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
            "mime_type": mime_type,
            "source": raw.get("source") or "",
            "kind": _kind_from_source(url, str(raw.get("source") or ""), width, height),
        }
        if not _candidate_passes_scan_filters(
            item,
            scan_filters,
            unknown_passes=not probe_images,
        ):
            continue
        result.append(item)
        if len(result) >= limit:
            break
    return result
