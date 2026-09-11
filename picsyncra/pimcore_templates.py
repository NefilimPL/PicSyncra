from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import csv
import itertools
import io
import re
import secrets
import time
import unicodedata
from typing import Callable, Iterable, Mapping


MAX_TEMPLATE_LENGTH = 4000
MAX_TEMPLATE_DEPTH = 8
MAX_OUTPUT_LENGTH = 16000
_TEST_VALUE_SEQUENCE = itertools.count(1)
TRANSLITERATION = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D"})


@dataclass(frozen=True)
class TemplateError(ValueError):
    code: str
    message: str
    position: int = 0

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class LiteralNode:
    value: str


@dataclass(frozen=True)
class FunctionCall:
    name: str
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class PlaceholderNode:
    source: str
    functions: tuple[FunctionCall, ...]
    position: int


@dataclass(frozen=True)
class GroupNode:
    children: tuple[object, ...]
    position: int


@dataclass(frozen=True)
class CalcNode:
    children: tuple[object, ...]
    position: int


def _split_quoted(value: str, delimiter: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in {'"', "'"}:
            current.append(char)
            quote = char
        elif char == delimiter:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if quote:
        raise TemplateError("invalid_arguments", "Niezamkniety cudzyslow.", 0)
    parts.append("".join(current).strip())
    return parts


def _arguments(value: str, position: int) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        row = next(
            csv.reader(
                io.StringIO(value),
                skipinitialspace=True,
                escapechar="\\",
            )
        )
    except (csv.Error, StopIteration) as exc:
        raise TemplateError(
            "invalid_arguments",
            "Niepoprawne argumenty funkcji.",
            position,
        ) from exc
    return tuple(row)


MATH_LITERAL_CHARS = frozenset("0123456789+-*/()., \t\r\n")
CALC_FUNCTION_NAMES = ("oblicz", "calc")


def _literal_text(nodes: tuple[object, ...]) -> str | None:
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, LiteralNode):
            return None
        parts.append(node.value)
    return "".join(parts)


