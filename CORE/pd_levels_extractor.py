"""pd_levels_extractor.py — Extraction niveaux Previous Day depuis JSONL DMP.

Spec : DOCS/specs/2026-04-28-rules-trader-pd-attentiste-design.md section 3.

Niveaux extraits (depuis la derniere barre RTH = mins_et 959, ou fallback) :
    PDH, PDL, PDC, PVWAP, PVAH, PVAL, PVPOC, PSD+1, PSD-1
    + meta : day_type, open_type, open_bias_conf

Anti-leak : extraction APRES close RTH du jour J pour usage J+1.
Ecrit dans DATA/PD_LEVELS/YYYYMMDD_{symbol}.json.

Auteur : MIA Trading System V2
Date   : 2026-04-28 00:40 (Voie 2 Bloc 1 — Plan B Rules PD)
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class PDLevels:
    """Niveaux Previous Day pour usage J+1 par rules_trader_pd_attentiste."""
    symbol: str
    date: str  # YYYY-MM-DD du jour J (la session dont on extrait les niveaux)

    # 9 niveaux clefs
    PDH: float          # Previous Day High RTH
    PDL: float          # Previous Day Low RTH
    PDC: float          # Previous Day Close RTH (close de la derniere barre RTH)
    PVWAP: float        # Previous Daily VWAP a close
    PVAH: float         # Previous Value Area High
    PVAL: float         # Previous Value Area Low
    PVPOC: float        # Previous Volume POC
    PSD_plus_1: float   # Previous SD +1 du Daily VWAP
    PSD_minus_1: float  # Previous SD -1 du Daily VWAP

    # Meta context
    day_type: Optional[int]
    open_type: Optional[int]
    open_bias_conf: Optional[float]

    computed_at_et: str  # ISO timestamp ET

    def to_dict(self) -> dict:
        return asdict(self)


def _et_minutes_from_ms(ts_ms: int) -> int:
    """Convert UTC ms timestamp -> ET minutes-of-day (approximation EDT UTC-4)."""
    dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    # EDT = UTC-4 (approximation, valide d'avril a octobre).
    # Pour EST (novembre-mars), serait UTC-5. Bot ne tradera US RTH only,
    # session 09:30-16:00 ET, donc l'erreur de 1h en hiver est tolerable.
    et_hour = (dt_utc.hour - 4) % 24
    return et_hour * 60 + dt_utc.minute


def _parse_jsonl_safe(path: Path, max_warn: int = 5) -> list:
    """Parse JSONL avec skip+log des lignes corrompues."""
    rows = []
    n_skip = 0
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                n_skip += 1
                if n_skip <= max_warn:
                    print(f"  [pd_levels_extractor] skip line {ln} (invalid JSON)", file=sys.stdout)
                continue
    if n_skip > max_warn:
        print(f"  [pd_levels_extractor] ... +{n_skip - max_warn} other corrupt lines", file=sys.stdout)
    return rows


def extract_pd_levels(jsonl_path: str, symbol: str) -> Optional[PDLevels]:
    """Extrait niveaux Previous Day depuis JSONL DMP du jour J.

    Args:
        jsonl_path: chemin DATA/{ES,NQ}/YYYYMMDD_{symbol}.jsonl
        symbol: 'ES' ou 'NQ'

    Returns:
        PDLevels object si OK, None si fichier absent/vide/corrompu integral.
    """
    p = Path(jsonl_path)
    if not p.exists():
        # Cas weekend/holiday — pas un crash
        return None

    rows = _parse_jsonl_safe(p)
    if not rows:
        print(f"  [pd_levels_extractor] {p.name} : 0 valid rows", file=sys.stdout)
        return None

    # Filtrer RTH bars (mins_et 570-960 = 09:30-16:00 ET)
    for r in rows:
        r["_mins_et"] = _et_minutes_from_ms(r["ts"])
    rth = [r for r in rows if 570 <= r["_mins_et"] <= 960]
    if not rth:
        print(f"  [pd_levels_extractor] {p.name} : 0 RTH bars", file=sys.stdout)
        return None

    # Tri par ts ascendant
    rth.sort(key=lambda r: r["ts"])

    # Cible : derniere barre RTH (la plus tardive avant ou a 16:00 ET)
    # = close session = source de verite pour PDC et niveaux a la close.
    target = rth[-1]

    # PDH / PDL depuis high/low de toutes les RTH bars
    pdh = max(r.get("high", r["price"]) for r in rth)
    pdl = min(r.get("low", r["price"]) for r in rth)
    pdc = float(target.get("close", target["price"]))

    # Niveaux relatifs : prix derniere barre + dist_*
    # Convention DMP uniforme : dist_X = X - price, donc X = price + dist_X.
    # Verifie empiriquement sur 27/04 NQ : dist_cur_vah=+105 (vah au-dessus prix),
    # dist_cur_val=-27 (val sous prix), dist_cur_vpoc=+45 (vpoc au-dessus 27418).
    p_now = float(target["price"])

    def _sf(v):
        """Safe float : None/missing → 0.0 (niveau = prix, neutralise)."""
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    pvpoc = p_now + _sf(target.get("dist_cur_vpoc"))
    pvah = p_now + _sf(target.get("dist_cur_vah"))
    pval = p_now + _sf(target.get("dist_cur_val"))
    pvwap = p_now + _sf(target.get("dist_vwap_d"))
    psd_plus_1 = p_now + _sf(target.get("dist_vwap_d_sd1u"))
    psd_minus_1 = p_now + _sf(target.get("dist_vwap_d_sd1d"))

    # Meta — None si absent
    day_type = target.get("day_type")
    open_type = target.get("open_type")
    open_bias_conf = target.get("open_bias_conf")
    if day_type is None or open_type is None or open_bias_conf is None:
        print(f"  [pd_levels_extractor] {p.name} : meta partiellement absent "
              f"(day_type={day_type}, open_type={open_type}, "
              f"open_bias_conf={open_bias_conf})", file=sys.stdout)

    # Date du jour J
    date_str = datetime.fromtimestamp(target["ts"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    return PDLevels(
        symbol=symbol,
        date=date_str,
        PDH=float(pdh), PDL=float(pdl), PDC=pdc,
        PVWAP=float(pvwap),
        PVAH=float(pvah),
        PVAL=float(pval),
        PVPOC=float(pvpoc),
        PSD_plus_1=float(psd_plus_1),
        PSD_minus_1=float(psd_minus_1),
        day_type=int(day_type) if day_type is not None else None,
        open_type=int(open_type) if open_type is not None else None,
        open_bias_conf=float(open_bias_conf) if open_bias_conf is not None else None,
        computed_at_et=datetime.now(timezone.utc).isoformat(),
    )


def write_pd_levels(pdl: PDLevels, out_dir: str = "DATA/PD_LEVELS") -> Path:
    """Sauvegarde PDLevels JSON dans DATA/PD_LEVELS/YYYYMMDD_{symbol}.json."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fname = f"{pdl.date.replace('-', '')}_{pdl.symbol}.json"
    fp = out / fname
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(pdl.to_dict(), f, indent=2, default=str)
    return fp


def main():
    """CLI : python -m CORE.pd_levels_extractor <symbol> <jsonl_path>"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", choices=["ES", "NQ"])
    parser.add_argument("jsonl_path")
    parser.add_argument("--out-dir", default="DATA/PD_LEVELS")
    args = parser.parse_args()

    pdl = extract_pd_levels(args.jsonl_path, args.symbol)
    if pdl is None:
        print(f"[FAIL] No PD levels extracted from {args.jsonl_path}")
        sys.exit(1)
    fp = write_pd_levels(pdl, args.out_dir)
    print(f"[OK] PD levels written: {fp}")
    print(f"  PDH={pdl.PDH:.2f} PDL={pdl.PDL:.2f} PDC={pdl.PDC:.2f}")
    print(f"  PVWAP={pdl.PVWAP:.2f} PVAH={pdl.PVAH:.2f} PVAL={pdl.PVAL:.2f} PVPOC={pdl.PVPOC:.2f}")
    print(f"  PSD+1={pdl.PSD_plus_1:.2f} PSD-1={pdl.PSD_minus_1:.2f}")
    print(f"  day_type={pdl.day_type} open_type={pdl.open_type} bias={pdl.open_bias_conf}")


if __name__ == "__main__":
    main()
