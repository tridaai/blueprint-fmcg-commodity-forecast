"""Geospatial basis & netting (R14: F20-PO4, F20-GS1, F20-GS2).

The basis between a commodity's markets — the spread of each
market's modal price against the reference market's, judged
against the spread's own history band — plus the desk-entered
freight and handling lines that turn market prices into landed
costs, and the schematic market map that plots all of it by
region with the alert state and the weather/event overlay.
Every figure is computed in code from stored facts; a market
whose landed lines are incomplete reads not_computable naming
the missing line, and a market with no current data renders
as a named gap, never a zero.
"""
