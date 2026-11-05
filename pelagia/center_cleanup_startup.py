"""Temporary startup hook for rolling out the cleaned dive-center catalogue.

The registry serializes concurrent workers and records the CSV digest, so this
hook applies the replacement once per catalogue version and is safe on restart.
After the rollout, remove this module and call center_registry.refresh_centers
directly from create_app again.
"""

from . import center_registry


def apply(db, app):
    return center_registry.refresh_centers(db, center_registry.configured_csv(app))
