"""The backtest harness + accuracy ledger package (R3, Law 2).

The harness is the one caller allowed to run the engine at past
origins, through the engine's explicit ``via_backtest`` seam — and
even here, history origins are scored against the observations
table (observed history) through the store port. This package
never imports the grading-truth store: the sealed boundary check
is composed by the eval gate, which hands truth rows in to
``harness.score_sealed_boundary``. The AST isolation scan in the
tests and the eval gate covers this package alongside the forecast
package.
"""
