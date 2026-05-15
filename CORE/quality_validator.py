"""
Quality Validator — MIA Trading System V2
==========================================

Garde-fou code-level qui REFUSE la generation d'un dataset pollue.
Tourne automatiquement a la fin de dataset_builder.py en mode BLOCKING.

Regle souveraine (Jackson 13/04/2026) :
    "AVOIR DE DONNER PROPRE EST LA BASE POUR UN BOT DE TRADING"
    Qualite des donnees > symetrie ES/NQ > screening Spearman

5 criteres de refus (zero tolerance) :
    1. Fuite instrument   : |mean_ES - mean_NQ| / max(std_ES, std_NQ) > SEUIL
    2. Fuite volatilite   : ticks/range/dist non normalises avec std_NQ/std_ES > 2.5
    3. Outlier explosion  : max / |p99| > 100 (division par ~0 probable)
    4. Quasi-constante    : std < 1e-6 OU top_value_freq > 0.95
    5. Prix absolu        : nom niveau (_high/_low/strike) avec mean > 100

Usage :
    from quality_validator import QualityValidator, QualityViolation

    validator = QualityValidator(strict=True)
    report = validator.validate(df_es, df_nq)
    if not report.passed:
        raise QualityViolation(report.summary())

Auteur : MIA Trading System
Date   : 2026-04-13
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════════════════════════════

LEAK_INSTRUMENT_THRESHOLD = 0.5      # |mean_ES - mean_NQ| / std_union > 0.5
LEAK_VOLATILITY_STD_RATIO = 2.5      # std_NQ / std_ES > 2.5 pour features en ticks
OUTLIER_MAX_P99_RATIO = 100.0        # max / |p99| > 100
CONSTANT_STD_THRESHOLD = 1e-6
CONSTANT_TOP_FREQ_THRESHOLD = 0.95
PRICE_LEVEL_MIN_MEAN = 100.0         # ES/NQ prix absolus > 100

# Suffixes qui indiquent qu'une feature est deja normalisee
NORMALIZED_SUFFIXES = ("_atr", "_norm", "_pct", "_ratio", "_score", "_pct_", "_b",
                       "_m", "_count", "_bars", "_agreement", "_weighted",
                       "_correlation", "_slope", "_inside", "_above", "_below",
                       "_align", "_signal", "_prob", "_bias", "_dir", "_phase",
                       "_rank", "_rvol", "_vs_atr")

# Substrings qui indiquent une feature potentiellement polluee
LEAK_PATTERNS = {
    "ticks_leak": ["_ticks"],
    "range_leak": ["range_", "_range"],
    "dist_leak":  ["dist_"],
    "volume_leak": ["total_vol", "buy_vol", "sell_vol", "diag_neg_delta",
                    "diag_pos_delta", "ticks_count", "vol_per_sec"],
    "price_level": ["_high", "_low", "_open", "_close", "strike"],
}

# Features autorisees a etre asymetriques par construction (intermarche)
SYMMETRIC_EXEMPT = [
    "_es_nq_",       # mq_es_nq_gamma_div, mq_es_nq_gex_ratio, mq_es_nq_iv_spread
    "im_price_ratio",  # ratio ES/NQ par nature asymetrique
    "delta_day",     # TODO : a virer mais pour info
]

# Features partagees ES=NQ par construction (memes valeurs)
SHARED_FEATURES = [
    "vix_level", "vix_regime", "vix_above_hvl", "vix_above_hvl_0dte",
    "dist_vix_call", "dist_vix_put", "dist_vix_call_0dte", "dist_vix_put_0dte",
    "dist_vix_hvl", "dist_vix_gex_nearest_up", "dist_vix_gex_nearest_dn",
    "mq_es_nq_gamma_div", "mq_es_nq_gex_ratio", "mq_es_nq_iv_spread",
    "im_cross_delta_agreement_5", "im_cross_delta_weighted_5",
    "im_open_type_agreement", "im_rolling_correlation_10",
]

# Features event-based par design : rares (fire rate < 1%) car elles ne
# declenchent qu'a des moments specifiques (divergence, rvol extreme, etc.).
# Le check CONSTANT (top_value_freq > 95%) est une fausse alerte pour elles.
# Ces features sont EXEMPTEES du check top_freq mais gardent le check std.
# Ajoute 17/04/2026 pour les features div.
EVENT_BASED_FEATURES = [
    "delta_divergence_clean",
    "delta_div_buy_clean",
    "delta_div_sell_clean",
    "delta_div_strength",
    "div_at_key_level_ticks",
    "div_confluence_dmp",
    "div_confluence_with_regime",
    "div_forward_return_20b",
    "div_regime_proxy_ok",
    "ctx_double_top_trap",
    "ctx_momentum_exhaustion",
    "rvol_buy_strong",
    "rvol_sell_strong",
    "rvol_absorb_buy",
    "rvol_absorb_sell",
    # Ajout 18/04/2026 suite audit empirique :
    # - ctx_instant_absorption : feature calculee Python (rolling_features.py:187)
    #   rare event stable, non affectee par pollution backfill C++. Reste EVENT_BASED.
    # - bar_long_dn_bar / bar_long_up_bar RETIRES (pollution historique backfill
    #   confirmee : NQ aggregate mean 0.737 vs 11% fire rate post-fix 17/04).
    #   Deplaces vers PROHIBITED temporaire (dataset_builder.py), retour prevu a
    #   la purge v4 02/05/2026 apres rebuild backfill DMP 3.7.7.
    "ctx_instant_absorption",
    # Ajout 03/05/2026 (Plan B regime_engine) — features rare events Sierra Chart :
    # - delta_divergence : binaire DMP, rare event signal divergence
    # - delta_day_dir : binaire -1/+1, broadcast 1 valeur/jour (event-based, top_freq>>95% par design)
    #   R4 code-reviewer : reclasser ici (vs NATURALLY_DIFFERENT) car broadcast event jour.
    "delta_divergence",
    "delta_day_dir",
]

# Features legitimement differenciees par instrument (% ou ratios naturels)
# — IV/HV d'un instrument est par nature differente entre ES et NQ
# — les ratios macroeconomiques (PC ratio, GEX ratio) sont differents par marche
# — les features CATEGORIELLES ont des distributions differentes ES/NQ sans etre
#   des fuites volatilite (ex: profile_shape, open_type, day_type)
NATURALLY_DIFFERENT = [
    "mq_iv_30d", "mq_hv_30d", "mq_iv_rank", "mq_hv_rank",
    "mq_exp_move_pct", "mq_exp_move",
    "mq_pc_oi", "mq_pc_gex", "mq_pc_dex",
    "mq_net_gex_ratio", "mq_net_dex_ratio",
    "ib_range_atr",  # ratio IB/ATR, peut legerement varier
    # Features categorielles (valeurs entieres, distributions differentes par symbol)
    "profile_shape",      # 0=D / 1=P / 2=b / 3=B
    "open_type",          # 0-5 types Dalton
    "day_type",           # 0-4 types jour
    "open_direction",     # -1/0/+1
    "profile_skew",       # [-1,+1] asymetrie
    "poc_position",       # [0,1]
    "trend_day_probability",  # [0,1]
    "open_bias_conf",     # [0,1]
    "vix_regime",         # 0/1/2 regime
    "volume_imbalance",   # ratio asymetrique
    # Extension Option B (13/04/2026) — features binaires / frequency / scores
    "cvd_day_dir",        # -1/+1 direction CVD
    "is_double_dist",     # 0/1 double distribution
    "bar_edge_buy",       # frequence bar edge (pas fuite vol)
    "bar_edge_sell",      # idem
    "retest_high_count",  # compte retests (seuil instrument-specifique)
    "mq_expiring_gex_pct", # pourcentage
    "single_print_count", # compte single prints
    # Distances aux niveaux options MenthorQ : structures de marche differentes
    # ES et NQ ont des strikes placees differemment, les distances /atr sont
    # naturellement non-symetriques (pas une fuite volatilite)
    "mq_dist_call_0dte_atr",
    "mq_dist_put_0dte_atr",
    "mq_dist_call_res_atr",
    "mq_dist_hvl_atr",
    "dist_mq_call_atr",
    "dist_mq_put_atr",
    "dist_mq_hvl_atr",
    "dist_mq_call_0dte_atr",
    # Features div (17/04/2026) : naturellement differentes par instrument
    # (ATR, tick scale, fire rate distincts ES/NQ par design)
    "div_at_key_level_ticks",
    "div_forward_return_20b",
    # Features naturellement differenciees 18/04/2026 :
    # - bars_since_retest_low : compteur bars, NQ plus volatil = plus de bars entre retests
    # - ctx_va_developing_10 : VA width scale ES vs NQ pure (points natifs)
    # - open_in_prev_va : biais session {ES,NQ} distinct par horaire de trading
    # - dist_sess_low, dist_swing_low, dist_vwap_d_sd2d : POINTS BRUTS (utilises
    #   par primary_models avec seuils en points). Ratio NQ/ES natif ~4x = prix.
    #   TODO : refactor primary_models pour utiliser _atr versions.
    "dist_sess_low",
    "dist_swing_low",
    "dist_vwap_d_sd2d",
    # RESERVE 3 code-reviewer : bn_score_bear RETIRE. Audit empirique DMP_Transform.h:1069
    # montre qu'il s'agit d'un COMPOSITE de features PROHIBITED (bn_color_dn, bn_absorb_bid,
    # bn_pressure_bid, bn_color_dn_2) + bn_long_dn. Avant fix 3.7.6 : composants satures
    # a 1 -> score eleve (mean 0.55 ES / 0.67 NQ). Apres fix : events propres -> score
    # s'effondre (0.02 ES / 0.06 NQ). Pas un biais naturel = composite casse.
    # bn_score_bear + bn_score_raw -> PROHIBITED (dataset_builder.py).
    "bars_since_retest_low",
    "ctx_va_developing_10",
    "open_in_prev_va",
    # Ajout 03/05/2026 (Plan B regime_engine) — features regime brutes naturellement
    # differenciees ES/NQ par design :
    # - poc_bar_dist : distance POC en bars, NQ plus volatil = POC migre plus loin
    # - regime_mode : categoriel ("TREND"/"RANGE"/"NORMAL"), distribution differente ES/NQ
    # - regime_favor : categoriel ("LONG"/"SHORT"/"NEUTRE")
    # - regime_vol : categoriel ("EXTREME"/"HIGH"/"NORMAL"/"LOW")
    # NOTE : regime_mode/favor/vol sont strings, quality_validator skip silencieusement
    # (R4 code-reviewer). Validation parite via test_regime_engine.py (a creer).
    "poc_bar_dist",
    "regime_mode",
    "regime_favor",
    "regime_vol",
    # Ajout 11/05/2026 (audit quality-auditor Phase 0.3) — n_big_t1 MGC :
    # seuil empirique t1=10 (MGC) trop bas vs ES t1=100 -> fire rate MGC 37.65%
    # vs ES 2.71% (ratio 14x). Naturellement different par calibration tier.
    # MGC n_big_t2 (seuil 30) = fire 2.24% = equivalent ES t1 en rarete.
    # Pour STANDALONE training (3 modeles ES/NQ/MGC separes) : feature utile,
    # variance non-nulle MGC. Pour JOINT training : DROP obligatoire (leak instrument).
    # Decision Jackson 11/05 : standalone par instrument -> garder + naturally_different.
    "n_big_t1",
    "n_big_buy_t1",
    "n_big_sell_t1",
]

# ═══════════════════════════════════════════════════════════════════════════════
# FEATURES PROHIBITED Bug D (16/05/2026 — quality-auditor + market-analyst)
# ═══════════════════════════════════════════════════════════════════════════════
# Identifiees apres rebuild 5 mois post Bug D + Bug E :
#   - 7 RED flags : critere fuite, outlier, prix absolu, quasi-constante
#   - DROP avant tout retrain LightGBM. Action systematique dans dataset_builder.
PROHIBITED_FEATURES_BUGD = [
    # CRITERE 3 : prix absolu (fuite instrument + non-stationnaire)
    "avg_price",
    # CRITERE 4 : outlier explosion (max/p99 = 1881-5824x sur 22K bars)
    #   Cause : bug calcul find_nearest_below() quand pas de blind level proche.
    #   Distribution bimodale (-28% ou ~0) = bruit non exploitable ML.
    "dist_blind_nearest_dn_pct",
    # CRITERE 4 : outlier 400x ES, 229x NQ (winsorisation envisagee Plan B)
    #   Plan A : DROP. Plan B : clip(p1, p99) si signal residuel justifie.
    "dist_gex_nearest_dn_pct",
    # CRITERE 1 + 4 : fuite instrument ratio=1.31 + 77-91% nulls 4 mois
    #   Cause : feature MQ-derived absente Dec-Mar 2026 (100% nulls),
    #   apparait avril partiellement. Non exploitable training cross-period.
    "position_in_range",
    # CRITERE 5 : quasi-constantes (top_value_freq > 94%)
    "bool_above_mq_call",        # 98.5% constant (rally avril-mai under call)
    "gex_cluster_count_z",       # 94-98.9% top value
    "is_roll_day",               # 99.9-100% constant (rarissime event 4x/an)
    # CRITERE 5 MGC : constants strictes (std=0) post MGC regime skip
    #   regime_engine skipped pour MGC (manque day_type/profile_shape DMP).
    "regime_confidence",         # MGC only : nunique=1 std=0
    "regime_trend_votes",        # MGC only : nunique=1 std=0
    "regime_range_votes",        # MGC only : nunique=1 std=0
    "regime_actionable",         # MGC only : nunique=1 std=0
]

# Meta columns a ignorer dans l'audit (pas des features)
# Phase 1 (13/04/2026) : ajout is_nq, partial_session, atr qui sont construits
# par dataset_builder mais excluses des features ML dans train_lightgbm.get_features.
META_COLUMNS = {
    "ts", "sym", "contract", "session_id", "session", "datetime_utc",
    "datetime_et", "label", "label_buy", "label_sell", "sample_weight",
    "exit_offset", "hl_mode", "price", "open", "high", "low", "close",
    "bar_high", "bar_low", "valid_bar", "day", "date",
    # Phase 1 extension
    "is_nq", "partial_session", "atr",
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FeatureViolation:
    """Une violation detectee sur une feature."""
    feature: str
    rule: str
    mean_es: float
    mean_nq: float
    std_es: float
    std_nq: float
    detail: str
    severity: str  # "RED" ou "YELLOW"


@dataclass
class QualityReport:
    """Rapport complet d'audit qualite."""
    n_features_audited: int
    red_flags: List[FeatureViolation] = field(default_factory=list)
    yellow_flags: List[FeatureViolation] = field(default_factory=list)
    green_count: int = 0

    @property
    def passed(self) -> bool:
        """Le dataset passe si AUCUN red flag."""
        return len(self.red_flags) == 0

    def summary(self) -> str:
        lines = [
            "",
            "=" * 70,
            "  QUALITY VALIDATOR REPORT",
            "=" * 70,
            f"  Features auditees : {self.n_features_audited}",
            f"  RED flags         : {len(self.red_flags)}  (drop immediat)",
            f"  YELLOW flags      : {len(self.yellow_flags)}  (a investiguer)",
            f"  GREEN             : {self.green_count}",
            "",
        ]

        if self.red_flags:
            lines.append("  RED FLAGS (BLOCKING) :")
            lines.append("  " + "-" * 68)
            for v in sorted(self.red_flags, key=lambda x: x.rule):
                lines.append(
                    f"    [{v.rule:12s}] {v.feature:35s}  "
                    f"ES={v.mean_es:12.3f} NQ={v.mean_nq:12.3f}"
                )
                lines.append(f"                 → {v.detail}")

        if self.yellow_flags:
            lines.append("")
            lines.append("  YELLOW FLAGS :")
            lines.append("  " + "-" * 68)
            for v in sorted(self.yellow_flags, key=lambda x: x.rule):
                lines.append(
                    f"    [{v.rule:12s}] {v.feature:35s}  {v.detail}"
                )

        lines.append("")
        lines.append("=" * 70)
        if self.passed:
            lines.append("  VERDICT : PASSED — dataset peut etre sauvegarde")
        else:
            lines.append("  VERDICT : BLOCKED — dataset REFUSE (red flags present)")
            lines.append("  Action  : drop/normalize les features ci-dessus avant rerun")
        lines.append("=" * 70)
        lines.append("")
        return "\n".join(lines)


