"""The production data plane (R11): connectors, quarantine, replay.

F20-DI1 (connector framework + source registry), F20-DI2
(quarantine & correction workflow) and F20-DI4 (historical
backfill & replay). Everything a real feed would meet on its
way into the observations table lives here: a registered
source, one validation path for every connector, bad rows
quarantined with named reasons instead of silently dropped
or silently loaded, corrections as insert-only overlays, and
a provenance row for every fact a connector lands.
"""
