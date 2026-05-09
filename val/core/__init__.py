"""VAL Core Package — import directly from submodules to avoid circular imports"""
# Do NOT add eager imports here. Circular: engine → models.router → core.planner → core.__init__ → engine
__all__ = []