class QualityViolation(Exception):
    """Exception levee si le validator refuse le dataset en mode strict."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════════

class QualityValidator:
    """Audite un couple ES/NQ de datasets selon 5 criteres de qualite.

    Usage :
        validator = QualityValidator(strict=True)
        report = validator.validate(df_es, df_nq)
        # En mode strict, leve QualityViolation si un red flag est detecte
    """

    def __init__(self, strict: bool = True, verbose: bool = True):
        self.strict = strict
        self.verbose = verbose

    # ─── API publique ─────────────────────────────────────────────────

    def validate(self, df_es: pd.DataFrame, df_nq: pd.DataFrame) -> QualityReport:
        """Audite le couple ES/NQ et retourne un rapport.

        Si strict=True, leve QualityViolation si red_flags != [].
        """
        features = self._get_feature_columns(df_es, df_nq)
        report = QualityReport(n_features_audited=len(features))

        for feat in features:
            violation = self._audit_feature(feat, df_es, df_nq)
            if violation is None:
                report.green_count += 1
            elif violation.severity == "RED":
                report.red_flags.append(violation)
            else:
                report.yellow_flags.append(violation)

        if self.verbose:
            print(report.summary())

        if self.strict and not report.passed:
            raise QualityViolation(
                f"Dataset REFUSE par quality_validator : "
                f"{len(report.red_flags)} red flags detectes. "
                f"Voir rapport ci-dessus."
            )

        return report

    # ─── Helpers prives ───────────────────────────────────────────────

    def _get_feature_columns(self, df_es: pd.DataFrame,
                              df_nq: pd.DataFrame) -> List[str]:
        """Liste des features candidates (intersection ES ∩ NQ, hors meta)."""
        common = set(df_es.columns) & set(df_nq.columns)
        features = [c for c in sorted(common) if c not in META_COLUMNS]
        features = [c for c in features
                    if pd.api.types.is_numeric_dtype(df_es[c])
                    and pd.api.types.is_numeric_dtype(df_nq[c])]
        return features

    def _audit_feature(self, feat: str, df_es: pd.DataFrame,
                       df_nq: pd.DataFrame) -> Optional[FeatureViolation]:
        """Applique les 5 regles a une feature. Retourne la 1ere violation trouvee."""
        s_es = df_es[feat].dropna()
        s_nq = df_nq[feat].dropna()

        if len(s_es) == 0 or len(s_nq) == 0:
            return None  # trop de NaN, laisse passer (autre check ailleurs)

        mean_es, mean_nq = s_es.mean(), s_nq.mean()
        std_es, std_nq = s_es.std(), s_nq.std()

        # Regle 4 : quasi-constante (priorite haute — bloque tout le reste)
        violation = self._check_constant(feat, s_es, s_nq, mean_es, mean_nq,
                                          std_es, std_nq)
        if violation:
            return violation

        # Feature partagee ES=NQ : skip les checks de symetrie
        if feat in SHARED_FEATURES:
            return self._check_outlier(feat, s_es, s_nq, mean_es, mean_nq,
                                        std_es, std_nq)

        # Feature naturellement differenciee (% ou ratio macro) : skip instrument leak
        if feat in NATURALLY_DIFFERENT:
            return self._check_outlier(feat, s_es, s_nq, mean_es, mean_nq,
                                        std_es, std_nq)

        # Regle 5 : prix absolu (nom niveau + mean > 100)
        violation = self._check_price_level(feat, mean_es, mean_nq,
                                              std_es, std_nq)
        if violation:
            return violation

        # Regle 1 : fuite instrument (asymetrie ES/NQ hors exemption)
        if not self._is_symmetric_exempt(feat):
            violation = self._check_instrument_leak(feat, mean_es, mean_nq,
                                                     std_es, std_nq)
            if violation:
                return violation

        # Regle 2 : fuite volatilite (ticks/range/dist non normalises)
        violation = self._check_volatility_leak(feat, mean_es, mean_nq,
                                                  std_es, std_nq)
        if violation:
            return violation

        # Regle 3 : outlier explosion
        violation = self._check_outlier(feat, s_es, s_nq, mean_es, mean_nq,
                                         std_es, std_nq)
        if violation:
            return violation

        return None  # GREEN

    def _check_constant(self, feat, s_es, s_nq, mean_es, mean_nq,
                         std_es, std_nq) -> Optional[FeatureViolation]:
        """Regle 4 : feature constante ou quasi-constante."""
        is_event_based = feat in EVENT_BASED_FEATURES
        for sym, s, std in [("ES", s_es, std_es), ("NQ", s_nq, std_nq)]:
            if std < CONSTANT_STD_THRESHOLD:
                return FeatureViolation(
                    feature=feat, rule="CONSTANT",
                    mean_es=mean_es, mean_nq=mean_nq,
                    std_es=std_es, std_nq=std_nq,
                    detail=f"{sym} std={std:.2e} < {CONSTANT_STD_THRESHOLD}",
                    severity="RED",
                )
            # Skip top_freq check for event-based features (rare by design)
            if is_event_based:
                continue
            top_freq = s.value_counts(normalize=True).iloc[0]
            if top_freq > CONSTANT_TOP_FREQ_THRESHOLD:
                return FeatureViolation(
                    feature=feat, rule="CONSTANT",
                    mean_es=mean_es, mean_nq=mean_nq,
                    std_es=std_es, std_nq=std_nq,
                    detail=f"{sym} top_value_freq={top_freq:.1%} > "
                           f"{CONSTANT_TOP_FREQ_THRESHOLD:.0%}",
                    severity="RED",
                )
        return None

    def _check_price_level(self, feat, mean_es, mean_nq,
                            std_es, std_nq) -> Optional[FeatureViolation]:
        """Regle 5 : feature qui stocke un niveau prix absolu."""
        feat_lower = feat.lower()
        has_level_suffix = any(pat in feat_lower
                                for pat in LEAK_PATTERNS["price_level"])
        if not has_level_suffix:
            return None
        # Est-ce normalise malgre le nom ?
        if any(feat_lower.endswith(s) or s in feat_lower[-10:]
               for s in NORMALIZED_SUFFIXES):
            return None
        # Exemption 18/04/2026 : features utilisees par primary_models en POINTS bruts
        # (CORE/primary_models/*.py). Refactor TODO pour migrer vers _atr versions.
        PRICE_LEVEL_EXEMPT = {
            "dist_sess_low", "dist_swing_low", "dist_vwap_d_sd2d",
        }
        if feat in PRICE_LEVEL_EXEMPT:
            return None
        # Si les valeurs ES et NQ sont toutes deux > 100 et tres differentes
        # → strike/prix absolu
        if abs(mean_es) > PRICE_LEVEL_MIN_MEAN and abs(mean_nq) > PRICE_LEVEL_MIN_MEAN:
            ratio = abs(mean_nq) / max(abs(mean_es), 1e-9)
            if ratio > 2.0 or ratio < 0.5:
                return FeatureViolation(
                    feature=feat, rule="PRICE_LEVEL",
                    mean_es=mean_es, mean_nq=mean_nq,
                    std_es=std_es, std_nq=std_nq,
                    detail=f"Prix absolu detecte (ratio NQ/ES={ratio:.1f}). "
                           f"Remplacer par distance normalisee.",
                    severity="RED",
                )
        return None

    def _check_instrument_leak(self, feat, mean_es, mean_nq,
                                std_es, std_nq) -> Optional[FeatureViolation]:
        """Regle 1 : fuite instrument (|mean_ES - mean_NQ| / std_union > seuil)."""
        std_union = max(std_es, std_nq, 1e-9)
        asymmetry = abs(mean_es - mean_nq) / std_union
        if asymmetry > LEAK_INSTRUMENT_THRESHOLD:
            return FeatureViolation(
                feature=feat, rule="INSTRUMENT",
                mean_es=mean_es, mean_nq=mean_nq,
                std_es=std_es, std_nq=std_nq,
                detail=f"|mean_ES - mean_NQ|/std_union = {asymmetry:.2f} "
                       f"> {LEAK_INSTRUMENT_THRESHOLD} → fuite instrument",
                severity="RED",
            )
        return None

    def _check_volatility_leak(self, feat, mean_es, mean_nq,
                                 std_es, std_nq) -> Optional[FeatureViolation]:
        """Regle 2 : fuite volatilite (ticks/range/dist non normalises)."""
        feat_lower = feat.lower()
        has_leak_pattern = any(
            pat in feat_lower
            for pat in LEAK_PATTERNS["ticks_leak"] + LEAK_PATTERNS["range_leak"]
        )
        # dist_ seulement si commence par dist_ (pas bars_since_retest)
        if feat_lower.startswith("dist_"):
            has_leak_pattern = True
        if not has_leak_pattern:
            return None
        # Est-ce normalise ?
        if any(feat_lower.endswith(s) for s in NORMALIZED_SUFFIXES):
            return None
        if "_atr" in feat_lower or "_norm" in feat_lower or "_pct" in feat_lower:
            return None
        # Ratio des std
        if std_es < 1e-9:
            return None
        std_ratio = std_nq / std_es
        if std_ratio > LEAK_VOLATILITY_STD_RATIO or std_ratio < 1 / LEAK_VOLATILITY_STD_RATIO:
            return FeatureViolation(
                feature=feat, rule="VOLATILITY",
                mean_es=mean_es, mean_nq=mean_nq,
                std_es=std_es, std_nq=std_nq,
                detail=f"std_NQ/std_ES = {std_ratio:.2f} (seuil {LEAK_VOLATILITY_STD_RATIO}) "
                       f"+ nom non normalise → fuite volatilite",
                severity="RED",
            )
        return None

    def _check_outlier(self, feat, s_es, s_nq, mean_es, mean_nq,
                        std_es, std_nq) -> Optional[FeatureViolation]:
        """Regle 3 : outlier explosion (max / |p99| > 100).

        Exemption (18/04/2026) : EVENT_BASED_FEATURES sont rare events par design.
        Leur ratio max/p99 peut exploser naturellement (division par ~0 sur
        fire rate < 1%) sans etre un bug. Ex : delta_div_strength = delta/magnitude
        de la divergence → petits deltas rare → ratio explosif.

        Garde-fou (reserve 2 code-reviewer) : meme en exemption, on refuse les
        valeurs non-finite (NaN/Inf/overflow) qui passeraient silencieusement.
        """
        if feat in EVENT_BASED_FEATURES:
            if not np.isfinite(s_es).all() or not np.isfinite(s_nq).all():
                return FeatureViolation(
                    feature=feat, rule="FINITE",
                    mean_es=mean_es, mean_nq=mean_nq,
                    std_es=std_es, std_nq=std_nq,
                    detail=f"EVENT_BASED exempt outlier mais contient NaN/Inf/overflow",
                    severity="RED",
                )
            return None
        for sym, s in [("ES", s_es), ("NQ", s_nq)]:
            if len(s) < 100:
                continue
            p99 = s.abs().quantile(0.99)
            max_abs = s.abs().max()
            if p99 < 1e-9:
                continue
            ratio = max_abs / p99
            if ratio > OUTLIER_MAX_P99_RATIO:
                return FeatureViolation(
                    feature=feat, rule="OUTLIER",
                    mean_es=mean_es, mean_nq=mean_nq,
                    std_es=std_es, std_nq=std_nq,
                    detail=f"{sym} max/p99 = {ratio:.0f} > {OUTLIER_MAX_P99_RATIO:.0f} "
                           f"(division par ~0 probable)",
                    severity="RED",
                )
        return None

    def _is_symmetric_exempt(self, feat: str) -> bool:
        """Feature exemptee de la regle de symetrie (intermarche par nature)."""
        return any(ex in feat for ex in SYMMETRIC_EXEMPT)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """CLI : valide les datasets existants."""
    import argparse
    parser = argparse.ArgumentParser(description="Quality Validator MIA V2")
    parser.add_argument("--es", default="DATA/DATASETS/ES_dataset_v2.parquet")
    parser.add_argument("--nq", default="DATA/DATASETS/NQ_dataset_v2.parquet")
    parser.add_argument("--no-strict", action="store_true",
                        help="Ne pas lever exception si red flags")
    args = parser.parse_args()

    print(f"[QualityValidator] Lecture {args.es}")
    df_es = pd.read_parquet(args.es)
    print(f"[QualityValidator] Lecture {args.nq}")
    df_nq = pd.read_parquet(args.nq)

    validator = QualityValidator(strict=not args.no_strict, verbose=True)
    try:
        report = validator.validate(df_es, df_nq)
        return 0 if report.passed else 1
    except QualityViolation as e:
        print(f"\n[QualityValidator] REFUS : {e}")
        return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