def _is_math_literal_group(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and any(char.isdigit() for char in stripped) and all(
        char in MATH_LITERAL_CHARS for char in stripped
    )


def _calc_literal_prefix(literal: list[str]) -> str | None:
    text = "".join(literal)
    folded = text.casefold()
    for name in CALC_FUNCTION_NAMES:
        if not folded.endswith(name):
            continue
        prefix = text[: -len(name)]
        if prefix and (prefix[-1].isalnum() or prefix[-1] == "_"):
            continue
        return prefix
    return None


def _placeholder(content: str, position: int) -> PlaceholderNode:
    parts = _split_quoted(content, "|")
    source = parts[0].strip()
    if not source:
        raise TemplateError(
            "empty_placeholder",
            "Placeholder nie ma zrodla.",
            position,
        )
    functions: list[FunctionCall] = []
    for raw in parts[1:]:
        name = _split_quoted(raw, ":")[0].strip().lower()
        argument_text = raw[len(name) + 1 :] if ":" in raw else ""
        functions.append(FunctionCall(name, _arguments(argument_text, position)))
    return PlaceholderNode(source, tuple(functions), position)


class _Parser:
    def __init__(self, template: str):
        if len(template) > MAX_TEMPLATE_LENGTH:
            raise TemplateError(
                "template_too_long",
                "Szablon jest za dlugi.",
                MAX_TEMPLATE_LENGTH,
            )
        self.template = template
        self.index = 0

    def parse(self) -> tuple[object, ...]:
        nodes = self._sequence("", 0)
        if self.index != len(self.template):
            raise TemplateError(
                "unexpected_closing",
                "Nieoczekiwany znak zamykajacy.",
                self.index,
            )
        return nodes

    def _sequence(self, closing: str, depth: int) -> tuple[object, ...]:
        if depth > MAX_TEMPLATE_DEPTH:
            raise TemplateError(
                "nesting_too_deep",
                "Za duzo zagniezdzonych grup.",
                self.index,
            )
        nodes: list[object] = []
        literal: list[str] = []
        while self.index < len(self.template):
            char = self.template[self.index]
            if closing and char == closing:
                break
            if char == "\\":
                self.index += 1
                if self.index >= len(self.template):
                    raise TemplateError(
                        "dangling_escape",
                        "Pusty znak ucieczki.",
                        self.index - 1,
                    )
                literal.append(self.template[self.index])
                self.index += 1
                continue
            if char == "{":
                if literal:
                    nodes.append(LiteralNode("".join(literal)))
                    literal = []
                nodes.append(self._read_placeholder())
                continue
            if char == "(":
                calc_prefix = _calc_literal_prefix(literal)
                if calc_prefix is not None:
                    if calc_prefix:
                        nodes.append(LiteralNode(calc_prefix))
                    literal = []
                    start = self.index
                    self.index += 1
                    children = self._sequence(")", depth + 1)
                    if self.index >= len(self.template):
                        raise TemplateError(
                            "unclosed_calc",
                            "Niezamknieta funkcja oblicz.",
                            start,
                        )
                    self.index += 1
                    nodes.append(CalcNode(children, start))
                    continue
                if literal:
                    nodes.append(LiteralNode("".join(literal)))
                    literal = []
                start = self.index
                self.index += 1
                children = self._sequence(")", depth + 1)
                if self.index >= len(self.template):
                    raise TemplateError(
                        "unclosed_group",
                        "Niezamknieta grupa warunkowa.",
                        start,
                    )
                self.index += 1
                if not any(
                    isinstance(node, (PlaceholderNode, GroupNode))
                    for node in children
                ):
                    literal_text = _literal_text(children)
                    if literal_text is not None and _is_math_literal_group(literal_text):
                        nodes.append(LiteralNode(f"({literal_text})"))
                        continue
                    raise TemplateError(
                        "condition_without_placeholder",
                        "Grupa nie zawiera placeholdera.",
                        start,
                    )
                nodes.append(GroupNode(children, start))
                continue
            if char in ")}":
                raise TemplateError(
                    "unexpected_closing",
                    "Nieoczekiwany znak zamykajacy.",
                    self.index,
                )
            literal.append(char)
            self.index += 1
        if literal:
            nodes.append(LiteralNode("".join(literal)))
        return tuple(nodes)

    def _read_placeholder(self) -> PlaceholderNode:
        start = self.index
        self.index += 1
        content: list[str] = []
        quote = ""
        escaped = False
        while self.index < len(self.template):
            char = self.template[self.index]
            if escaped:
                content.append(char)
                escaped = False
            elif char == "\\":
                content.append(char)
                escaped = True
            elif quote:
                content.append(char)
                if char == quote:
                    quote = ""
            elif char in {'"', "'"}:
                content.append(char)
                quote = char
            elif char == "}":
                self.index += 1
                return _placeholder("".join(content), start)
            else:
                content.append(char)
            self.index += 1
        raise TemplateError(
            "unclosed_placeholder",
            "Niezamkniety placeholder.",
            start,
        )


def parse_template(template: object) -> tuple[object, ...]:
    return _Parser(str(template or "")).parse()


def _case_shortcut(source: str, calls: Iterable[FunctionCall]) -> str:
    if any(
        call.name
        in {
            "keep",
            "upper",
            "lower",
            "title",
            "capitalize",
            "filled",
            "any_filled",
            "count_filled",
            "if_filled",
        }
        for call in calls
    ):
        return "keep"
    tail = source.rsplit(":", 1)[-1]
    letters = "".join(char for char in tail if char.isalpha())
    if letters and letters.isupper():
        return "upper"
    if letters and letters.islower():
        return "lower"
    if tail.istitle():
        return "title"
    return "keep"


def _strip_diacritics(value: str) -> str:
    translated = value.translate(TRANSLITERATION)
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", translated)
        if not unicodedata.combining(char)
    )


