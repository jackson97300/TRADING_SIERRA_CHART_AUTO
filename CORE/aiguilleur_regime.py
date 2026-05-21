"""aiguilleur_regime.py — Detecteur de contexte TENDANCE / RANGE / NEUTRE.

Role : c'est l'AIGUILLEUR du bot. Il determine le contexte de marche pour
router vers le bon setup :
  - TENDANCE -> setup continuation (achat du pullback sur niveau)
  - RANGE    -> setup fade des extremes
  - NEUTRE   -> zone grise : le bot NE TRADE PAS

Methode : Choppiness Index + Efficiency Ratio (Kaufman), calcules sur barres
5-min AGREGEES depuis le 1-min. Le 1-min pur est trop bruite (aucun detecteur
> 66% precision) ; l'agregation 5-min debloque le signal.

Validation empirique (agent market-analyst, 2026-05-21, live_enriched NQ/ES,
4 jours) : CI 5-min AUC 0.81, ER 5-min AUC 0.82. Sur la verite terrain
NQ 21/05 : ER = 0.50 en tendance vs 0.13 en range ; CI = 44 vs 53.

RESERVE : seuils valides sur 4 jours seulement (echantillon tendance faible).
A REVALIDER sur 15+ jours avant tout deploiement capital.

Seuils :
  TENDANCE si CI < 46 ET ER > 0.35
  RANGE    si CI > 52 OU ER < 0.20
  NEUTRE   sinon (zone grise -> pas de trade)
"""
from __future__ import annotations

import math

# ─── Parametres (calibres agent 21/05, a revalider 15+ jours) ──────────
CI_PERIOD: int = 14
ER_PERIOD: int = 14
CI_TREND_MAX: float = 46.0
CI_RANGE_MIN: float = 52.0
ER_TREND_MIN: float = 0.35
ER_RANGE_MAX: float = 0.20
BUCKET_SEC: int = 300  # agregation 5-min


def aggregate_5m(bars_1m: list[dict]) -> list[dict]:
    """Agrege des barres 1-min en barres 5-min.

    bars_1m : liste de dicts {ts (epoch sec), high, low, close}, ordre chrono.
    Retourne la liste des barres 5-min (high=max, low=min, close=dernier).
    """
    buckets: dict[int, dict] = {}
    for b in bars_1m:
        bk = (int(b["ts"]) // BUCKET_SEC) * BUCKET_SEC
        cur = buckets.get(bk)
        if cur is None:
            buckets[bk] = {"ts": bk, "high": float(b["high"]),
                           "low": float(b["low"]), "close": float(b["close"])}
        else:
            cur["high"] = max(cur["high"], float(b["high"]))
            cur["low"] = min(cur["low"], float(b["low"]))
            cur["close"] = float(b["close"])
    return [buckets[k] for k in sorted(buckets)]


def choppiness_index(bars5: list[dict], n: int = CI_PERIOD) -> float | None:
    """Choppiness Index sur les n dernieres barres 5-min.

    Bas (<46) = mouvement efficient = tendance.
    Haut (>52) = prix qui zigzague = range.
    Retourne None si pas assez de barres.
    """
    if len(bars5) < n + 1:
        return None
    tr_sum = 0.0
    for i in range(len(bars5) - n, len(bars5)):
        h, l = bars5[i]["high"], bars5[i]["low"]
        pc = bars5[i - 1]["close"]
        tr_sum += max(h - l, abs(h - pc), abs(l - pc))
    window = bars5[-n:]
    rng = max(b["high"] for b in window) - min(b["low"] for b in window)
    if rng <= 0 or tr_sum <= 0:
        return None
    return 100.0 * math.log10(tr_sum / rng) / math.log10(n)


def efficiency_ratio(bars5: list[dict], n: int = ER_PERIOD) -> float | None:
    """Efficiency Ratio de Kaufman sur les n dernieres barres 5-min.

    ~1 = trajectoire droite = tendance. ~0 = zigzag = range.
    Retourne None si pas assez de barres.
    """
    if len(bars5) < n + 1:
        return None
    closes = [b["close"] for b in bars5[-(n + 1):]]
    net = abs(closes[-1] - closes[0])
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    if path <= 0:
        return None
    return net / path


def detect_regime(bars_1m: list[dict]) -> dict:
    """Aiguilleur : determine le regime depuis les barres 1-min.

    bars_1m : liste de dicts {ts, high, low, close} ordre chrono (tout
    l'historique disponible jusqu'a l'instant courant).
    Retourne {regime, ci, er, n_bars_5m} avec regime in
    {TENDANCE, RANGE, NEUTRE}.
    """
    bars5 = aggregate_5m(bars_1m)
    ci = choppiness_index(bars5)
    er = efficiency_ratio(bars5)
    if ci is None or er is None:
        regime = "NEUTRE"
    elif ci < CI_TREND_MAX and er > ER_TREND_MIN:
        regime = "TENDANCE"
    elif ci > CI_RANGE_MIN or er < ER_RANGE_MAX:
        regime = "RANGE"
    else:
        regime = "NEUTRE"
    return {"regime": regime, "ci": ci, "er": er, "n_bars_5m": len(bars5)}


if __name__ == "__main__":
    # Smoke test : tendance droite vs range zigzag
    trend = [{"ts": i * 60, "high": 100 + i + 0.5, "low": 100 + i - 0.5,
              "close": 100 + i} for i in range(120)]
    rng = [{"ts": i * 60, "high": 100 + (i % 4) + 0.5,
            "low": 100 + (i % 4) - 0.5, "close": 100 + (i % 4)}
           for i in range(120)]
    print("tendance droite :", detect_regime(trend))
    print("range zigzag    :", detect_regime(rng))
