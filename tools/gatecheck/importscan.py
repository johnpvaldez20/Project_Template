#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Read the imports of one source file.

The project file selects the parser for each file suffix.
The python parser reads the syntax tree. It finds each static import.
The regex parser reads any language with the patterns in the project file.
The rules on those imports are in architecture.py.
"""

from __future__ import annotations

import ast
import posixpath
import re
from typing import NamedTuple


class Import(NamedTuple):
    """One imported name, its line, and the layers that the name is in."""

    line: int
    text: str
    layers: tuple[str, ...]


def layer_of(path: str, layers: dict) -> str | None:
    """Return the layer whose directory holds the path."""
    for name, prefixes in layers.items():
        if any(path.startswith(prefix) for prefix in prefixes):
            return name
    return None


def scan(source: str, path: str, scanner: dict, layers: dict) -> list[Import]:
    """Return the imports of one file. The python parser can raise SyntaxError."""
    if scanner["parser"] == "python":
        return _python_imports(source, path, scanner["roots"], layers)
    return _regex_imports(source, scanner)


def _python_imports(source: str, path: str, roots: list[str], layers: dict) -> list[Import]:
    package = posixpath.dirname(path)
    found: set[Import] = set()
    for node in ast.walk(ast.parse(source)):
        for line, text, candidates in _node_imports(node, package, roots):
            found.add(Import(line, text, _candidate_layers(candidates, layers)))
    return sorted(found)


def _node_imports(node: ast.AST, package: str, roots: list[str]) -> list[tuple[int, str, list[str]]]:
    if isinstance(node, ast.Import):
        return [(node.lineno, alias.name, _from_roots(alias.name, roots)) for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return _from_imports(node, package, roots)
    if isinstance(node, ast.Call):
        name = _literal_import(node)
        if name is not None:
            return [(node.lineno, name, _from_roots(name, roots))]
    return []


def _from_imports(
    node: ast.ImportFrom, package: str, roots: list[str]
) -> list[tuple[int, str, list[str]]]:
    """A name after import can be a module. Check the module and each name."""
    names = [alias.name for alias in node.names if alias.name != "*"]
    module = node.module or ""
    if node.level == 0:
        targets = [module] + [f"{module}.{name}" for name in names]
        return [(node.lineno, target, _from_roots(target, roots)) for target in targets]
    base = _relative_base(package, node.level)
    if base is None:
        return []
    dots = "." * node.level
    prefix = _join(base, module.replace(".", "/"))
    rows = [(node.lineno, dots + module, [prefix])]
    for name in names:
        text = f"{dots}{module}.{name}" if module else f"{dots}{name}"
        rows.append((node.lineno, text, [_join(prefix, name)]))
    return rows


def _relative_base(package: str, level: int) -> str | None:
    """Return the directory that a relative import starts from."""
    parts = package.split("/") if package else []
    up = level - 1
    if up > len(parts):
        return None
    return "/".join(parts[: len(parts) - up])


def _literal_import(node: ast.Call) -> str | None:
    """Return the module name of a dynamic import that has a literal name."""
    function = node.func
    name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", None)
    if name not in ("import_module", "__import__") or not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _from_roots(dotted: str, roots: list[str]) -> list[str]:
    return [root + dotted.replace(".", "/") for root in roots]


def _join(left: str, right: str) -> str:
    return "/".join(part for part in (left, right) if part)


def _candidate_layers(candidates: list[str], layers: dict) -> tuple[str, ...]:
    found = {layer_of(candidate + "/", layers) for candidate in candidates}
    return tuple(sorted(name for name in found if name is not None))


def _regex_imports(source: str, scanner: dict) -> list[Import]:
    found: set[Import] = set()
    for pattern in scanner["import_patterns"]:
        for match in re.finditer(pattern, source, re.MULTILINE):
            target = match.group(1)
            if target is None:
                continue
            line = source.count("\n", 0, match.start(1)) + 1
            found.add(Import(line, target, _pattern_layers(target, scanner["layer_patterns"])))
    return sorted(found)


def _pattern_layers(target: str, layer_patterns: dict) -> tuple[str, ...]:
    return tuple(
        sorted(
            layer
            for layer, patterns in layer_patterns.items()
            if any(re.search(pattern, target) for pattern in patterns)
        )
    )