def _apply(
    value: str,
    call: FunctionCall,
    position: int,
    resolver: Callable[[str], object],
) -> str:
    name, args = call.name, call.arguments
    known = {
        "keep",
        "trim",
        "normalize_spaces",
        "upper",
        "lower",
        "title",
        "capitalize",
        "replace",
        "default",
        "substring",
        "truncate",
        "strip_diacritics",
        "slug",
        "number",
        "filled",
        "any_filled",
        "count_filled",
        "if_filled",
    }
    if name not in known:
        raise TemplateError(
            "unknown_function",
            f"Nieznana funkcja {name}.",
            position,
        )
    try:
        if name == "keep" and not args:
            return value
        if name == "trim" and not args:
            return value.strip()
        if name == "normalize_spaces" and not args:
            return " ".join(value.split())
        if name == "upper" and not args:
            return value.upper()
        if name == "lower" and not args:
            return value.lower()
        if name == "title" and not args:
            return value.title()
        if name == "capitalize" and not args:
            return value[:1].upper() + value[1:].lower()
        if name == "replace" and len(args) == 2:
            return value.replace(args[0], args[1])
        if name == "default" and len(args) == 1:
            return value if value.strip() else args[0]
        if name == "substring" and len(args) in {1, 2}:
            start = int(args[0])
            if len(args) == 1:
                return value[start:]
            return value[start : start + int(args[1])]
        if name == "truncate" and len(args) in {1, 2}:
            length = max(0, int(args[0]))
            suffix = args[1] if len(args) == 2 else ""
            return value if len(value) <= length else value[:length] + suffix
        if name == "strip_diacritics" and not args:
            return _strip_diacritics(value)
        if name == "slug" and not args:
            plain = _strip_diacritics(value)
            return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
        if name == "number" and 1 <= len(args) <= 3:
            decimals = max(0, min(8, int(args[0])))
            decimal_separator = args[1] if len(args) >= 2 else "."
            group_separator = args[2] if len(args) == 3 else ""
            number = Decimal(value.replace(" ", "").replace(",", "."))
            rendered = f"{number:,.{decimals}f}"
            return (
                rendered.replace(",", "\x00")
                .replace(".", decimal_separator)
                .replace("\x00", group_separator)
            )
        if name == "filled" and not args:
            return "1" if value.strip() else "0"
        if name in {"any_filled", "count_filled"}:
            values = (value, *(str(resolver(source) or "") for source in args))
            count = sum(bool(item.strip()) for item in values)
            return str(int(bool(count))) if name == "any_filled" else str(count)
        if name == "if_filled" and len(args) == 2:
            return args[0] if value.strip() else args[1]
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TemplateError(
            "invalid_arguments",
            f"Niepoprawne argumenty funkcji {name}.",
            position,
        ) from exc
    raise TemplateError(
        "invalid_arguments",
        f"Niepoprawne argumenty funkcji {name}.",
        position,
    )


def _math_error(position: int) -> TemplateError:
    return TemplateError(
        "invalid_math_expression",
        "Niepoprawne wyrazenie matematyczne.",
        position,
    )


