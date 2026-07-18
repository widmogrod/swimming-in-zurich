"""provider/core: the cross-provider contract.

Every provider returns a `Result[TOk, ProviderError]`. The Ok payload differs per
provider; the error union is standardised so downstream code handles error paths
uniformly and exhaustively.
"""

from swimzh.core.errors import (
    ConnectionFailed,
    DecodeError,
    HttpStatus,
    ParseError,
    ProviderError,
    ProviderSpecific,
    RateLimited,
    Redirect,
    SchemaMismatch,
    Timeout,
    TooLarge,
    describe,
    retriable,
)
from swimzh.core.result import Err, Ok, Result, ResultError, bind, fmap

__all__ = [
    "ConnectionFailed",
    "DecodeError",
    "Err",
    "HttpStatus",
    "Ok",
    "ParseError",
    "ProviderError",
    "ProviderSpecific",
    "RateLimited",
    "Redirect",
    "Result",
    "ResultError",
    "SchemaMismatch",
    "Timeout",
    "TooLarge",
    "bind",
    "describe",
    "fmap",
    "retriable",
]
