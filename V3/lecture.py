"""La lecture d'une barre — le seul endroit qui calcule.

Les portes comparent, elles ne calculent pas. Une porte qui calcule est une
porte qu'on ne peut pas tester sans un DataFrame complet ; avec ce decoupage,
chaque porte se teste avec un dict de trois cles.

C'est aussi le seul endroit qui connait les noms de colonnes. Le jour ou une
colonne change de nom, une ligne bouge — pas neuf portes.
"""

from __future__ import annotations

import pandas as pd


def val(df, col, i):
    if col not in df.columns:
        return None
    v = pd.to_numeric(pd.Series([df[col].iloc[i]]), errors="coerce").iloc[0]
    return None if pd.isna(v) else float(v)


def vrai(df, col, i):
    v = val(df, col, i)
    return v is not None and v != 0


def lire(df, i, sym="ES"):
    """Prepare la barre `i` pour toutes les portes, L0 et L5."""
    ts = int(df["ts"].iloc[i])
    t = pd.Timestamp(ts, unit="ms", tz="UTC")
    return {
        "ts": ts, "sym": sym, "i": i,
        "minute_utc": t.hour * 60 + t.minute,
        "jour": str(df["jour"].iloc[i]) if "jour" in df.columns else "",
        # --- L0 ---
        "news_60m": vrai(df, "is_news_60m", i),
        "session_bloquee": vrai(df, "is_session_blocked", i),
        "vix_regime": val(df, "vix_regime", i),
        # --- L5 ---
        "gamma_block_long": vrai(df, "gamma_block_long", i),
        "rvol_zscore": val(df, "rvol_zscore", i),
        "atr5": val(df, "atr5", i),
    }