class _MathExpressionParser:
    def __init__(self, text: str, *, allow_division_by_zero: bool = False):
        self.text = text
        self.index = 0
        self.operations = 0
        self.allow_division_by_zero = allow_division_by_zero

    def parse(self) -> Decimal:
        value = self._expression()
        self._skip_spaces()
        if self.index != len(self.text):
            raise _math_error(self.index)
        return value

    def _skip_spaces(self) -> None:
        while self.index < len(self.text) and self.text[self.index].isspace():
            self.index += 1

    def _expression(self) -> Decimal:
        value = self._term()
        while True:
            self._skip_spaces()
            if self.index >= len(self.text) or self.text[self.index] not in "+-":
                return value
            operator = self.text[self.index]
            self.index += 1
            right = self._term()
            self.operations += 1
            value = value + right if operator == "+" else value - right

    def _term(self) -> Decimal:
        value = self._factor()
        while True:
            self._skip_spaces()
            if self.index >= len(self.text) or self.text[self.index] not in "*/":
                return value
            operator = self.text[self.index]
            self.index += 1
            right = self._factor()
            self.operations += 1
            if operator == "*":
                value *= right
                continue
            if right == 0:
                if self.allow_division_by_zero:
                    value = Decimal(0)
                    continue
                raise TemplateError(
                    "math_division_by_zero",
                    "Dzielenie przez zero w wyrazeniu matematycznym.",
                    self.index,
                )
            value /= right

    def _factor(self) -> Decimal:
        self._skip_spaces()
        if self.index >= len(self.text):
            raise _math_error(self.index)
        char = self.text[self.index]
        if char in "+-":
            self.index += 1
            value = self._factor()
            return value if char == "+" else -value
        if char == "(":
            start = self.index
            self.index += 1
            value = self._expression()
            self._skip_spaces()
            if self.index >= len(self.text) or self.text[self.index] != ")":
                raise _math_error(start)
            self.index += 1
            return value
        return self._number()

    def _number(self) -> Decimal:
        start = self.index
        separator = ""
        digits = 0
        while self.index < len(self.text):
            char = self.text[self.index]
            if char.isdigit():
                digits += 1
                self.index += 1
                continue
            if char in ".,":
                if separator:
                    raise _math_error(self.index)
                separator = char
                self.index += 1
                continue
            break
        if digits == 0:
            raise _math_error(start)
        token = self.text[start:self.index].replace(",", ".")
        try:
            return Decimal(token)
        except InvalidOperation as exc:
            raise _math_error(start) from exc


def _format_math_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    if value == value.to_integral_value():
        return str(value.quantize(Decimal(1)))
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _evaluate_math_expression(
    text: str,
    *,
    syntax_only: bool = False,
) -> str | None:
    stripped = text.strip()
    if not stripped or not any(char.isdigit() for char in stripped):
        return None
    if any(char not in MATH_LITERAL_CHARS for char in stripped):
        return None
    parser = _MathExpressionParser(
        stripped,
        allow_division_by_zero=syntax_only,
    )
    try:
        value = parser.parse()
    except TemplateError:
        if syntax_only:
            return None
        raise
    if parser.operations == 0:
        return None
    if syntax_only:
        return "0"
    return _format_math_decimal(value)


def _math_skeleton(nodes: tuple[object, ...]) -> str:
    output: list[str] = []
    for node in nodes:
        if isinstance(node, LiteralNode):
            output.append(node.value)
        elif isinstance(node, PlaceholderNode):
            output.append("1")
        elif isinstance(node, GroupNode):
            output.append("(")
            output.append(_math_skeleton(node.children))
            output.append(")")
        elif isinstance(node, CalcNode):
            output.append("1")
    return "".join(output)


def _is_math_template(nodes: tuple[object, ...]) -> bool:
    return _evaluate_math_expression(_math_skeleton(nodes), syntax_only=True) is not None


def render_template(template: object, resolver: Callable[[str], object]) -> str:
    nodes = parse_template(template)
    preserve_math_groups = _is_math_template(nodes)

    def render_nodes(
        nodes: tuple[object, ...],
        *,
        force_math_groups: bool = False,
    ) -> tuple[str, list[str]]:
        output: list[str] = []
        resolved: list[str] = []
        keep_group_parentheses = preserve_math_groups or force_math_groups
        for node in nodes:
            if isinstance(node, LiteralNode):
                output.append(node.value)
            elif isinstance(node, PlaceholderNode):
                value = str(resolver(node.source) or "")
                for call in node.functions:
                    value = _apply(value, call, node.position, resolver)
                shortcut = _case_shortcut(node.source, node.functions)
                value = _apply(
                    value,
                    FunctionCall(shortcut, ()),
                    node.position,
                    resolver,
                )
                output.append(value)
                resolved.append(value)
            elif isinstance(node, GroupNode):
                value, group_values = render_nodes(
                    node.children,
                    force_math_groups=force_math_groups,
                )
                group_has_values = bool(group_values) and all(
                    item.strip() for item in group_values
                )
                if group_has_values:
                    output.append(f"({value})" if keep_group_parentheses else value)
                else:
                    output.append("")
                resolved.extend(group_values)
            elif isinstance(node, CalcNode):
                value, calc_values = render_nodes(
                    node.children,
                    force_math_groups=True,
                )
                calculated = _evaluate_math_expression(value)
                if calculated is None:
                    raise _math_error(node.position)
                output.append(calculated)
                resolved.extend(calc_values)
                resolved.append(calculated)
        text = "".join(output)
        if len(text) > MAX_OUTPUT_LENGTH:
            raise TemplateError(
                "output_too_long",
                "Wynik szablonu jest za dlugi.",
                MAX_OUTPUT_LENGTH,
            )
        return text, resolved

    rendered = render_nodes(nodes)[0]
    if preserve_math_groups:
        calculated = _evaluate_math_expression(rendered)
        if calculated is not None:
            return calculated
    return rendered


