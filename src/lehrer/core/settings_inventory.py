"""Read a settings class's declared fields without importing it.

A feature manifest names settings by key, and a typo must fail at compile
time rather than boot into a default. The class that defines which keys exist
cannot be imported here: a generated aqueduct model imports Django and
edx-platform, and an entry module calls ``configure_django_settings`` at import
time. So this walks the classes with :mod:`ast`, following each class's bases
to the files that declare them, and records every field's name and the key
pydantic-settings actually reads for it.

Kept out of :mod:`lehrer.settings.base`, which is copied into the platform
image; that module is one of the files walked here, not a home for tooling.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

TERMINAL_BASES = frozenset({"BaseSettings", "BaseModel"})
"""Bases that end a walk: pydantic's own, which declare no settings."""

_SKIPPED_NAMES = frozenset({"model_config"})


@dataclass(frozen=True)
class SettingField:
    """One declared setting."""

    name: str
    """The attribute name on the class."""
    alias: str | None
    """The ``validation_alias`` (first choice, for ``AliasChoices``), if any.
    When set, pydantic-settings reads this key and ignores ``name``."""
    owner: str
    """The class that declares it, for messages."""
    statement: ast.AnnAssign = field(compare=False, repr=False)
    """The declaration itself, for callers that need its annotation or default."""

    @property
    def key(self) -> str:
        """The key a settings source must use to set this field."""
        return self.alias or self.name


@dataclass(frozen=True)
class _Module:
    path: Path
    tree: ast.Module

    def class_def(self, name: str) -> ast.ClassDef | None:
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        return None

    def imported_from(self, name: str) -> tuple[str, int] | None:
        """Return ``(module, level)`` that ``name`` is imported from, if any."""
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if (alias.asname or alias.name) == name:
                        return node.module or "", node.level
        return None


class InventoryError(ValueError):
    """A base class the walker cannot follow."""


def _is_class_var(annotation: ast.expr) -> bool:
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(target, ast.Attribute):
        return target.attr == "ClassVar"
    return isinstance(target, ast.Name) and target.id == "ClassVar"


def _alias(value: ast.expr | None) -> str | None:
    """The first validation alias of a ``Field(...)`` call, if it sets one."""
    if not isinstance(value, ast.Call):
        return None
    for keyword in value.keywords:
        if keyword.arg not in {"validation_alias", "alias"}:
            continue
        alias = keyword.value
        if isinstance(alias, ast.Constant) and isinstance(alias.value, str):
            return alias.value
        if isinstance(alias, ast.Call) and alias.args:
            first = alias.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return first.value
        msg = f"cannot read the alias {ast.unparse(alias)!r} statically"
        raise InventoryError(msg)
    return None


def declared_fields(node: ast.ClassDef) -> list[SettingField]:
    """The settings a class body declares itself, ignoring its bases."""
    fields = []
    for statement in node.body:
        if not (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        ):
            continue
        name = statement.target.id
        if (
            name.startswith("_")
            or name in _SKIPPED_NAMES
            or _is_class_var(statement.annotation)
        ):
            continue
        fields.append(SettingField(name, _alias(statement.value), node.name, statement))
    return fields


def module_fields(path: Path) -> dict[str, SettingField]:
    """Every setting declared by any top-level class in ``path``, bases ignored."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, SettingField] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for declared in declared_fields(node):
                found.setdefault(declared.name, declared)
    return found


class _Walker:
    def __init__(self, modules: Mapping[str, Path]) -> None:
        self._overrides = dict(modules)
        self._cache: dict[Path, _Module] = {}

    def module(self, path: Path) -> _Module:
        path = path.resolve()
        if path not in self._cache:
            self._cache[path] = _Module(
                path, ast.parse(path.read_text(encoding="utf-8"))
            )
        return self._cache[path]

    def _locate(self, module: _Module, name: str) -> tuple[_Module, ast.ClassDef]:
        local = module.class_def(name)
        if local is not None:
            return module, local
        source = module.imported_from(name)
        if source is None:
            msg = f"{module.path}: base {name!r} is neither defined nor imported there"
            raise InventoryError(msg)
        dotted, level = source
        written = "." * level + dotted
        if written in self._overrides:
            path = self._overrides[written]
        elif level:
            path = module.path.parents[level - 1].joinpath(*dotted.split("."))
            path = path.with_suffix(".py")
        else:
            msg = (
                f"{module.path}: base {name!r} comes from {written!r}, which "
                "is not a file the walker can follow"
            )
            raise InventoryError(msg)
        if not path.is_file():
            msg = (
                f"{module.path}: base {name!r} resolves to {path}, which does not exist"
            )
            raise InventoryError(msg)
        target = self.module(path)
        found = target.class_def(name)
        if found is None:
            msg = f"{path} does not define {name!r}"
            raise InventoryError(msg)
        return target, found

    def walk(self, module: _Module, node: ast.ClassDef) -> list[SettingField]:
        """Fields along ``node``'s bases, the most-derived declaration first."""
        fields = declared_fields(node)
        for base in node.bases:
            if not isinstance(base, ast.Name):
                msg = f"{module.path}: cannot follow base {ast.unparse(base)!r}"
                raise InventoryError(msg)
            if base.id in TERMINAL_BASES:
                continue
            fields += self.walk(*self._locate(module, base.id))
        return fields


def inventory(
    entry: Path, class_name: str, modules: Mapping[str, Path] | None = None
) -> dict[str, SettingField]:
    """Every setting ``class_name`` in ``entry`` declares, keyed by field name.

    :param entry: The module defining the class.
    :param class_name: The settings class to inventory.
    :param modules: Files for imports that are not where the walker would look
        on disk, keyed by the module as the importing file spells it (e.g.
        ``".models.base"`` for a file the image build injects).
    :returns: One :class:`SettingField` per name. Where a subclass redeclares
        a field, the subclass's declaration wins, as it does in pydantic.
    :raises InventoryError: On a base that cannot be followed to a file,
        rather than silently returning an inventory that misses its fields.
    """
    walker = _Walker(modules or {})
    module = walker.module(entry)
    node = module.class_def(class_name)
    if node is None:
        msg = f"{entry} does not define {class_name!r}"
        raise InventoryError(msg)
    found: dict[str, SettingField] = {}
    for declared in walker.walk(module, node):
        found.setdefault(declared.name, declared)
    return found


def configured_class(entry: Path) -> str:
    """The class an aqueduct entry module passes to ``configure_django_settings``."""
    tree = ast.parse(entry.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "configure_django_settings"
            and node.value.args
            and isinstance(node.value.args[0], ast.Name)
        ):
            return node.value.args[0].id
    msg = f"{entry} never calls configure_django_settings(<SettingsClass>, ...)"
    raise InventoryError(msg)
