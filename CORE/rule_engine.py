"""
rule_engine.py — Moteur de regles MIA V2
==========================================

Regles basees sur l'analyse des donnees DMP (02/04/2026, 3 jours, ES+NQ).
Chaque regle a ete validee statistiquement (p < 0.05) ET par logique marche.

Architecture :
  1. Chaque regle produit un score [-1, +1] (sell, buy)
  2. Les scores sont ponderes par la confiance de la regle
  3. Filtres qualite (chemin libre, mur protecteur) ajustent le score
  4. Signal final : BUY si score > seuil, SELL si score < -seuil

Utilisation :
  engine = RuleEngine()
  signal = engine.evaluate(row)  # row = dict ou Series (1 barre DMP)

Auteur : MIA Trading System
Date   : 2026-04-02
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Seuils de decision
SIGNAL_THRESHOLD = 0.35      # Score minimum pour generer un signal (etait 0.30)
MIN_RULES_ALIGNED = 2        # Minimum de regles alignees pour un signal
COOLDOWN_BARS = 10           # Barres minimum entre 2 signaux (10 min)
MAX_SIGNALS_PER_DAY = 10     # Max signaux par jour par instrument
TICK_SIZE = 0.25


@dataclass
class RuleSignal:
    """Resultat de l'evaluation des regles."""
    direction: int = 0          # +1=BUY, -1=SELL, 0=HOLD
    score: float = 0.0          # Score total [-1, +1]
    confidence: str = "NONE"    # HIGH, MEDIUM, LOW, NONE
    n_rules_buy: int = 0        # Nombre de regles BUY actives
    n_rules_sell: int = 0       # Nombre de regles SELL actives
    rules_fired: list = field(default_factory=list)  # Noms des regles actives
    sl_ticks: float = 20.0      # SL suggere
    tp_ticks: float = 20.0      # TP suggere
    quality_filters: list = field(default_factory=list)  # Filtres qualite actifs


def _get(row, col, default=0.0):
    """Recupere une valeur de la barre, avec fallback."""
    try:
        v = row.get(col, default) if isinstance(row, dict) else row.get(col, default)
        if v is None or (isinstance(v, float) and v != v):  # NaN check
            return default
        return float(v)
    except Exception:
        return default


def _get_nullable(row, col):
    """Recupere une valeur numerique ou None (pour features avec sentinel null).

    Contrairement a _get(), ne retourne PAS 0.0 par defaut. Retourne None si
    la valeur est None, NaN, ou absente. A utiliser pour les features ou 0 serait
    ambigu avec 'hors range' (ex: va_position_pct, ib_position_pct post fix
    DMP_Transform.h 2026-04-16 qui ecrit null au lieu du sentinel -1).
    """
    try:
        v = row.get(col, None) if isinstance(row, dict) else row.get(col, None)
        if v is None:
            return None
        if isinstance(v, float) and v != v:  # NaN
            return None
        return float(v)
    except Exception:
        return None


