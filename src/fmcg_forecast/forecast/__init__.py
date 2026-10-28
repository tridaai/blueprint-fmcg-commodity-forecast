"""The forecast engine package (engine lands in R2).

ISOLATION LAW: nothing in this package may import the grading-truth
store (``fmcg_forecast.truth``) or read the truth table. The engine
is graded against the sealed future path; it must never see it. A
structural test and the eval gate scan this package's import graph.
"""
