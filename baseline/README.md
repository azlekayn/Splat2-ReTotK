# Vendored runtime baseline

`totk-recomp/` is a source copy of
[`Muhammad1259-sigma/totk-recomp`](https://github.com/Muhammad1259-sigma/totk-recomp)
at commit `a32f709` (MIT, `Copyright (c) 2026 the totk-recomp contributors`).

It is the Linux/Steam Deck static-recompilation runtime for *Tears of the Kingdom*, used here
as the starting point for the Splatoon 2 port. The copy contains no game code or game data.

One local change is included: `tools/recomp/gen.py` now handles the two-operand scalar
`FADDP Sd, Vn.2S` form, which the upstream generator left unhandled. That is required to
lift Splatoon 2's `main` with zero unhandled instructions.

See [`../SPLAT2_RETOTK_PLAN.md`](../SPLAT2_RETOTK_PLAN.md) for the port plan and measured
coverage.