def placeholder_sources(template: object) -> tuple[str, ...]:
    sources: list[str] = []

    def visit(nodes: tuple[object, ...]) -> None:
        for node in nodes:
            if isinstance(node, PlaceholderNode) and node.source not in sources:
                sources.append(node.source)
            elif isinstance(node, (GroupNode, CalcNode)):
                visit(node.children)

    visit(parse_template(template))
    return tuple(sources)


PRODUCT_SOURCES = {
    "name": ("Nazwa", "NAZWA", "name"),
    "type": ("Typ", "TYP", "type", "type_name"),
    "model": ("Model", "MODEL", "model"),
    "color1": ("Kolor 1", "KOLOR 1", "color1"),
    "color2": ("Kolor 2", "KOLOR 2", "color2"),
    "color3": ("Kolor 3", "KOLOR 3", "color3"),
    "extra": ("Dodatek", "DODATEK", "extra"),
    "ean": ("EAN", "ean"),
}


@dataclass(frozen=True)
class SourceDefinition:
    key: str
    label: str
    provider: str
    aliases: tuple[str, ...] = ()


class SourceCatalog:
    def __init__(self, definitions: Iterable[SourceDefinition]):
        self.definitions = tuple(definitions)
        aliases: dict[str, set[str]] = {}
        for definition in self.definitions:
            for alias in (definition.key, definition.label, *definition.aliases):
                aliases.setdefault(alias.casefold(), set()).add(definition.key)
        self._aliases = aliases

    def resolve(self, source: str) -> str:
        matches = self._aliases.get(str(source).strip().casefold(), set())
        if not matches:
            raise TemplateError(
                "unknown_source",
                f"Nieznane zrodlo {source}.",
                0,
            )
        if len(matches) > 1:
            raise TemplateError(
                "ambiguous_source",
                f"Niejednoznaczne zrodlo {source}.",
                0,
            )
        return next(iter(matches))

    def public_items(self) -> list[dict[str, object]]:
        return [
            {
                "key": item.key,
                "label": item.label,
                "provider": item.provider,
                "aliases": list(item.aliases),
            }
            for item in self.definitions
        ]


@dataclass(frozen=True)
class RenderedMappings:
    values: dict[str, object]
    order: tuple[str, ...]


def build_source_catalog(
    mappings: Iterable[Mapping[str, object]],
    extra_sources: Iterable[SourceDefinition] = (),
) -> SourceCatalog:
    definitions = [
        SourceDefinition(
            f"PRODUCT:{key}",
            values[0],
            "product",
            tuple(values[1:]),
        )
        for key, values in PRODUCT_SOURCES.items()
    ]
    for mapping in mappings:
        source = str(mapping.get("source") or "").strip()
        if not source:
            continue
        definitions.append(
            SourceDefinition(
                f"PIMCORE:{source}",
                str(mapping.get("label") or source),
                "pimcore",
                (source,),
            )
        )
    definitions.extend(extra_sources)
    return SourceCatalog(definitions)


