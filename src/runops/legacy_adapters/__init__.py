"""Ports of the runops v1 ``emses`` / ``beach`` adapters (SPEC §8.5).

They are not registered. ``runo init`` copies one into the project's
``adapters/`` directory when no installed package provides the adapter, so the
project works until the simulator package ships its ``runops.adapters`` entry point.
"""
