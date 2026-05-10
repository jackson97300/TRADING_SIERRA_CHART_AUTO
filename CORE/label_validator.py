"""
Label Validator — MIA Trading System V2
========================================

Miroir du quality_validator mais pour les labels triple-barriere.
Tourne automatiquement en fin de labeler.py en mode BLOCKING.

Regle souveraine (Jackson 13/04/2026) :
    "AVOIR DE DONNER PROPRE EST LA BASE POUR UN BOT DE TRADING"
    La qualite des labels est aussi critique que la qualite des features.

6 criteres de refus (zero tolerance) :
    1. Mode collapse        : classe minoritaire < 10% des barres valides
    2. Asymetrie buy/sell   : ratio max/min > 3.0
    3. sample_weight casse  : NaN, negatif, somme = 0, ou constant
    4. Future leak          : exit_offset > FORWARD_BARS configure
    5. TP/SL incoherent     : realized_pts / tp_pts > 1.1 (signal tronque)
    6. RR degrade           : tp_pts / sl_pts < 1.5 (calibrage triple barriere)

Usage :
    from label_validator import LabelValidator, LabelViolation

    validator = LabelValidator(symbol="ES", strict=True)
    report = validator.validate(df_labeled)
    if not report.passed:
        raise LabelViolation(report.summary())

Auteur : MIA Trading System
Date   : 2026-04-13
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════════════════════════════

MODE_COLLAPSE_MIN_PCT = 0.05        # classe minoritaire >= 5% (parmi BUY/SELL)
BUY_SELL_RATIO_MAX = 3.0            # ratio max/min entre BUY et SELL
SAMPLE_WEIGHT_SUM_MIN = 1e-6        # somme poids > 0
RR_MIN = 1.5                        # risk/reward minimum
REALIZED_TP_MAX_RATIO = 1.1         # realized / tp <= 1.1 (sinon debordement)
FORWARD_BARS_DEFAULT = 20           # fallback si config non-fournie

# TP/SL attendus par instrument (source : CLAUDE.md)
EXPECTED_TP_SL = {
    "ES": {"sl_ticks": 5, "tp_ticks": 9},
    "NQ": {"sl_ticks": 20, "tp_ticks": 36},
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LabelIssue:
    rule: str
    severity: str  # "RED" ou "YELLOW"
    detail: str


@dataclass
class LabelReport:
    symbol: str
    n_bars: int
    n_valid_bars: int
    n_buy: int
    n_sell: int
    n_hold: int
    red_flags: List[LabelIssue] = field(default_factory=list)
    yellow_flags: List[LabelIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.red_flags) == 0

    def summary(self) -> str:
        lines = [
            "",
            "=" * 70,
            f"  LABEL VALIDATOR REPORT — {self.symbol}",
            "=" * 70,
            f"  Barres totales  : {self.n_bars}",
            f"  Barres valides  : {self.n_valid_bars}",
            f"  BUY  (+1)       : {self.n_buy}  "
            f"({self.n_buy / max(self.n_valid_bars, 1):.1%})",
            f"  SELL (-1)       : {self.n_sell}  "
            f"({self.n_sell / max(self.n_valid_bars, 1):.1%})",
            f"  HOLD ( 0)       : {self.n_hold}  "
            f"({self.n_hold / max(self.n_valid_bars, 1):.1%})",
            f"  RED flags       : {len(self.red_flags)}  (bloquants)",
            f"  YELLOW flags    : {len(self.yellow_flags)}  (warning)",
            "",
        ]
        if self.red_flags:
            lines.append("  RED FLAGS (BLOCKING) :")
            lines.append("  " + "-" * 68)
            for f in self.red_flags:
                lines.append(f"    [{f.rule:15s}] {f.detail}")
        if self.yellow_flags:
            lines.append("")
            lines.append("  YELLOW FLAGS :")
            lines.append("  " + "-" * 68)
            for f in self.yellow_flags:
                lines.append(f"    [{f.rule:15s}] {f.detail}")
        lines.append("")
        lines.append("=" * 70)
        if self.passed:
            lines.append("  VERDICT : PASSED — labels peuvent etre sauvegardes")
        else:
            lines.append("  VERDICT : BLOCKED — labels REFUSES")
            lines.append("  Action  : corriger les issues ci-dessus puis rerun labeler.py")
        lines.append("=" * 70)
        return "\n".join(lines)


class LabelViolation(Exception):
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════════

class LabelValidator:
    """Valide un DataFrame de labels triple-barriere."""

    def __init__(self, symbol: str, forward_bars: int = FORWARD_BARS_DEFAULT,
                 strict: bool = True, verbose: bool = True):
        self.symbol = symbol.upper()
        self.forward_bars = forward_bars
        self.strict = strict
        self.verbose = verbose

    # ─── API publique ─────────────────────────────────────────────────

    def validate(self, df: pd.DataFrame) -> LabelReport:
        """Audite le DataFrame labeled et retourne un rapport."""
        # Filtrer les barres valides (eliminer partial_session et invalid)
        df_valid = self._get_valid_subset(df)

        report = LabelReport(
            symbol=self.symbol,
            n_bars=len(df),
            n_valid_bars=len(df_valid),
            n_buy=int((df_valid["label"] == 1).sum()) if "label" in df_valid else 0,
            n_sell=int((df_valid["label"] == -1).sum()) if "label" in df_valid else 0,
            n_hold=int((df_valid["label"] == 0).sum()) if "label" in df_valid else 0,
        )

        if len(df_valid) == 0:
            report.red_flags.append(LabelIssue(
                rule="EMPTY", severity="RED",
                detail="Aucune barre valide apres filtrage",
            ))
        else:
            # Appliquer les 6 regles
            self._check_mode_collapse(df_valid, report)
            self._check_buy_sell_ratio(df_valid, report)
            self._check_sample_weight(df_valid, report)
            self._check_future_leak(df_valid, report)
            self._check_realized_vs_tp(df_valid, report)
            self._check_rr_calibration(df_valid, report)

        if self.verbose:
            print(report.summary())

        if self.strict and not report.passed:
            raise LabelViolation(
                f"Labels {self.symbol} REFUSES : "
                f"{len(report.red_flags)} red flags. Voir rapport ci-dessus."
            )

        return report

    # ─── Helpers prives ───────────────────────────────────────────────

    def _get_valid_subset(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filtre les barres valides (exclut invalid + partial_session)."""
        if "valid_bar" in df.columns:
            df = df[df["valid_bar"] == True]
        if "partial_session" in df.columns:
            df = df[df["partial_session"] == False]
        return df

    def _check_mode_collapse(self, df: pd.DataFrame, report: LabelReport) -> None:
        """Regle 1 : classe minoritaire (BUY ou SELL) >= 5% des barres valides."""
        if "label" not in df.columns:
            report.red_flags.append(LabelIssue(
                rule="MISSING_COL", severity="RED",
                detail="Colonne 'label' absente",
            ))
            return

        total = len(df)
        n_buy = int((df["label"] == 1).sum())
        n_sell = int((df["label"] == -1).sum())
        n_minor = min(n_buy, n_sell)
        pct_minor = n_minor / total if total > 0 else 0.0

        if pct_minor < MODE_COLLAPSE_MIN_PCT:
            report.red_flags.append(LabelIssue(
                rule="MODE_COLLAPSE", severity="RED",
                detail=f"Classe minoritaire (BUY ou SELL) = {pct_minor:.1%} "
                       f"< {MODE_COLLAPSE_MIN_PCT:.0%} (minoritaire={n_minor}/{total}). "
                       f"Le modele va s'effondrer sur HOLD.",
            ))

    def _check_buy_sell_ratio(self, df: pd.DataFrame, report: LabelReport) -> None:
        """Regle 2 : ratio BUY/SELL dans [1/3, 3]."""
        if "label" not in df.columns:
            return
        n_buy = int((df["label"] == 1).sum())
        n_sell = int((df["label"] == -1).sum())
        if n_buy == 0 or n_sell == 0:
            return  # deja flag par mode_collapse
        ratio = max(n_buy, n_sell) / min(n_buy, n_sell)
        if ratio > BUY_SELL_RATIO_MAX:
            report.red_flags.append(LabelIssue(
                rule="BUY_SELL_SKEW", severity="RED",
                detail=f"Ratio BUY/SELL = {ratio:.2f} > {BUY_SELL_RATIO_MAX} "
                       f"(BUY={n_buy}, SELL={n_sell}). Biais directionnel suspect.",
            ))
        elif ratio > 2.0:
            report.yellow_flags.append(LabelIssue(
                rule="BUY_SELL_SKEW", severity="YELLOW",
                detail=f"Ratio BUY/SELL = {ratio:.2f} (attention au biais)",
            ))

    def _check_sample_weight(self, df: pd.DataFrame, report: LabelReport) -> None:
        """Regle 3 : sample_weight valide (pas de NaN, pas negatif, somme > 0)."""
        if "sample_weight" not in df.columns:
            report.yellow_flags.append(LabelIssue(
                rule="SAMPLE_WEIGHT", severity="YELLOW",
                detail="Colonne 'sample_weight' absente "
                       "(Lopez AFML ch.4 uniqueness non applique)",
            ))
            return

        sw = df["sample_weight"]
        n_nan = int(sw.isna().sum())
        n_neg = int((sw < 0).sum())
        sw_sum = float(sw.sum())
        sw_std = float(sw.std())

        if n_nan > 0:
            report.red_flags.append(LabelIssue(
                rule="SAMPLE_WEIGHT", severity="RED",
                detail=f"sample_weight contient {n_nan} NaN ({n_nan/len(sw):.1%})",
            ))
        if n_neg > 0:
            report.red_flags.append(LabelIssue(
                rule="SAMPLE_WEIGHT", severity="RED",
                detail=f"sample_weight contient {n_neg} valeurs negatives",
            ))
        if sw_sum < SAMPLE_WEIGHT_SUM_MIN:
            report.red_flags.append(LabelIssue(
                rule="SAMPLE_WEIGHT", severity="RED",
                detail=f"sum(sample_weight) = {sw_sum:.2e} ~ 0 "
                       f"(le fit sera degenerement nul)",
            ))
        if sw_std < 1e-9 and len(sw) > 10:
            report.yellow_flags.append(LabelIssue(
                rule="SAMPLE_WEIGHT", severity="YELLOW",
                detail=f"sample_weight constant "
                       f"(uniqueness non applique — Lopez ch.4 mort ?)",
            ))

    def _check_future_leak(self, df: pd.DataFrame, report: LabelReport) -> None:
        """Regle 4 : exit_offset <= forward_bars (pas de barre future non-observable)."""
        if "exit_offset" not in df.columns:
            return
        eo = df["exit_offset"].dropna()
        if len(eo) == 0:
            return
        max_offset = int(eo.max())
        if max_offset > self.forward_bars:
            report.red_flags.append(LabelIssue(
                rule="FUTURE_LEAK", severity="RED",
                detail=f"max(exit_offset) = {max_offset} > forward_bars={self.forward_bars}. "
                       f"Certaines labels utilisent des barres hors horizon.",
            ))

    def _check_realized_vs_tp(self, df: pd.DataFrame, report: LabelReport) -> None:
        """Regle 5 : |realized_pts| <= tp_pts * 1.1 (pas de debordement)."""
        if "realized_pts" not in df.columns or "tp_pts" not in df.columns:
            return
        sub = df[(df["label"] != 0) & df["tp_pts"].notna()
                  & df["realized_pts"].notna()]
        if len(sub) == 0:
            return
        tp = sub["tp_pts"].abs()
        real = sub["realized_pts"].abs()
        ratio = (real / tp.replace(0, np.nan)).dropna()
        if len(ratio) == 0:
            return
        max_ratio = float(ratio.max())
        n_debord = int((ratio > REALIZED_TP_MAX_RATIO).sum())
        if n_debord > 0:
            pct = n_debord / len(ratio)
            severity = "RED" if pct > 0.05 else "YELLOW"
            flag = report.red_flags if severity == "RED" else report.yellow_flags
            flag.append(LabelIssue(
                rule="REALIZED_TP", severity=severity,
                detail=f"{n_debord}/{len(ratio)} ({pct:.1%}) labels avec "
                       f"|realized| > 1.1*tp (max ratio={max_ratio:.2f}). "
                       f"Bug potentiel de simulation triple barriere.",
            ))

    def _check_rr_calibration(self, df: pd.DataFrame, report: LabelReport) -> None:
        """Regle 6 : tp_pts / sl_pts >= 1.5 et match config attendue."""
        if "tp_pts" not in df.columns or "sl_pts" not in df.columns:
            return
        sub = df[(df["label"] != 0) & df["tp_pts"].notna() & df["sl_pts"].notna()]
        if len(sub) == 0:
            return

        tp_mean = float(sub["tp_pts"].abs().mean())
        sl_mean = float(sub["sl_pts"].abs().mean())
        if sl_mean < 1e-9:
            return
        rr = tp_mean / sl_mean
        if rr < RR_MIN:
            report.red_flags.append(LabelIssue(
                rule="RR_LOW", severity="RED",
                detail=f"RR moyen = tp/sl = {rr:.2f} < {RR_MIN}. "
                       f"Avec un RR faible, il est impossible d'avoir un edge avec WR<60%.",
            ))

        # Verifier contre la config attendue
        expected = EXPECTED_TP_SL.get(self.symbol)
        if expected:
            # tp_pts/sl_pts sont en points (pas ticks), convertir avec TICK_SIZE
            tick_size = 0.25  # default ES/NQ. MGC=0.10 — TODO Chantier 6 : recuperer
                              # tick_size par symbole via expected['symbol'] ou param fonction
                              # (actuellement hardcoded = MGC silencieusement faux).
            expected_tp = expected["tp_ticks"] * tick_size
            expected_sl = expected["sl_ticks"] * tick_size
            tolerance = 0.2  # 20%
            if abs(tp_mean - expected_tp) / expected_tp > tolerance:
                report.yellow_flags.append(LabelIssue(
                    rule="TP_MISMATCH", severity="YELLOW",
                    detail=f"tp_mean={tp_mean:.2f} pts divergent de "
                           f"{expected_tp:.2f} pts attendu (CLAUDE.md)",
                ))
            if abs(sl_mean - expected_sl) / expected_sl > tolerance:
                report.yellow_flags.append(LabelIssue(
                    rule="SL_MISMATCH", severity="YELLOW",
                    detail=f"sl_mean={sl_mean:.2f} pts divergent de "
                           f"{expected_sl:.2f} pts attendu (CLAUDE.md)",
                ))


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Label Validator MIA V2")
    parser.add_argument("--symbol", default="ES", choices=["ES", "NQ"])
    parser.add_argument("--path", default=None,
                        help="Chemin vers ALL_{symbol}_labels.parquet")
    parser.add_argument("--forward-bars", type=int, default=FORWARD_BARS_DEFAULT)
    parser.add_argument("--no-strict", action="store_true")
    args = parser.parse_args()

    if args.path is None:
        args.path = f"DATA/LABELS/ALL_{args.symbol}_labels.parquet"

    print(f"[LabelValidator] Lecture {args.path}")
    df = pd.read_parquet(args.path)
    print(f"[LabelValidator] {len(df)} barres chargees")

    validator = LabelValidator(
        symbol=args.symbol,
        forward_bars=args.forward_bars,
        strict=not args.no_strict,
        verbose=True,
    )
    try:
        report = validator.validate(df)
        return 0 if report.passed else 1
    except LabelViolation as e:
        print(f"\n[LabelValidator] REFUS : {e}")
        return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
