"""Alerting, subscriptions and escalation (R9, F20-AL1/AL2/AL3).

Subscriptions are desk-entered artefacts. Alerts are derived from
artefacts of record — struck buy signals, declared event windows,
computed price crossings, the accuracy ledger — and pinned to the
triggering artefact. An alert's state is the fold of attributed
acts plus the pack's escalation clock, derived at read. Nothing
here places a trade: every alert carries the signal scope note.
"""
