"""
mia_menthorq_reader.py — Lecteur de données MenthorQ pour le pipeline ML
=========================================================================

Lit les fichiers JSON MenthorQ (collectés par mia_menthorq_scraper.py)
et produit 41 features ML préfixées mq_* pour enrichir le dataset LightGBM.

Architecture :
  - 27 features daily (constantes pour toutes les barres du jour)
  - 14 features dynamiques (distances recalculées par barre selon le prix)

Formats d'entrée supportés :
  - Format "raw" (depuis mia_menthorq_scraper.py) : YYYYMMDD_menthorq_complete.json
  - Format "manual" (depuis OpenClaw) : YYYYMMDD_ES_menthorq.json

Usage :
    from mia_menthorq_reader import MenthorQReader
    mq = MenthorQReader("DATA/MENTHORQ")
    df = mq.enrich(df, date="20260331", symbol="ES", tick_size=0.25)

Emplacement : D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\mia_menthorq_reader.py
Auteur : MIA Trading System
Date   : 2026-04-01
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


class MenthorQReader:
    """Lecteur et calculateur de features MenthorQ pour le ML."""

    PREFIX = "mq_"

    def __init__(self, base_path: str = "DATA/MENTHORQ"):
        self.base = Path(base_path)

    # ─────────────────────────────────────────────────────────────────
    # CHARGEMENT — supporte les 2 formats
    # ─────────────────────────────────────────────────────────────────

    def _load_json(self, filepath: Path) -> Optional[dict]:
        if not filepath.exists():
            return None
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)

    def load_raw(self, date: str) -> Optional[dict]:
        """Charge le fichier raw complet (scraper)."""
        filepath = self.base / f"{date}_menthorq_complete.json"
        return self._load_json(filepath)

    def load_manual(self, date: str, symbol: str) -> Optional[dict]:
        """Charge le fichier manuel (OpenClaw)."""
        filepath = self.base / f"{date}_{symbol}_menthorq.json"
        return self._load_json(filepath)

    def _parse_number(self, text) -> Optional[float]:
        """Parse un nombre depuis un texte MenthorQ (gere M, B, %, ±)."""
        if text is None:
            return None
        if isinstance(text, (int, float)):
            return float(text)
        text = str(text).strip().replace(",", "").replace(" ", "")
        text = text.replace("±", "").replace("%", "").replace("$", "")
        multiplier = 1.0
        # Pas de conversion d'unité — le champ ML stocke dans l'unité d'origine
        # Les suffixes M/B/T sont juste supprimés, la valeur reste telle quelle
        if text.endswith("M"):
            text = text[:-1]
        elif text.endswith("B"):
            text = text[:-1]
        elif text.endswith("T"):
            text = text[:-1]
        elif text.endswith("K"):
            text = text[:-1]
        try:
            return float(text) * multiplier
        except (ValueError, TypeError):
            return None

    def _gamma_to_int(self, condition) -> float:
        if isinstance(condition, str):
            low = condition.lower()
            if "neg" in low:
                return -1.0
            if "pos" in low:
                return 1.0
        return 0.0

    def _bias_to_int(self, bias) -> float:
        if isinstance(bias, str):
            low = bias.lower()
            if "bear" in low:
                return -1.0
            if "bull" in low:
                return 1.0
        return 0.0

    # ─────────────────────────────────────────────────────────────────
    # PARSING DES DONNÉES BRUTES AJAX
    # ─────────────────────────────────────────────────────────────────

    def _extract_from_raw(self, raw: dict, symbol: str) -> dict:
        """
        Extrait les données structurées depuis le format raw AJAX.

        Priorité :
          1. Données futures (ES1!, NQ1!) pour les niveaux et GEX
          2. Données proxy (SPX, QQQ) pour Q-Scores, Gamma Condition, Swing
          3. Conversion automatique QQQ→NQ (ratio) et SPX→ES (spread)
        """
        out = {
            "q_scores": {},
            "liquidity": {},
            "key_levels": {},
            "gex": {},
            "top_gex_strikes": [],
            "swing": {},
        }

        sym_data = raw.get(symbol, {}).get("raw_ajax", {})
        swing_data = raw.get(f"{symbol}_swing", {}).get("raw_ajax", {})

        # Calculer le ratio/spread de conversion proxy → futures
        # SPX→ES : spread (ES ≈ SPX + 1)
        # QQQ→NQ : ratio (NQ ≈ QQQ × 41)
        self._conversion = self._calc_conversion(raw, symbol, swing_data)

        # ── Key Levels (contient aussi GEX) ──
        kl = self._get_ajax_data(sym_data, "key_levels")
        if kl:
            out["key_levels"] = {
                "Call_Resistance":      kl.get("Call Resistance"),
                "Call_Resistance_0DTE": kl.get("Call Resistance 0DTE"),
                "HVL":                  kl.get("High Vol Level"),
                "Put_Support":          kl.get("Put Support"),
                "Put_Support_0DTE":     kl.get("Put Support 0DTE"),
                "1D_Max":               self._parse_number(kl.get("1D Max.")),
                "1D_Min":               self._parse_number(kl.get("1D Min.")),
                "Distance_to_HVL_Pct":  self._parse_number(kl.get("Distance to HVL %")),
                "Implied_Vol_30D":      self._parse_number(kl.get("Implied Vol 30D")),
            }
            out["gex"] = {
                "Total_GEX_M":     self._parse_number(kl.get("Total GEX")),
                "Net_GEX_M":       self._parse_number(kl.get("Net GEX")),
                "Expiring_GEX_M":  self._parse_number(kl.get("Expiring GEX")),
                "Put_Call_GEX":    self._parse_number(kl.get("Put/Call GEX")),
                "Total_DEX_B":     self._parse_number(kl.get("Total DEX")),
                "Net_DEX_B":       self._parse_number(kl.get("Net DEX")),
                "Put_Call_DEX":    self._parse_number(kl.get("Put/Call DEX")),
            }

        # ── Net GEX (top strikes) ──
        ng = self._get_ajax_data(sym_data, "netgex")
        if ng and "Top Net GEX Strikes" in ng:
            strikes = ng["Top Net GEX Strikes"]
            if isinstance(strikes, list):
                out["top_gex_strikes"] = strikes[:10]

        # ── Liquidity Snapshot (depuis swing/EOD proxy) ──
        liq = self._get_ajax_data(swing_data, "liq_snapshot")
        if liq:
            out["liquidity"] = {
                "P/C_OI":           self._parse_number(liq.get("P/C OI")),
                "1D_Exp_Move_Percent": self._parse_number(liq.get("1D Exp Move %")),
                "Implied_Vol_30D":  self._parse_number(liq.get("Implied Vol 30D")),
                "Momentum":         liq.get("Momentum", ""),
                "IV_Rank":          self._parse_number(liq.get("IV Rank")),
                "HV_30":            self._parse_number(liq.get("Historical Volatility (HV30)")),
                "Vol_Regime":       liq.get("Vol Regime IV/HV", ""),
            }

        # ── Gamma Condition — dériver depuis Net GEX futures (plus fiable que proxy) ──
        # Net GEX > 0 = Positive gamma (stabilisant)
        # Net GEX < 0 = Negative gamma (déstabilisant)
        net_gex = self._parse_number(out["gex"].get("Net_GEX_M"))
        if net_gex is not None and net_gex != 0:
            out["liquidity"]["Gamma_Condition"] = "Positive" if net_gex > 0 else "Negative"
        elif liq:
            # Fallback vers le proxy si Net GEX futures indisponible
            out["liquidity"]["Gamma_Condition"] = liq.get("Gamma Condition", "")

        # ── Q-Scores — tentative depuis AJAX (souvent images) ──
        for qs in ["qscore_option", "qscore_momentum", "qscore_volatility", "qscore_seasonality"]:
            qs_data = self._get_ajax_data(sym_data, qs)
            if qs_data and isinstance(qs_data, dict):
                for key in ["value", "score", "q_score"]:
                    if key in qs_data:
                        name = qs.replace("qscore_", "")
                        out["q_scores"][name.capitalize()] = qs_data[key]
                        break

        # Fallback Q-Score Momentum depuis liq_snapshot
        if "Momentum" not in out["q_scores"] and liq:
            momentum_text = liq.get("Momentum", "")
            if momentum_text:
                momentum_map = {"bearish": 1, "neutral": 2, "bullish": 4}
                out["q_scores"]["Momentum"] = momentum_map.get(
                    momentum_text.lower().split()[0], 2)

        # ── Swing Models (souvent images — extraire si données texte dispo) ──
        # Les Swing Models sont en proxy (SPX pour ES, QQQ pour NQ)
        # Les niveaux de prix doivent être convertis vers le futures
        for period in ["5d", "20d"]:
            sw = self._get_ajax_data(swing_data, f"swing_{period}")
            if sw and isinstance(sw, dict):
                raw_upper = sw.get("Upper Band") or sw.get("upper_band")
                raw_trigger = sw.get("Risk Trigger") or sw.get("risk_trigger")
                out["swing"][period] = {
                    "upper_band":   self._convert_proxy_level(raw_upper, symbol),
                    "risk_trigger": self._convert_proxy_level(raw_trigger, symbol),
                    "bias":         sw.get("Bias") or sw.get("bias", ""),
                    "success_rate": self._parse_number(sw.get("Success Rate") or sw.get("success_rate")),
                }

        # Fallback Swing bias depuis liq_snapshot Momentum
        if not out["swing"] and liq:
            momentum_text = liq.get("Momentum", "")
            if "bear" in momentum_text.lower():
                out["swing"]["5d"] = {"bias": "BEARISH"}
                out["swing"]["20d"] = {"bias": "BEARISH"}
            elif "bull" in momentum_text.lower():
                out["swing"]["5d"] = {"bias": "BULLISH"}
                out["swing"]["20d"] = {"bias": "BULLISH"}

        return out

    def _get_ajax_data(self, raw_ajax: dict, slug: str) -> Optional[dict]:
        """Extrait les données d'un slug AJAX."""
        resp = raw_ajax.get(slug, {})
        if isinstance(resp, dict) and resp.get("success"):
            resource = resp.get("data", {}).get("resource", {})
            return resource.get("data", {})
        return None

    def _calc_conversion(self, raw: dict, symbol: str, swing_data: dict) -> dict:
        """
        Calcule le ratio/spread de conversion proxy → futures.

        SPX→ES : spread = ES_price - SPX_price (typiquement +1 à +5)
        QQQ→NQ : ratio = NQ_price / QQQ_price (typiquement ~41)
        """
        conv = {"method": "none", "value": 0}

        # Prix futures depuis key_levels
        futures_kl = self._get_ajax_data(
            raw.get(symbol, {}).get("raw_ajax", {}), "key_levels")
        # Prix proxy depuis liq_snapshot
        proxy_liq = self._get_ajax_data(swing_data, "liq_snapshot")

        if not futures_kl or not proxy_liq:
            return conv

        # HVL est le meilleur point de référence (identique conceptuellement)
        futures_hvl = self._parse_number(futures_kl.get("High Vol Level"))
        proxy_price = self._parse_number(proxy_liq.get("Last Price"))

        if not futures_hvl or not proxy_price or proxy_price <= 0:
            return conv

        if symbol == "ES":
            # SPX ≈ ES : spread method (écart typique 0-10 pts)
            conv["method"] = "spread"
            conv["value"] = futures_hvl - self._parse_number(
                self._get_ajax_data(swing_data, "key_levels").get("High Vol Level", 0)
                if self._get_ajax_data(swing_data, "key_levels") else 0)
            if conv["value"] is None or abs(conv["value"]) > 50:
                conv["value"] = 0  # Fallback si écart aberrant
        elif symbol == "NQ":
            # QQQ → NQ : ratio method
            conv["method"] = "ratio"
            conv["value"] = futures_hvl / proxy_price if proxy_price > 10 else 0

        return conv

    def _convert_proxy_level(self, proxy_level, symbol: str) -> Optional[float]:
        """Convertit un niveau proxy vers le niveau futures."""
        level = self._parse_number(proxy_level)
        if level is None or not _valid(level):
            return None

        conv = getattr(self, "_conversion", {"method": "none", "value": 0})

        if conv["method"] == "spread" and conv["value"] is not None:
            return level + conv["value"]
        elif conv["method"] == "ratio" and conv["value"] and conv["value"] > 0:
            return level * conv["value"]
        return level

    # ─────────────────────────────────────────────────────────────────
    # FEATURES DAILY (27)
    # ─────────────────────────────────────────────────────────────────

    def compute_daily_features(self, parsed: dict, cross_parsed: dict = None) -> dict:
        """Calcule les 27 features daily depuis les données parsées."""
        if not parsed:
            return {}

        f = {}
        qs = parsed.get("q_scores", {})
        liq = parsed.get("liquidity", {})
        kl = parsed.get("key_levels", {})
        gex = parsed.get("gex", {})
        strikes = parsed.get("top_gex_strikes", [])
        swing = parsed.get("swing", {})

        # ── Cat 1 : Q-Scores (4) ──
        f["mq_qscore_option"]      = _to_float(qs.get("Option"))
        f["mq_qscore_volatility"]  = _to_float(qs.get("Volatility"))
        f["mq_qscore_momentum"]    = _to_float(qs.get("Momentum"))
        f["mq_qscore_seasonality"] = _to_float(qs.get("Seasonality"))

        # ── Cat 2 : Gamma / Delta (8) ──
        f["mq_gamma_condition"]    = self._gamma_to_int(liq.get("Gamma_Condition", ""))
        net_gex = _to_float(gex.get("Net_GEX_M"))
        total_gex = _to_float(gex.get("Total_GEX_M"))
        expiring = _to_float(gex.get("Expiring_GEX_M"))

        f["mq_net_gex_m"]   = net_gex
        f["mq_total_gex_m"] = total_gex
        f["mq_net_dex_b"]   = _to_float(gex.get("Net_DEX_B"))
        f["mq_pc_gex"]      = _to_float(gex.get("Put_Call_GEX"))
        f["mq_pc_dex"]      = _to_float(gex.get("Put_Call_DEX"))

        if _valid(net_gex) and _valid(total_gex) and total_gex != 0:
            f["mq_net_gex_ratio"] = net_gex / total_gex
        else:
            f["mq_net_gex_ratio"] = np.nan

        if _valid(expiring) and _valid(total_gex) and total_gex != 0:
            f["mq_expiring_gex_pct"] = expiring / total_gex * 100
        else:
            f["mq_expiring_gex_pct"] = np.nan

        # ── Cat 3 : Ratios Options (5) ──
        f["mq_pc_oi"]        = _to_float(liq.get("P/C_OI"))
        f["mq_iv_30d"]       = _to_float(liq.get("Implied_Vol_30D") or kl.get("Implied_Vol_30D"))
        f["mq_exp_move_pct"] = _to_float(liq.get("1D_Exp_Move_Percent"))
        f["mq_iv_rank"]      = _to_float(liq.get("IV_Rank"))
        f["mq_hv_30d"]       = _to_float(liq.get("HV_30"))

        # ── Cat 5 : GEX Structure (3) ──
        if strikes and isinstance(strikes, list):
            f["mq_top_gex_strike_1"] = _to_float(strikes[0]) if len(strikes) > 0 else np.nan
            f["mq_n_gex_strikes"]    = float(len(strikes))
        else:
            f["mq_top_gex_strike_1"] = np.nan
            f["mq_n_gex_strikes"]    = np.nan

        # ── Cat 6 : Swing bias (2) ──
        sw5 = swing.get("5d", {})
        sw20 = swing.get("20d", {})
        f["mq_swing_5d_bias"]  = self._bias_to_int(sw5.get("bias", ""))
        f["mq_swing_20d_bias"] = self._bias_to_int(sw20.get("bias", ""))

        # ── Cat 7 : Cross-Asset Divergence (3) ──
        if cross_parsed:
            my_gamma = f.get("mq_gamma_condition", 0)
            other_gamma = self._gamma_to_int(
                cross_parsed.get("liquidity", {}).get("Gamma_Condition", ""))
            f["mq_es_nq_gamma_div"] = my_gamma - other_gamma

            other_gex = _to_float(cross_parsed.get("gex", {}).get("Net_GEX_M"))
            # FIX 13/04/2026 : normalized difference (ES + NQ = 0 garanti) au lieu
            # du ratio simple my/other qui donnait ES * NQ = 1 (pas de dualite).
            # Formule : (my - other) / (|my| + |other|)
            #   ES val : (gex_ES - gex_NQ) / (|gex_ES| + |gex_NQ|)
            #   NQ val : (gex_NQ - gex_ES) / (|gex_NQ| + |gex_ES|) = -ES val
            # Proprietes : borne [-1, 1], symetrique, robuste aux zeros.
            # Audit V2 regle miroir ES/NQ (feedback_es_nq_mirror.md).
            denom = abs(net_gex) + abs(other_gex) if _valid(net_gex) and _valid(other_gex) else 0.0
            if _valid(net_gex) and _valid(other_gex) and denom > 1e-6:
                f["mq_es_nq_gex_ratio"] = (net_gex - other_gex) / denom
            else:
                f["mq_es_nq_gex_ratio"] = np.nan

            my_iv = f.get("mq_iv_30d", np.nan)
            other_iv = _to_float(cross_parsed.get("liquidity", {}).get("Implied_Vol_30D")
                                 or cross_parsed.get("key_levels", {}).get("Implied_Vol_30D"))
            if _valid(my_iv) and _valid(other_iv):
                f["mq_es_nq_iv_spread"] = other_iv - my_iv
            else:
                f["mq_es_nq_iv_spread"] = np.nan
        else:
            f["mq_es_nq_gamma_div"] = np.nan
            f["mq_es_nq_gex_ratio"] = np.nan
            f["mq_es_nq_iv_spread"] = np.nan

        return f

    # ─────────────────────────────────────────────────────────────────
    # FEATURES DYNAMIQUES (14 distances recalculées par barre)
    # ─────────────────────────────────────────────────────────────────

    def compute_dynamic_features(self, price: float, parsed: dict,
                                  tick_size: float = 0.25) -> dict:
        """Calcule les 14 features dynamiques pour une barre."""
        if not parsed or not _valid(price):
            return {}

        f = {}
        ts = tick_size
        kl = parsed.get("key_levels", {})
        swing = parsed.get("swing", {})

        # ── Distances niveaux clés (8) ──
        levels = {
            "mq_dist_call_res":   kl.get("Call_Resistance"),
            "mq_dist_put_sup":    kl.get("Put_Support"),
            "mq_dist_hvl":        kl.get("HVL"),
            "mq_dist_call_0dte":  kl.get("Call_Resistance_0DTE"),
            "mq_dist_put_0dte":   kl.get("Put_Support_0DTE"),
            "mq_dist_1d_max":     kl.get("1D_Max"),
            "mq_dist_1d_min":     kl.get("1D_Min"),
        }
        for key, level in levels.items():
            level = _to_float(level)
            if _valid(level) and level > 100:
                f[key] = (level - price) / ts
            else:
                f[key] = np.nan

        hvl = _to_float(kl.get("HVL"))
        if _valid(hvl) and hvl > 100:
            f["mq_hvl_distance_pct"] = abs(price - hvl) / price * 100
        else:
            f["mq_hvl_distance_pct"] = np.nan

        # ── Distances Swing (4) ──
        for period in ["5d", "20d"]:
            sw = swing.get(period, {})
            upper = _to_float(sw.get("upper_band"))
            trigger = _to_float(sw.get("risk_trigger"))

            if _valid(upper) and upper > 100:
                f[f"mq_dist_swing_{period}_upper"] = (upper - price) / ts
            else:
                f[f"mq_dist_swing_{period}_upper"] = np.nan

            if _valid(trigger) and trigger > 100:
                f[f"mq_dist_swing_{period}_trigger"] = (trigger - price) / ts
            else:
                f[f"mq_dist_swing_{period}_trigger"] = np.nan

        # ── Gamma Flip (1) ──
        f["mq_dist_gamma_flip"] = np.nan  # disponible seulement si top_gex_strikes analysés

        return f

    # ─────────────────────────────────────────────────────────────────
    # ENRICHISSEMENT DATAFRAME
    # ─────────────────────────────────────────────────────────────────

    def enrich(self, df: pd.DataFrame, date: str, symbol: str,
               tick_size: float = 0.25) -> pd.DataFrame:
        """
        Enrichit un DataFrame DMP avec les features MenthorQ.

        Tente d'abord le format raw (scraper), puis le format manuel (OpenClaw).
        """
        df = df.copy()

        # Charger et parser les données
        parsed = None
        cross_parsed = None
        other_sym = "NQ" if symbol == "ES" else "ES"

        # Format 1 : raw scraper (prioritaire)
        raw = self.load_raw(date)
        if raw:
            if symbol in raw:
                parsed = self._extract_from_raw(raw, symbol)
            if other_sym in raw:
                cross_parsed = self._extract_from_raw(raw, other_sym)

        # Format 2 : fichier manuel (fallback)
        if parsed is None:
            manual = self.load_manual(date, symbol)
            if manual:
                parsed = manual  # Déjà structuré
                other_manual = self.load_manual(date, other_sym)
                if other_manual:
                    cross_parsed = other_manual

        if parsed is None:
            return df

        # Features daily (broadcast)
        daily = self.compute_daily_features(parsed, cross_parsed)
        for key, value in daily.items():
            df[key] = value

        # Features dynamiques (par barre)
        if "price" in df.columns:
            prices = df["price"].values
            dyn_results = {key: np.full(len(df), np.nan) for key in self.FEATURES_DYNAMIC}

            for i, price in enumerate(prices):
                dyn = self.compute_dynamic_features(float(price), parsed, tick_size)
                for key, value in dyn.items():
                    if key in dyn_results:
                        dyn_results[key][i] = value

            for key, values in dyn_results.items():
                df[key] = values

        n_features = sum(1 for c in df.columns if c.startswith("mq_"))
        n_valid = sum(1 for c in df.columns
                      if c.startswith("mq_") and df[c].notna().any())
        print(f"  [MenthorQ] {symbol} {date}: +{n_features} features ({n_valid} valides)")

        return df

    # ─────────────────────────────────────────────────────────────────
    # PROPRIÉTÉS
    # ─────────────────────────────────────────────────────────────────

    @property
    def FEATURES_DAILY(self) -> list:
        return [
            "mq_qscore_option", "mq_qscore_volatility",
            "mq_qscore_momentum", "mq_qscore_seasonality",
            "mq_gamma_condition", "mq_net_gex_m", "mq_total_gex_m",
            "mq_net_gex_ratio", "mq_expiring_gex_pct",
            "mq_net_dex_b", "mq_pc_gex", "mq_pc_dex",
            "mq_pc_oi", "mq_iv_30d", "mq_exp_move_pct",
            "mq_iv_rank", "mq_hv_30d",
            "mq_top_gex_strike_1", "mq_n_gex_strikes",
            "mq_swing_5d_bias", "mq_swing_20d_bias",
            "mq_es_nq_gamma_div", "mq_es_nq_gex_ratio", "mq_es_nq_iv_spread",
        ]

    @property
    def FEATURES_DYNAMIC(self) -> list:
        return [
            "mq_dist_call_res", "mq_dist_put_sup", "mq_dist_hvl",
            "mq_dist_call_0dte", "mq_dist_put_0dte",
            "mq_dist_1d_max", "mq_dist_1d_min", "mq_hvl_distance_pct",
            "mq_dist_swing_5d_upper", "mq_dist_swing_5d_trigger",
            "mq_dist_swing_20d_upper", "mq_dist_swing_20d_trigger",
            "mq_dist_gamma_flip",
        ]

    @property
    def FEATURES(self) -> list:
        return self.FEATURES_DAILY + self.FEATURES_DYNAMIC


# ─────────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────────

def _to_float(v) -> float:
    if v is None:
        return np.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan

def _valid(v) -> bool:
    if v is None:
        return False
    try:
        return np.isfinite(float(v))
    except (TypeError, ValueError):
        return False


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else "DATA/MENTHORQ"
    mq = MenthorQReader(base)

    test_df = pd.DataFrame({
        "price": [6530.0, 6535.0, 6520.0, 6540.0, 6525.0],
        "delta_bar": [10, -5, 20, -15, 8],
    })

    for sym in ["ES", "NQ"]:
        print(f"\n{'='*50}")
        enriched = mq.enrich(test_df.copy(), "20260331", sym, tick_size=0.25)
        mq_cols = sorted([c for c in enriched.columns if c.startswith("mq_")])
        for c in mq_cols:
            v = enriched[c].iloc[0]
            if not np.isnan(v) if isinstance(v, float) else True:
                print(f"  {c:35s} = {v}")
