"""The event registry package (R5, Law 4).

Shocks are declared events, not silent adjustments: an analyst act
registers each event with its class, its effective window and its
stated transmission — which driver it moves, by what estimated
magnitude, on what named basis. The registry never "detects" an
event from a price move; measurement (the YoY seasonally-matched
comparison, the baseline-projection impact view) is a separate
layer that CHECKS a declared transmission against history, it does
not create events.

ISOLATION LAW: like the forecast and backtest packages, nothing in
this package may import the grading-truth store
(``fmcg_forecast.truth``) or read the truth table. Events are
declared and measured against observed history only. The eval
gate's AST scan covers this package.
"""