def render_mapping_templates(
    mappings: Iterable[Mapping[str, object]],
    *,
    product_values: Mapping[str, object],
    pimcore_values: Mapping[str, object],
    targets: Iterable[str] | None = None,
    extra_sources: Iterable[SourceDefinition] = (),
    extra_values: Mapping[str, object] | None = None,
    preserve_submitted_dependencies: bool = False,
) -> RenderedMappings:
    rows = {
        str(item.get("source") or ""): dict(item)
        for item in mappings
        if str(item.get("source") or "")
    }
    catalog = build_source_catalog(rows.values(), extra_sources)
    values = {
        f"PRODUCT:{key}": value
        for key, value in product_values.items()
    }
    values.update(
        {f"PIMCORE:{key}": value for key, value in pimcore_values.items()}
    )
    values.update(dict(extra_values or {}))

    configured_templated = [
        source
        for source, row in rows.items()
        if str(row.get("value_template") or "")
    ]
    selected = list(targets) if targets is not None else list(configured_templated)
    selected_sources = set(selected)
    templated = [
        source
        for source in configured_templated
        if not (
            preserve_submitted_dependencies
            and source not in selected_sources
            and str(pimcore_values.get(source, "")).strip()
        )
    ]
    dependencies: dict[str, list[str]] = {}
    for source in templated:
        dependencies[source] = []
        for name in placeholder_sources(rows[source]["value_template"]):
            resolved = catalog.resolve(name)
            if not resolved.startswith("PIMCORE:"):
                continue
            dependency = resolved.split(":", 1)[1]
            if dependency in templated and dependency not in dependencies[source]:
                dependencies[source].append(dependency)

    order: list[str] = []
    active: list[str] = []
    complete: set[str] = set()

    def visit(source: str) -> None:
        if source in complete:
            return
        if source not in rows:
            raise TemplateError(
                "unknown_target",
                f"Nieznane pole docelowe {source}.",
                0,
            )
        if source not in templated:
            return
        if source in active:
            cycle = active[active.index(source) :] + [source]
            raise TemplateError(
                "dependency_cycle",
                "Cykliczne pola: " + " -> ".join(cycle),
                0,
            )
        active.append(source)
        for dependency in dependencies[source]:
            visit(dependency)
        active.pop()
        complete.add(source)
        order.append(source)

    for source in selected:
        visit(source)

    for source in order:
        values[f"PIMCORE:{source}"] = render_template(
            rows[source]["value_template"],
            lambda name: values.get(catalog.resolve(name), ""),
        )

    return RenderedMappings(
        {
            source: values.get(f"PIMCORE:{source}", "")
            for source in rows
        },
        tuple(order),
    )


def _gtin13(seed: int) -> str:
    body = f"{seed % 10**12:012d}"
    total = sum(
        int(char) * (1 if index % 2 == 0 else 3)
        for index, char in enumerate(body)
    )
    return body + str((-total) % 10)


def generate_test_values(
    mappings: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    sequence = next(_TEST_VALUE_SEQUENCE)
    token = f"{int(time.time() * 1000):x}{sequence:x}{secrets.randbelow(0x10000):04x}"
    result: dict[str, object] = {}
    for index, mapping in enumerate(mappings, start=1):
        source = str(mapping.get("source") or "")
        parser = str(mapping.get("parser") or "text")
        element_type = str(mapping.get("type") or "input")
        if source.casefold() == "ean":
            value = _gtin13(time.time_ns() + sequence * 1000 + index)
        elif parser == "integer":
            value = str(1000 + index)
        elif parser == "decimal_comma":
            value = f"{1000 + index},{index % 10}"
        elif parser == "boolean" or element_type == "checkbox":
            value = "tak" if index % 2 else "nie"
        elif element_type == "select" and str(mapping.get("default") or ""):
            value = str(mapping["default"])
        else:
            safe = re.sub(r"[^0-9A-Za-z]+", "_", source).strip("_")
            value = f"TEST_{safe or f'FIELD_{index}'}_{token}_{index}"
        result[source] = value
    return result
