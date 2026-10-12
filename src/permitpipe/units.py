"""Convert reported generator ratings to kW, keeping what was reported.

Permits state output as kW (electrical), MW, kVA (apparent power) or hp/bhp
(engine shaft power). kVA -> kW needs a power factor; hp -> kWe needs an
alternator efficiency. Those conversions return the assumption used so the
record can flag it.
"""

from __future__ import annotations

HP_TO_KW = 0.745699872
DEFAULT_PF = 0.8              # standard genset nameplate power factor
DEFAULT_GEN_EFF = 0.95        # shaft -> electrical, large diesel gensets


def to_kw(value: float, unit: str) -> tuple[float, str | None]:
    """Return (kW, assumption or None)."""
    u = unit.strip().lower().replace("-", "").replace(" ", "")
    if u in {"kw", "kwe", "ekw"}:
        return value, None
    if u in {"mw", "mwe"}:
        return value * 1000, None
    if u == "kva":
        return value * DEFAULT_PF, f"pf={DEFAULT_PF}"
    if u == "mva":
        return value * 1000 * DEFAULT_PF, f"pf={DEFAULT_PF}"
    if u in {"hp", "bhp"}:
        return value * HP_TO_KW * DEFAULT_GEN_EFF, f"shaft_to_electric_eff={DEFAULT_GEN_EFF}"
    if u in {"mmbtu/hr", "mmbtuhr"}:
        raise ValueError("heat input is not an output rating; keep as reported")
    raise ValueError(f"unknown rating unit: {unit!r}")
