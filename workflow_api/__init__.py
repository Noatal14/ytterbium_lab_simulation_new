"""Side-effect-free application API for simulation workflows.

The modules in :mod:`studies` remain the stable command-line compatibility
surface.  UI code should use this package for inspection and planning so that
opening a page can never submit a scheduler job or run a simulation.
"""

from workflow_api.catalog import list_workflows
from workflow_api.mot_2d import read_campaign

__all__ = ["list_workflows", "read_campaign"]