class RuleEngine:
    """Moteur de regles base sur les niveaux previous, options et order flow."""

    def __init__(self, min_score: float = SIGNAL_THRESHOLD,
                 min_rules: int = MIN_RULES_ALIGNED,
                 cooldown_bars: int = COOLDOWN_BARS,
                 max_signals_day: int = MAX_SIGNALS_PER_DAY):
        self.min_score = min_score
        self.min_rules = min_rules
        self.cooldown_bars = cooldown_bars
        self.max_signals_day = max_signals_day

        # Etat par symbole
        self._last_signal_bar: Dict[str, int] = {}    # {symbol: bar_index}
        self._last_signal_dir: Dict[str, int] = {}    # {symbol: direction}
        self._bar_counter: Dict[str, int] = {}         # {symbol: compteur barres}
        self._daily_signals: Dict[str, int] = {}       # {symbol: nb signaux aujourd'hui}
        self._current_date: str = ""

    def evaluate(self, row, symbol: str = "") -> RuleSignal:
        """
        Evalue toutes les regles sur une barre DMP.

        Args:
            row: dict ou pandas Series avec les 262 colonnes DMP
            symbol: "ES" ou "NQ" (pour cooldown par instrument)

        Returns:
            RuleSignal avec direction, score, regles actives
        """
        signal = RuleSignal()
        buy_score = 0.0
        sell_score = 0.0

        # Incrementer le compteur de barres
        sym = symbol or str(_get(row, "sym", ""))
        self._bar_counter[sym] = self._bar_counter.get(sym, 0) + 1

        # Reset daily si nouveau jour
        date_str = str(_get(row, "date", ""))
        if date_str and date_str != self._current_date:
            self._current_date = date_str
            self._daily_signals = {}
            self._last_signal_bar = {}
            self._last_signal_dir = {}

        # ═══════════════════════════════════════════════════════
        # TIER 1 — Previous Levels (DIRECTIONNEL)
        # Le prix arrive SUR un niveau → on trade le REBOND
        # FIX BUG D 15/05/2026 : convention DMP unique (level - close) compliant
        # CalcDistTicks(level, price) = (level - price) / tick.
        # dist > 0 = niveau AU-DESSUS du prix → prix sous le niveau → monte vers → SELL (rejet)
        # dist < 0 = niveau EN-DESSOUS du prix → prix au-dessus → descend vers → BUY (rebond)
        # ═══════════════════════════════════════════════════════

        # R1: prev_VPOC — aimant, rebond dans la direction d'approche
        dist_raw = _get(row, "dist_prev_vpoc")
        dist_abs = abs(dist_raw)
        if 0 < dist_abs < 12:
            weight = 0.25 if dist_abs < 5 else 0.15
            if dist_raw < 0:  # VPOC sous le prix = prix au-dessus, descend vers → BUY
                buy_score += weight
                signal.rules_fired.append(f"prev_VPOC({dist_raw:+.0f}t)→BUY_rebond")
            else:  # VPOC au-dessus du prix = prix en-dessous, monte vers → SELL
                sell_score += weight
                signal.rules_fired.append(f"prev_VPOC({dist_raw:+.0f}t)→SELL_rejet")

        # R2: prev_VWAP — meme logique
        dist_raw = _get(row, "dist_prev_vwap")
        dist_abs = abs(dist_raw)
        if 0 < dist_abs < 12:
            weight = 0.25 if dist_abs < 5 else 0.15
            if dist_raw < 0:  # VWAP sous le prix → BUY rebond
                buy_score += weight
                signal.rules_fired.append(f"prev_VWAP({dist_raw:+.0f}t)→BUY_rebond")
            else:
                sell_score += weight
                signal.rules_fired.append(f"prev_VWAP({dist_raw:+.0f}t)→SELL_rejet")

        # R3: prev_VWAP_SD1d — bande BASSE = mean reversion BUY
        # dist > 0 = SD1d AU-DESSUS du prix = prix EN-DESSOUS du SD1d = survendu = BUY
        # dist < 0 = SD1d en-dessous = zone normale, pas de signal
        dist_raw = _get(row, "dist_prev_vwap_sd1d")
        if dist_raw > 0 and abs(dist_raw) < 12:
            weight = 0.25 if abs(dist_raw) < 5 else 0.15
            buy_score += weight
            signal.rules_fired.append(f"prev_SD1d({dist_raw:+.0f}t)→BUY_survendu")

        # R4: prev_VWAP_SD1u — bande HAUTE = mean reversion SELL
        # dist < 0 = SD1u SOUS le prix = prix AU-DESSUS du SD1u = surachete = SELL
        # dist > 0 = SD1u au-dessus = zone normale, pas de signal
        dist_raw = _get(row, "dist_prev_vwap_sd1u")
        if dist_raw < 0 and abs(dist_raw) < 12:
            weight = 0.20 if abs(dist_raw) < 5 else 0.12
            sell_score += weight
            signal.rules_fired.append(f"prev_SD1u({dist_raw:+.0f}t)→SELL_surachete")

        # R5: prev_VAL — support, rebond BUY
        dist_raw = _get(row, "dist_prev_val")
        dist_abs = abs(dist_raw)
        if 0 < dist_abs < 12:
            if dist_raw < 0:  # VAL sous le prix = prix au-dessus, descend vers → BUY rebond
                buy_score += 0.12
                signal.rules_fired.append(f"prev_VAL({dist_raw:+.0f}t)→BUY_support")
            else:  # VAL au-dessus = prix en-dessous → SELL breakdown
                sell_score += 0.08
                signal.rules_fired.append(f"prev_VAL({dist_raw:+.0f}t)→SELL_break")

        # R5b: prev_VAH — resistance, rejet SELL
        dist_raw = _get(row, "dist_prev_vah")
        dist_abs = abs(dist_raw)
        if 0 < dist_abs < 12:
            if dist_raw > 0:  # VAH au-dessus du prix = prix en-dessous, monte vers → SELL rejet
                sell_score += 0.12
                signal.rules_fired.append(f"prev_VAH({dist_raw:+.0f}t)→SELL_resist")
            else:  # VAH sous le prix = prix au-dessus → BUY breakout
                buy_score += 0.08
                signal.rules_fired.append(f"prev_VAH({dist_raw:+.0f}t)→BUY_break")

        # ═══════════════════════════════════════════════════════
        # TIER 1 — Options (Call 0DTE, Put 0DTE, HVL)
        # ═══════════════════════════════════════════════════════

        # R6: MQ Call 0DTE — resistance, prix monte vers → SELL
        dist_raw = _get(row, "dist_mq_call_0dte")
        dist_abs = abs(dist_raw)
        if 0 < dist_abs < 15:
            weight = 0.20 if dist_abs < 8 else 0.12
            if dist_raw > 0:  # Call au-dessus du prix = prix en-dessous, monte vers → SELL
                sell_score += weight
                signal.rules_fired.append(f"Call_0DTE({dist_raw:+.0f}t)→SELL_resist")
            else:  # Call sous le prix = prix au-dessus → breakout rare
                buy_score += weight * 0.3
                signal.rules_fired.append(f"Call_0DTE({dist_raw:+.0f}t)→BUY_break")

        # R7: MQ Put 0DTE — support, prix descend vers → BUY
        dist_raw = _get(row, "dist_mq_put_0dte")
        dist_abs = abs(dist_raw)
        if 0 < dist_abs < 20:
            weight = 0.20 if dist_abs < 10 else 0.12
            if dist_raw < 0:  # Put sous le prix = prix au-dessus, descend vers → BUY
                buy_score += weight
                signal.rules_fired.append(f"Put_0DTE({dist_raw:+.0f}t)→BUY_support")
            else:  # Put au-dessus = prix en-dessous → SELL breakdown
                sell_score += weight * 0.5
                signal.rules_fired.append(f"Put_0DTE({dist_raw:+.0f}t)→SELL_break")

        # R8: MQ HVL — aimant/resistance
        dist_raw = _get(row, "dist_mq_hvl")
        dist_abs = abs(dist_raw)
        if 0 < dist_abs < 20:
            weight = 0.12
            if dist_raw < 0:  # HVL sous le prix = prix au-dessus, descend vers → attraction
                buy_score += weight * 0.5
                signal.rules_fired.append(f"MQ_HVL({dist_raw:+.0f}t)→aimant")
            else:  # HVL au-dessus = prix en-dessous, monte vers → SELL resistance
                sell_score += weight
                signal.rules_fired.append(f"MQ_HVL({dist_raw:+.0f}t)→SELL_resist")

        # R9: Composite VPOC 20d/50d < 15t — directionnel (meme logique rebond)
        for col in ["dist_comp_20d_vpoc", "dist_comp_50d_vpoc"]:
            dist_raw = _get(row, col)
            dist_abs = abs(dist_raw)
            if 0 < dist_abs < 15:
                if dist_raw < 0:  # comp_vpoc sous le prix → BUY rebond
                    buy_score += 0.10
                    signal.rules_fired.append(f"{col}({dist_raw:+.0f}t)→BUY")
                else:  # comp_vpoc au-dessus → SELL rejet
                    sell_score += 0.10
                    signal.rules_fired.append(f"{col}({dist_raw:+.0f}t)→SELL")
                break

        # ═══════════════════════════════════════════════════════
        # TIER 2 — Divergences et Dow Theory
        # ═══════════════════════════════════════════════════════

        # R10: VWAP slope positive + prix baisse → BUY (ES 62% WR, n=360, p=0.001)
        price_diff = _get(row, "price_diff_10", 0)
        vwap_slope = _get(row, "vwap_slope_10")
        if vwap_slope > 0.5 and price_diff < -2:
            buy_score += 0.12
            signal.rules_fired.append("div_VWAP_slope+_prix-→BUY")
        elif vwap_slope < -0.5 and price_diff > 2:
            sell_score += 0.08
            signal.rules_fired.append("div_VWAP_slope-_prix+→SELL")

        # R11: VA position extreme — SEULEMENT si le trend confirme
        # FIX 2026-04-16 : va_position_pct est null hors VA (pas -1 comme avant).
        # On utilise _get_nullable pour ne PAS fallback a 0.0 qui ferait fire faux BUY
        # sur toute barre hors VA. Ancienne logique va_pos < 0 devient va_pos is None.
        va_pos = _get_nullable(row, "va_position_pct")
        vwap_sl_r11 = _get(row, "vwap_slope_10")
        if va_pos is None:
            # Hors VA -> pas de signal R11
            pass
        elif va_pos > 0.80:
            sell_score += 0.10
            signal.rules_fired.append(f"VA_haute({va_pos:.0%})→SELL")
        elif va_pos < 0.20:
            # VA basse = BUY seulement si le VWAP ne descend pas (sinon breakdown)
            if vwap_sl_r11 >= -0.1:
                buy_score += 0.08
                signal.rules_fired.append(f"VA_basse({va_pos:.0%})→BUY")
            else:
                signal.rules_fired.append(f"VA_basse_SKIP(slope={vwap_sl_r11:.1f})")

        # R12: new_swing_high → BUY (NQ 64% WR, p=0.036)
        if _get(row, "new_swing_high") == 1:
            buy_score += 0.10
            signal.rules_fired.append("new_swing_high→BUY")

        # R13: Double top + delta divergence → SELL (NQ 65% WR)
        if _get(row, "retest_high_count") >= 2 and _get(row, "retest_high_delta_div") == 1:
            sell_score += 0.15
            signal.rules_fired.append("double_top+delta_div→SELL")

        # R14: Double bottom + delta divergence → BUY
        if _get(row, "retest_low_count") >= 2 and _get(row, "retest_low_delta_div") == 1:
            buy_score += 0.12
            signal.rules_fired.append("double_bottom+delta_div→BUY")

        # R15: VIX Call 0DTE au-dessus → BUY (ES 66% WR, n=547, p=0.000)
        # FIX BUG D 15/05/2026 : convention NEW (level - close). Call AU-DESSUS
        # du VIX prix = dist_vix_call > 0 (anciennement dist < 0 sous OLD conv).
        dist_vix_call = _get(row, "dist_vix_call_0dte")
        if 3 < dist_vix_call < 20:
            buy_score += 0.08
            signal.rules_fired.append("VIX_Call_0DTE_above→BUY")

        # R16: VIX Put 0DTE en-dessous → SELL (ES 65% WR, n=162, p=0.000)
        # FIX BUG D 15/05/2026 : Put EN-DESSOUS du VIX prix = dist_vix_put < 0.
        dist_vix_put = _get(row, "dist_vix_put_0dte")
        if -20 < dist_vix_put < -3:
            sell_score += 0.10
            signal.rules_fired.append("VIX_Put_0DTE_below→SELL")

        # ═══════════════════════════════════════════════════════
        # FILTRE MOMENTUM GLOBAL — Bloque les trades contra-trend
        # Un trader pro ne prend JAMAIS un BUY quand tout descend
        # ═══════════════════════════════════════════════════════

        vwap_sl = _get(row, "vwap_slope_10")
        delta_d = _get(row, "delta_day")
        cvd_dir = _get(row, "cvd_day_dir")

        # BUY bloque si momentum FORTEMENT baissier (les 2 conditions ensemble)
        if buy_score > 0 and vwap_sl < -0.3 and delta_d < -10000:
            buy_score *= 0.0  # KILL le BUY
            signal.rules_fired.append(f"BLOQUE_momentum_bear(slope={vwap_sl:.1f},delta={delta_d:.0f})")

        # SELL bloque si momentum FORTEMENT haussier
        if sell_score > 0 and vwap_sl > 0.3 and delta_d > 10000:
            sell_score *= 0.0
            signal.rules_fired.append(f"BLOQUE_momentum_bull(slope={vwap_sl:.1f},delta={delta_d:.0f})")

        # Sauvegarder le score brut avant confirmations (pour plafonner)
        buy_score_raw = buy_score
        sell_score_raw = sell_score

        # ═══════════════════════════════════════════════════════
        # CONFIRMATIONS — Doivent etre EN FAVEUR du trade
        # BN Color, Edge Zone, Absorption, Delta
        # ═══════════════════════════════════════════════════════

        # C1: BN Color — la barre doit etre dans la direction du trade
        # Si UP et DN sont les deux a 1 → signal contradictoire → NEUTRE
        bn_color_up = _get(row, "bn_color_up_2")
        bn_color_dn = _get(row, "bn_color_dn_2")
        bar_color_up = _get(row, "bar_color_up")
        bar_color_dn = _get(row, "bar_color_dn")
        bn_contradictoire = (bn_color_up > 0 and bn_color_dn > 0)

        if not bn_contradictoire:
            if buy_score > 0:
                if bn_color_up > 0 or bar_color_up > 0:
                    buy_score *= 1.15
                    signal.rules_fired.append("BN_color_UP_confirm")
                elif bn_color_dn > 0:
                    buy_score *= 0.60  # PENALITE forte — color contra BUY
                    signal.rules_fired.append("BN_color_DN_CONTRA")

            if sell_score > 0:
                if bn_color_dn > 0 or bar_color_dn > 0:
                    sell_score *= 1.15
                    signal.rules_fired.append("BN_color_DN_confirm")
                elif bn_color_up > 0:
                    sell_score *= 0.60
                    signal.rules_fired.append("BN_color_UP_CONTRA")
        else:
            signal.rules_fired.append("BN_color_NEUTRE(up+dn=1)")

        # C2: Edge Zone — imbalance forte, doit favoriser le trade
        fp_edge_buy = _get(row, "fp_edge_buy")
        fp_edge_sell = _get(row, "fp_edge_sell")
        bar_edge_buy = _get(row, "bar_edge_buy")
        bar_edge_sell = _get(row, "bar_edge_sell")

        if buy_score > 0 and (fp_edge_buy > 0 or bar_edge_buy > 0):
            buy_score *= 1.20
            signal.rules_fired.append("EDGE_BUY_confirm")
        if sell_score > 0 and (fp_edge_sell > 0 or bar_edge_sell > 0):
            sell_score *= 1.20
            signal.rules_fired.append("EDGE_SELL_confirm")

        # Penalite si edge zone CONTRA
        if buy_score > 0 and fp_edge_sell > 0 and fp_edge_buy == 0:
            buy_score *= 0.75
            signal.rules_fired.append("EDGE_SELL_CONTRA")
        if sell_score > 0 and fp_edge_buy > 0 and fp_edge_sell == 0:
            sell_score *= 0.75
            signal.rules_fired.append("EDGE_BUY_CONTRA")

        # C3: Absorption — vendeurs absorbes = BUY, acheteurs absorbes = SELL
        # bn_absorb_ask = vendeurs agressifs bloques par acheteurs passifs → BUY
        # bn_absorb_bid = acheteurs agressifs bloques par vendeurs passifs → SELL
        if _get(row, "bn_absorb_ask") > 0 and buy_score > 0:
            buy_score *= 1.15
            signal.rules_fired.append("absorb_ask→BUY_confirm")
        if _get(row, "bn_absorb_bid") > 0 and sell_score > 0:
            sell_score *= 1.15
            signal.rules_fired.append("absorb_bid→SELL_confirm")

        # C4: BN score global
        bn_raw = _get(row, "bn_score_raw")
        if bn_raw > 0 and buy_score > 0:
            buy_score *= 1.10
            signal.rules_fired.append("bn_score+_confirm")
        elif bn_raw < 0 and sell_score > 0:
            sell_score *= 1.10
            signal.rules_fired.append("bn_score-_confirm")

        # C5: Delta bar confirme
        delta = _get(row, "delta_bar")
        if delta > 30 and buy_score > 0:
            buy_score *= 1.08
            signal.rules_fired.append("delta+_confirm")
        elif delta < -30 and sell_score > 0:
            sell_score *= 1.08
            signal.rules_fired.append("delta-_confirm")

        # Plafonner les multiplicateurs (max 1.5x le score brut des regles)
        MAX_MULT = 1.50
        buy_score = min(buy_score, buy_score_raw * MAX_MULT) if buy_score_raw > 0 else buy_score
        sell_score = min(sell_score, sell_score_raw * MAX_MULT) if sell_score_raw > 0 else sell_score

        # ═══════════════════════════════════════════════════════
        # FILTRES QUALITE — Chemin libre + Mur protecteur
        # ═══════════════════════════════════════════════════════

        # F1: Chemin libre vers TP (HVN au-dessus > 15t pour BUY)
        # Si HVN < 15t → MUR qui bloque le TP → KILL le signal
        hvn_above = _get(row, "dist_session_hvn_above", 999)
        hvn_below = _get(row, "dist_session_hvn_below", 999)

        if buy_score > 0:
            if hvn_above <= 15:
                buy_score *= 0.0  # KILL — mur au-dessus trop proche
                signal.quality_filters.append(f"BLOQUE_HVN_above={hvn_above:.0f}t")
            elif hvn_above > 25:
                buy_score *= 1.25
                signal.quality_filters.append("chemin_libre_HVN↑")

        if sell_score > 0:
            if hvn_below <= 15:
                sell_score *= 0.0
                signal.quality_filters.append(f"BLOQUE_HVN_below={hvn_below:.0f}t")
            elif hvn_below > 25:
                sell_score *= 1.15
                signal.quality_filters.append("chemin_libre_HVN↓")

        # F2: SL protege par GEX/HVN (mur derriere)
        gex_dn = abs(_get(row, "dist_gex_nearest_dn", 999))
        gex_up = abs(_get(row, "dist_gex_nearest_up", 999))

        if buy_score > 0 and (hvn_below < 20 or gex_dn < 20):
            signal.quality_filters.append("SL_protege_mur↓")

        if sell_score > 0 and (hvn_above < 20 or gex_up < 20):
            signal.quality_filters.append("SL_protege_mur↑")

        # F3: Pas d'obstacle option entre prix et TP
        # BUY : pas de call wall proche au-dessus
        next_wall_call = _get(row, "next_wall_is_call")
        next_wall_dist = _get(row, "next_wall_dist_ticks", 999)

        if buy_score > 0 and next_wall_call == 1 and next_wall_dist < 20:
            buy_score *= 0.70  # Penalite : call wall bloque le TP
            signal.quality_filters.append("PENALITE_call_wall_obstacle")

        if sell_score > 0 and next_wall_call == 0 and next_wall_dist < 20:
            sell_score *= 0.70  # Penalite : put wall bloque le TP
            signal.quality_filters.append("PENALITE_put_wall_obstacle")

        # ═══════════════════════════════════════════════════════
        # DECISION FINALE
        # ═══════════════════════════════════════════════════════

        # Compter les regles (pas les confirmations ni les filtres)
        n_buy = sum(1 for r in signal.rules_fired if "→BUY" in r)
        n_sell = sum(1 for r in signal.rules_fired if "→SELL" in r)
        signal.n_rules_buy = n_buy
        signal.n_rules_sell = n_sell

        # Score net
        net_score = buy_score - sell_score

        # Direction (avant cooldown)
        raw_direction = 0
        if net_score > self.min_score and n_buy >= self.min_rules:
            raw_direction = 1
        elif net_score < -self.min_score and n_sell >= self.min_rules:
            raw_direction = -1

        # Cooldown : pas de signal si trop recent ou max jour atteint
        if raw_direction != 0:
            bar_now = self._bar_counter.get(sym, 0)
            last_bar = self._last_signal_bar.get(sym, -999)
            bars_since = bar_now - last_bar
            daily_count = self._daily_signals.get(sym, 0)

            if bars_since < self.cooldown_bars:
                raw_direction = 0  # Trop tot apres le dernier signal
                signal.rules_fired.append(f"COOLDOWN({bars_since}/{self.cooldown_bars})")
            elif daily_count >= self.max_signals_day:
                raw_direction = 0  # Max signaux jour atteint
                signal.rules_fired.append(f"MAX_JOUR({daily_count})")
            else:
                # Enregistrer le signal
                self._last_signal_bar[sym] = bar_now
                self._last_signal_dir[sym] = raw_direction
                self._daily_signals[sym] = daily_count + 1

        signal.direction = raw_direction
        signal.score = net_score if raw_direction != 0 else net_score
        if raw_direction == 1:
            signal.score = min(net_score, 1.0)
        elif raw_direction == -1:
            signal.score = max(net_score, -1.0)

        # Confiance
        abs_score = abs(signal.score)
        if abs_score >= 0.50:
            signal.confidence = "HIGH"
        elif abs_score >= 0.35:
            signal.confidence = "MEDIUM"
        elif abs_score >= self.min_score:
            signal.confidence = "LOW"
        else:
            signal.confidence = "NONE"

        # SL/TP adaptatif
        signal.sl_ticks, signal.tp_ticks = self._compute_sltp(row, signal.direction)

        return signal

    def _compute_sltp(self, row, direction: int) -> tuple:
        """
        Calcule SL/TP base sur les murs.
        SL derriere le mur le plus PROCHE, TP avant le premier obstacle.
        Controle R:R minimum 1.2:1.
        Fallback : SL=20t, TP=20t.
        """
        sl_ticks = 20.0
        tp_ticks = 20.0

        if direction == 0:
            return sl_ticks, tp_ticks

        if direction == 1:  # BUY
            # SL = derriere le mur le plus PROCHE en-dessous
            hvn_below = _get(row, "dist_session_hvn_below", 0)
            gex_below = abs(_get(row, "dist_gex_nearest_dn", 0))
            walls = [w for w in [hvn_below, gex_below] if 8 < w < 50]
            if walls:
                sl_ticks = min(walls) + 4  # mur le plus proche + buffer

            # TP = avant le premier obstacle au-dessus
            hvn_above = _get(row, "dist_session_hvn_above", 0)
            if hvn_above > 10:
                tp_ticks = max(hvn_above - 2, 15)

        else:  # SELL
            # SL = derriere le mur le plus PROCHE au-dessus
            hvn_above = _get(row, "dist_session_hvn_above", 0)
            gex_above = _get(row, "dist_gex_nearest_up", 0)
            walls = [w for w in [hvn_above, gex_above] if 8 < w < 50]
            if walls:
                sl_ticks = min(walls) + 4

            # TP = avant le premier obstacle en-dessous
            hvn_below = _get(row, "dist_session_hvn_below", 0)
            if hvn_below > 10:
                tp_ticks = max(hvn_below - 2, 15)

        # Clamp
        sl_ticks = max(12, min(sl_ticks, 50))
        tp_ticks = max(15, min(tp_ticks, 60))

        # Controle R:R minimum 1.2:1 — si TP trop petit vs SL, ajuster
        if tp_ticks < sl_ticks * 1.2:
            tp_ticks = sl_ticks * 1.2

        # Re-clamp TP apres ajustement R:R
        tp_ticks = min(tp_ticks, 60)

        return sl_ticks, tp_ticks

    def summary(self, signal: RuleSignal) -> str:
        """Resume lisible d'un signal."""
        if signal.direction == 0:
            return f"HOLD (score={signal.score:+.2f}, buy={signal.n_rules_buy} sell={signal.n_rules_sell})"

        dir_str = "BUY" if signal.direction == 1 else "SELL"
        rules = " + ".join(signal.rules_fired[:5])
        filters = ", ".join(signal.quality_filters) if signal.quality_filters else "aucun"
        return (f"{dir_str} [{signal.confidence}] score={signal.score:+.2f} "
                f"| {rules} | filtres: {filters} "
                f"| SL={signal.sl_ticks:.0f}t TP={signal.tp_ticks:.0f}t")
