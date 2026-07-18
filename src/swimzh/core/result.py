"""A hand-rolled `Result` (Either) type: errors as values, not exceptions.

Why not the `returns` library? Under `pyright --strict` there is no mypy plugin, so
`returns`' higher-kinded machinery degrades and its `Success/Failure` wrapper hides the
very thing we want in the match position: the error union. A small frozen-dataclass
`Ok | Err` gives real exhaustiveness (`assert_never` reaches `Never`), zero dependencies,
and native structural pattern matching.

Combinators (`fmap`, `bind`) are module-level functions rather than methods. On a split
`Ok[T] | Err[E]` union, a `.map(...)` *method* forces the lambda's parameter type to widen
to `object` (the union can't thread the success type through a per-class method). A free
function typed `Result[T, E] -> ...` threads the generics precisely instead.

Usage::

    match fetch():
        case Ok(value):
            ...
        case Err(error):
            match error:                      # exhaustive over ProviderError
                case Timeout(): ...
                case _ as unreachable:
                    assert_never(unreachable)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

# NOTE: dataclasses here are intentionally NOT kw_only, so positional match patterns
# (`case Ok(value)`) bind via the generated __match_args__.


@dataclass(frozen=True, slots=True)
class Ok[T]:
    """A successful result carrying a value."""

    value: T

    def is_ok(self) -> bool:
        return True

    def unwrap_or(self, _default: T) -> T:
        return self.value

    def unwrap_or_raise(self) -> T:
        """Return the value; used at the ETL/Dagster boundary where the framework wants
        exceptions. The library core does not call this on hot paths."""
        return self.value


@dataclass(frozen=True, slots=True)
class Err[E]:
    """A failed result carrying a typed error value."""

    error: E

    def is_ok(self) -> bool:
        return False

    def unwrap_or[T](self, default: T) -> T:
        return default

    def unwrap_or_raise(self) -> NoReturn:
        raise ResultError(self.error)


type Result[T, E] = Ok[T] | Err[E]


class ResultError(Exception):
    """Raised by `Err.unwrap_or_raise()` to cross into exception-based frameworks.

    The wrapped `.error` is the original typed error value, so callers that want the
    structured error can still recover it.
    """

    def __init__(self, error: object) -> None:
        super().__init__(repr(error))
        self.error = error


def fmap[T, U, E](result: Result[T, E], fn: Callable[[T], U]) -> Result[U, E]:
    """Apply `fn` to the value of an `Ok`, passing `Err` through unchanged."""
    match result:
        case Ok(value):
            return Ok(fn(value))
        case Err(error):
            return Err(error)


def bind[T, U, E](result: Result[T, E], fn: Callable[[T], Result[U, E]]) -> Result[U, E]:
    """Chain a Result-returning `fn` onto an `Ok`, passing `Err` through unchanged."""
    match result:
        case Ok(value):
            return fn(value)
        case Err(error):
            return Err(error)
