"""Data providers (adapters). Each returns `Result[TOk, ProviderError]`; the Ok payload is
provider-specific, the error union is the standardised `core.ProviderError`.
"""
