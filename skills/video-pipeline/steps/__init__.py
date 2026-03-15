"""Pipeline step modules — one file per pipeline stage.

Each step module exports a single `run(pipeline) -> dict` async function.
The pipeline instance provides access to all clients and current idea state.
"""
