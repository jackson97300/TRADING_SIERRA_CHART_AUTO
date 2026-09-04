"""v4_reader.py — Lecture parquet V4 enriched pour dashboard live.

Source : DATA/datasets/v4_enriched/symbol={ES,NQ}.c.0/year=YYYY/month=MM/data.parquet

Contenu V4 (456 cols NQ / 445 ES) :
  - Toutes features DMP +
  - Features dérivées Python (delta_div_*, trapped_*_at_resistance, poc_migration_dir, ...)
  - Inter-marché ES/NQ (im_*)
  - Composites SMT, naked POC, blind levels, edges
  - Updated live par pipeline `build_dataset_v4_dmp_databento.py` (mtime ~5 min)

Cache TTL : 5s (le parquet n'est pas mis a jour plus souvent).

SAFETY 04/05 (audit code-reviewer R2) :
  - Whitelist `V4_ONLY_FEATURES` : SEULES ces colonnes V4 ecrasent le DMP.
  - Check staleness : si V4 mtime > V4_STALE_SEC, merge desactive.
  - Tout le reste (prix absolus VPOC/VAH/VAL/VWAP/IB) reste DMP frais.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
V4_BASE = ROOT / "DATA" / "datasets" / "v4_enriched"

# Cache : {symbol: (timestamp, last_row_dict)} + lock (R3 race condition fix)
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL_SEC = 5.0
_V4_STALE_SEC = 2700  # 45 min : au-dela, V4 considere stale (pipeline lag).
                       # 13/05 Jackson bump 600->2700 (code-reviewer reserve R1) :
                       # pipeline V4 Historical Databento a un delay inherent 15-30min
                       # (DATABENTO_DELAY_MIN=15 + Phase_B retraitement mois entier ~3min
                       # + iter loop 5min). Empirique 13/05 : DMP-V4 diff steady-state
                       # 17-25min mais pic observe 48min (lag transitoire). Seuil 2700s
                       # couvre 95% des cas observes sans depasser 3000s.
                       # Compromis safety : V4_ONLY_FEATURES (cluster, big_orders, smt,
                       # naked_poc, im_*, n_*_zones_active) = signaux d'evenements par-bar
                       # (volume aggregations, big trades, divergences) PAS niveaux de prix
                       # → ne derivent pas fortement en 45min. Acceptable.
                       # CAS-LIMITE R2 reviewer : near_resistance_level/near_support_level
                       # restent dans whitelist V4_ONLY_FEATURES. A 45min stale + move
                       # directionnel fort (>10t ES/40t NQ), ces flags peuvent etre faux.
                       # Dette tech a traiter post-refacto pipeline incremental (P1 backlog).
                       # ZERO impact bots : merge_dmp_v4 utilise uniquement dashboard
                       # (verifie grep cross-codebase 13/05). Bot 1/2/3 lisent DMP JSONL
                       # ou V4 parquet directement, pas via cette fonction.
                       # A revoir post-refacto pipeline V4 incremental (priorite 1 backlog)
                       # quand lag steady-state passera a <5min -> retour 300-600s.

# 13/05 R4 reviewer : telemetrie compteur skip cumule (warning toutes 10 skip)
# pour visibilite "le bump 2700s suffit-il ?" sans devoir grep logs en continu.
_merge_skip_count = 0
_MERGE_SKIP_LOG_EVERY = 10

# Whitelist : SEULES ces features V4 ont le droit d'ecraser DMP au merge.
# Le reste (cur_vpoc, vwap_d, ib_high, etc.) reste DMP frais meme si V4 plus jeune.
# Source : audit code-reviewer R2 04/05 — protege contre V4 stale 70h vs DMP live.
V4_ONLY_FEATURES = frozenset({
    # Cluster acheteur/vendeur (V4-only, pas dans DMP)
    "n_clusters", "n_cluster_groups", "max_cluster_size", "max_cluster_volume",
    "max_cluster_volume_v2", "gex_cluster_count_z",
    "dist_cluster_nearest_up_pct", "dist_cluster_nearest_dn_pct",
    "cluster_at_high", "cluster_at_low",
    "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
    "n_delta_div_buy_cluster_within_0_2pct", "n_delta_div_sell_cluster_within_0_2pct",
    "n_spike_origins_cluster_within_0_2pct",
    "n_trapped_buyers_cluster_within_0_2pct", "n_trapped_sellers_cluster_within_0_2pct",
    # Big orders (V4-only)
    "big_buy_dominance", "big_sell_dominance",
    "dist_big_ask_nearest_pct", "dist_big_bid_nearest_pct",
    "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar",
    "n_big_ask_t1", "n_big_ask_t2", "n_big_ask_t3", "n_big_ask_t4",
    "n_big_bid_t1", "n_big_bid_t2", "n_big_bid_t3", "n_big_bid_t4",
    "n_big_ask_v2_t1", "n_big_ask_v2_t2", "n_big_ask_v2_t3", "n_big_ask_v2_t4",
    "n_big_bid_v2_t1", "n_big_bid_v2_t2", "n_big_bid_v2_t3", "n_big_bid_v2_t4",
    "n_big_t1", "n_big_t2", "n_big_t3", "n_big_t4",
    # Inter-marche ES/NQ (V4-only)
    "im_smt_divergence", "im_delta_day_divergence",
    # Naked POC (V4-only)
    "dist_naked_poc_nearest_pct", "n_naked_poc_active",
    "n_naked_poc_within_0_5pct", "naked_poc_age_max_days",
    # Zones actives (V4-only — cumuls stables)
    "n_color_up_zones_active", "n_color_dn_zones_active",
    "n_delta_div_buy_zones_active", "n_delta_div_sell_zones_active",
    "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
    # Delta divergence V4-side (le pipeline V4 calcule sa version cleane)
    "delta_div_buy", "delta_div_sell", "delta_divergence",
    "dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct",
    # Trapped @ niveau (V4 enriched)
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
    "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
    # Absorption @ niveau (V4-only nommage)
    "bn_absorb_bid_at_level", "bn_absorb_ask_at_level",
    "bn_absorb_bid_raw", "bn_absorb_ask_raw",
    # Near level booleens (HVL/POC/VWAP/BL) — refactor 04/05 cluster swap
    "near_resistance_level", "near_support_level",
    # Stack ASK/BID (N consecutive cells qualifiees)
    "bn_stack_ask", "bn_stack_bid",
    # Spike origins (recent V4)
    "spike_detected_lag3", "n_spike_origins_active",
    "n_spike_origins_cluster_within_0_2pct",
    # Naked POC supplementaires
    "n_naked_poc_within_0_5pct",
})


def _v4_path(symbol: str) -> Optional[Path]:
    """Resoud le chemin parquet V4 du mois courant pour un symbole.

    Audit R7 : retourne le mois courant prioritaire ; si absent OU vide,
    fallback mois precedent.

    11/05 J2c FIX B2 (code-reviewer) — DECOUPLAGE NAMING vs TICKER :
    Le `.c.0` ici est une convention de NAMING du storage V4 enriched
    (cf build_dataset_v4_dmp_databento.py:1079 `write_partitioned` hardcode
    `out_base = OUT_ROOT / f"symbol={symbol}.c.0"`). Pour TOUS les symboles
    (ES, NQ, MGC), le dataset est stocke sous `symbol={X}.c.0` MEME pour MGC.
    Ce `.c.0` n'est PAS le ticker Databento (qui est `MGC.v.0` pour eviter
    le bug rollover GC documente lessons.md 10/05).

    Cohenrence avec write_partitioned : OK (storage = `.c.0` toujours).
    Si refactor pipeline pour aligner storage sur ticker → mettre a jour
    write_partitioned ET ce code en miroir.

    Args:
        symbol : "ES", "NQ", "MGC" (ou variantes ".c.0"/".v.0")

    Returns:
        Liste ordonnee de Path candidats (mois courant, mois precedent),
        seulement ceux qui existent. None si aucun.
    """
    sym_norm = symbol.upper().replace(".C.0", "").replace(".V.0", "")
    # Convention storage V4 enriched : TOUJOURS `.c.0` (cf docstring).
    sym_full = f"{sym_norm}.c.0"
    now = datetime.now(timezone.utc)
    candidates = []
    # Mois courant
    candidate = V4_BASE / f"symbol={sym_full}" / f"year={now.year}" / f"month={now.month:02d}" / "data.parquet"
    if candidate.exists():
        candidates.append(candidate)
    # Mois precedent (fallback debut de mois OU mois courant vide/stale)
    prev_month = now.month - 1 if now.month > 1 else 12
    prev_year = now.year if now.month > 1 else now.year - 1
    fallback = V4_BASE / f"symbol={sym_full}" / f"year={prev_year}" / f"month={prev_month:02d}" / "data.parquet"
    if fallback.exists():
        candidates.append(fallback)
    return candidates if candidates else None


def read_last_v4_row(symbol: str) -> dict:
    """Lit la derniere row du parquet V4 pour un symbole.

    Cache TTL 5s.

    Args:
        symbol : "ES" ou "NQ"

    Returns:
        dict avec colonnes V4 (vide si erreur ou parquet absent).
    """
    sym_key = symbol.upper().replace(".C.0", "")
    now_ts = time.time()
    # R3 fix : tout l'acces _cache sous lock pour eviter races multi-thread
    with _cache_lock:
        cached = _cache.get(sym_key)
        if cached is not None:
            cached_ts, cached_row = cached
            if now_ts - cached_ts < _CACHE_TTL_SEC:
                return cached_row

    paths = _v4_path(sym_key)
    if paths is None:
        logger.debug(f"V4 parquet absent pour {sym_key}")
        with _cache_lock:
            _cache[sym_key] = (now_ts, {})
        return {}

    # Iterer mois courant -> mois precedent. Garder la 1ere row valide.
    for path in paths:
        try:
            pf = pq.ParquetFile(str(path))
            n_rows = pf.metadata.num_rows
            if n_rows == 0:
                continue  # R7 : essayer le mois precedent
            last_rg = pf.metadata.num_row_groups - 1
            table = pf.read_row_group(last_rg)
            if table.num_rows == 0:
                continue
            last_idx = table.num_rows - 1
            # 13/05 WORKAROUND (cross-check 2 agents : code-reviewer + quality-auditor) :
            # Pipeline V4 produit parfois des rows JOUR J avec features V4-only=None
            # (engines partiels sur jour incomplet OU trades Databento absents temporairement).
            # Look-back jusqu'a 30 bars (= 30min) pour trouver la derniere row enrichie
            # via canary col `n_big_buy_t1` (proxy V4_ONLY_FEATURES populated).
            # Acceptable car features OFA = signaux d'evenements par-bar non-derivants en 30min.
            # Si toutes les 30 dernieres bars sont None -> retour row actuelle (mode degrade).
            CANARY_COL = "n_big_ask_t1"
            MAX_LOOKBACK = 30
            if CANARY_COL in table.column_names:
                lookback = 0
                while last_idx > 0 and lookback < MAX_LOOKBACK:
                    canary_val = table[CANARY_COL][last_idx].as_py()
                    if canary_val is not None:
                        break  # row enrichie trouvee
                    last_idx -= 1
                    lookback += 1
                if lookback > 0:
                    logger.info(
                        f"V4 look-back {sym_key}: recule {lookback} bars pour trouver row enrichie "
                        f"(jour J non-fully-enriched par pipeline)"
                    )
            row_dict = {col: table[col][last_idx].as_py() for col in table.column_names}
            # Convert numpy/pandas types -> python natifs
            result = {}
            for k, v in row_dict.items():
                if v is None:
                    result[k] = None
                elif hasattr(v, "isoformat"):
                    result[k] = v.isoformat()
                elif hasattr(v, "item"):
                    try:
                        result[k] = v.item()
                    except (ValueError, AttributeError):
                        result[k] = v
                else:
                    result[k] = v
            with _cache_lock:
                _cache[sym_key] = (now_ts, result)
            return result
        except Exception as e:
            # R3 fix : erreur transitoire (rotation fichier pipeline V4).
            # Tente le candidat suivant sans polluer le cache.
            logger.warning(f"V4 read error {sym_key} {path.name}: {e}")
            continue
    # Aucun candidat lisible
    with _cache_lock:
        _cache[sym_key] = (now_ts, {})
    return {}


def merge_dmp_v4(bar_dmp: dict, bar_v4: dict) -> dict:
    """Merge DMP JSONL bar + V4 enriched row (whitelist V4_ONLY_FEATURES).

    SAFETY 04/05 (audit R2) :
      - DMP est SOURCE DE VERITE pour tout ce qui est niveau de prix absolu
        (cur_vpoc, vah/val, vwap_d/w/m, ib_high/low, atr, dist_*, etc.).
      - V4 ne peut ecraser DMP QUE pour les colonnes de la whitelist
        `V4_ONLY_FEATURES` (cluster, big_orders, naked_poc, im_smt, ...).
      - Si V4 stale (mtime > V4_STALE_SEC), merge desactive completement,
        retour DMP brut. Garantit que niveaux du jour ne sont pas remplaces
        par valeurs du vendredi en cas de pipeline lag.

    Args:
        bar_dmp : dict bar JSONL DMP (268 features) — toujours frais.
        bar_v4 : dict row parquet V4 (456 features) — peut etre stale.

    Returns:
        dict merged ou DMP brut si V4 absent/stale.
    """
    if not bar_v4 or not bar_dmp:
        return dict(bar_dmp) if bar_dmp else {}
    # Check staleness V4 vs DMP : si V4 trop vieux, on ne merge rien
    v4_ts = bar_v4.get("ts_event") or bar_v4.get("ts")
    dmp_ts = bar_dmp.get("ts") or bar_dmp.get("ts_event")
    if v4_ts and dmp_ts:
        try:
            v4_dt = datetime.fromisoformat(str(v4_ts).replace("Z", "+00:00")) \
                if isinstance(v4_ts, str) else v4_ts
            dmp_dt = datetime.fromisoformat(str(dmp_ts).replace("Z", "+00:00")) \
                if isinstance(dmp_ts, str) else dmp_ts
            if v4_dt.tzinfo is None:
                v4_dt = v4_dt.replace(tzinfo=timezone.utc)
            if dmp_dt.tzinfo is None:
                dmp_dt = dmp_dt.replace(tzinfo=timezone.utc)
            staleness = (dmp_dt - v4_dt).total_seconds()
            if staleness > _V4_STALE_SEC:
                # 13/05 R4 reviewer : compteur telemetrie skip pour evaluer
                # si bump 2700s suffit en pratique (sans necessite grep logs).
                global _merge_skip_count
                _merge_skip_count += 1
                if _merge_skip_count % _MERGE_SKIP_LOG_EVERY == 0:
                    logger.warning(
                        f"V4 stale skip cumule={_merge_skip_count} "
                        f"(derniere: {staleness:.0f}s > {_V4_STALE_SEC}s) — "
                        f"si compteur croit vite, considerer bump seuil ou fix pipeline lag"
                    )
                else:
                    logger.warning(
                        f"V4 stale ({staleness:.0f}s > {_V4_STALE_SEC}s), merge skipped"
                    )
                return dict(bar_dmp)
        except (ValueError, TypeError, AttributeError):
            pass  # ts non parsable -> fallback whitelist (mode safe)
    # Merge restrictif : seules les V4_ONLY_FEATURES ecrasent DMP
    merged = dict(bar_dmp)
    for k, v in bar_v4.items():
        if v is None:
            continue
        # V4 prioritaire UNIQUEMENT sur la whitelist
        if k in V4_ONLY_FEATURES:
            merged[k] = v
        elif k not in merged:
            # Feature V4 absente du DMP : on l'ajoute (richesse sans overwrite)
            merged[k] = v
    return merged
