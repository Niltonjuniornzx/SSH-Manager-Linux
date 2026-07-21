"""Conversão segura de enums (Qt QComboBox devolve strings para str Enum)."""

from __future__ import annotations

from enum import Enum
from typing import TypeVar

E = TypeVar("E", bound=Enum)


def coerce_enum(enum_cls: type[E], value: object, default: E | None = None) -> E:
    """
    Converte value para enum_cls.

    Aceita instância do enum, string do value, ou nome do membro.
    """
    if isinstance(value, enum_cls):
        return value
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"Valor None para {enum_cls.__name__}")
    try:
        return enum_cls(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        pass
    # tentar por nome
    try:
        return enum_cls[str(value)]
    except KeyError:
        pass
    if default is not None:
        return default
    raise ValueError(f"Valor inválido para {enum_cls.__name__}: {value!r}")


def enum_value(value: object) -> object:
    """Extrai .value se for Enum, senão devolve o próprio valor."""
    if isinstance(value, Enum):
        return value.value
    return value
