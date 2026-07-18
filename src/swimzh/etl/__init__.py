"""Medallion ETL as pure functions: raw -> silver -> gold.

Framework-agnostic on purpose. Each stage is an ordinary function returning a Result;
Dagster (later) wraps these as assets and converts Err -> raise at its boundary. Building
them as functions first keeps the pipeline fully testable offline.
"""
