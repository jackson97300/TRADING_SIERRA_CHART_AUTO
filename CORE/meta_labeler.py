"""
meta_labeler.py — Meta-Labeling pour MIA V2
=============================================

Architecture a 2 niveaux (Lopez de Prado, Advances in Financial ML, ch.3) :

    NIVEAU 1 — Primary Model
        LightGBM deja existant dans train_lightgbm.py
        Features : 100-126 colonnes DMP
        Sortie   : p_primary (probabilite de direction buy/sell correcte)
        Seuil    : BAS (pour ne rater aucune opportunite)

    NIVEAU 2 — Meta Model (CE MODULE)
        LightGBM binaire SEPARE
        Features : [p_primary, subset contextuel : session, regime, volatilite, ...]
                  NE PREND PAS les 100-126 features du primary (redondance dangereuse)
        Label    : 1 si le trade primaire est profitable (TP touche), 0 sinon
        Seuil    : HAUT (filtre les faux positifs du primary)

    DECISION FINALE
        score_final = p_primary x p_meta
        size = Half-Kelly x p_meta (Lopez ch.10 : proportionnel a la confiance)

Pourquoi c'est l'INVERSE architectural du systeme V1 :
    V1 = 8 gates rule-based cascading + seuils manuels par symbole par session
         → overfit de chaque gate individuellement, interactions non monitorees
    V2 = 2 modeles ML qui APPRENNENT leurs seuils depuis les donnees
         → regularisation globale, interactions captees automatiquement

Reference academique : Lopez de Prado, AFML 2018, Ch.3 "Labeling".
Validation empirique : Hudson & Thames "Does Meta-Labeling Add to Signal Efficacy".

Auteur : MIA Trading System
Date   : 2026-04-12
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Features contextuelles par defaut pour le meta model.
# NOTE : ces features doivent etre DIFFERENTES de celles utilisees par le primary
# pour eviter la redondance. Idealement : contexte macro (regime, game changers),
# pas de micro (OrderFlow tick-level qui est deja dans le primary).
#
# MISE A JOUR 13/04/2026 : post-Phase 1 save-or-drop + WHITELIST_BYPASS.
# Les anciennes features (ctx_dist_vwap_velocity, ctx_vwap_slope_accel,
# ctx_price_slope_5) ont ete droppees (fuite volatilite non normalisees).
# Remplacees par les Game Changers (open_type, profile_shape) qui sont
# des signaux non-monotones que le primary ne capte pas bien.
#
# Jackson 13/04 : "open_type aussi serait bien de l'integrer"
DEFAULT_META_CONTEXT_FEATURES = [
    # Game Changers — Open Type / Day Type (Dalton / Steidlmayer)
    # Signaux categoriels du debut de journee qui definissent le contexte
    "open_type",                # 0-5 Dalton open type (Drive, Test Drive, Rejection Reverse, Auction)
    "open_bias_conf",           # [0,1] confiance biais open
    "day_type",                 # 0-4 day type Steidlmayer
    "trend_day_probability",    # [0,1] prob que ce soit une trend day
    "profile_shape",            # 0=D / 1=P / 2=b / 3=B

    # Intermarket ES/NQ (contexte cross-asset)
    "im_rolling_correlation_10",    # correlation rolling ES/NQ
    "im_cross_delta_agreement_5",   # delta agreement cross-instrument
    "im_open_type_agreement",       # agreement open type ES/NQ

    # Regime volatilite
    "vix_regime",               # 0/1/2 regime VIX
    "ib_range_atr",             # IB normalisee (narrow vs wide)
]


@dataclass
class MetaLabelConfig:
    """Configuration du meta-labeling."""

    # Seuil du primary : en-dessous, on ne declenche pas le meta (HOLD direct)
    # Plus bas = plus de candidats pour le meta = plus de filtrage possible
    primary_threshold: float = 0.30

    # Features contextuelles du meta model (independantes du primary)
    context_features: List[str] = field(
        default_factory=lambda: DEFAULT_META_CONTEXT_FEATURES.copy()
    )

    # LightGBM hyperparams — volontairement conservateurs (meta = petit dataset)
    num_leaves: int = 15
    max_depth: int = 4
    learning_rate: float = 0.05
    n_estimators: int = 200
    min_child_samples: int = 20
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_alpha: float = 0.1
    reg_lambda: float = 0.1

    # Nombre min d'echantillons pour entrainer le meta
    min_meta_samples: int = 50


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DES LABELS META
# ═══════════════════════════════════════════════════════════════════════════════

def build_meta_labels(
    labels: pd.Series,
    primary_preds: np.ndarray,
    primary_threshold: float,
    target_label: int = 1,
) -> pd.Series:
    """
    Construit les labels binaires pour le meta model.

    Logique :
        - Le primary predit un trade (p_primary > threshold)
        - On verifie si ce trade etait effectivement profitable (label reel == target_label)
        - y_meta = 1 si prediction + label reel coherents
        - y_meta = 0 si prediction sans validation reelle (faux positif du primary)
        - y_meta = NaN (exclu) si le primary n'a pas predit de trade

    Args:
        labels           : pd.Series int8, labels Triple Barrier (+1/-1/0)
        primary_preds    : np.ndarray, probabilites du primary model
        primary_threshold: float, seuil minimal du primary pour considerer le signal
        target_label     : int, 1 pour buy model, -1 pour sell model

    Returns:
        pd.Series avec valeurs {0, 1, NaN}, nom='meta_label'
    """
    if len(labels) != len(primary_preds):
        raise ValueError(
            f"labels et primary_preds ont des tailles differentes : "
            f"{len(labels)} vs {len(primary_preds)}"
        )

    labels_arr = labels.values
    active = primary_preds > primary_threshold
    correct = labels_arr == target_label

    # y_meta = 1 si primary active ET label reel correspond
    # y_meta = 0 si primary active MAIS label reel != target
    # y_meta = NaN si primary inactif (exclu du training meta)
    y_meta = np.where(
        active,
        correct.astype(float),
        np.nan,
    )

    return pd.Series(y_meta, index=labels.index, name='meta_label', dtype=np.float64)


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DES FEATURES META
# ═══════════════════════════════════════════════════════════════════════════════

def build_meta_features(
    df: pd.DataFrame,
    primary_preds: np.ndarray,
    context_features: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Construit le DataFrame de features pour le meta model.

    Regle d'or : les features du meta doivent etre DIFFERENTES de celles du primary.
    Si le meta voit les memes features que le primary, il va reapprendre la meme
    fonction et n'ajoutera aucune information.

    Features meta typiques :
      - p_primary                    (confiance du primary lui-meme)
      - Context (session, regime, volatilite)
      - Pas de micro-features (bn_*, delta_*, OrderFlow detaille qui est deja
        dans le primary)

    Args:
        df               : DataFrame complet avec les colonnes features
        primary_preds    : np.ndarray probabilites du primary
        context_features : liste de colonnes a utiliser comme contexte.
                          None = utilise DEFAULT_META_CONTEXT_FEATURES.

    Returns:
        pd.DataFrame avec les colonnes [p_primary, <context_features dispo>]
    """
    if context_features is None:
        context_features = DEFAULT_META_CONTEXT_FEATURES

    # Ne garder que les colonnes qui existent reellement dans le df
    available = [c for c in context_features if c in df.columns]
    missing = [c for c in context_features if c not in df.columns]

    # Garde-fou : si AUCUNE feature de contexte n'est disponible, le meta model
    # tournerait avec uniquement p_primary comme input — inutile (il reapprendrait
    # juste une transformation monotone du primary).
    if not available:
        raise ValueError(
            f"Aucune des features meta par defaut n'est presente dans le DataFrame. "
            f"Features demandees : {context_features}. "
            f"Colonnes disponibles (extrait) : {list(df.columns)[:20]}... "
            f"Solution : passer un `context_features` explicite adapte a ton dataset."
        )

    if missing:
        import warnings
        warnings.warn(
            f"Features meta manquantes (non-bloquant, sera ignore) : {missing}. "
            f"Features utilisees : {available}",
            RuntimeWarning,
        )

    X_meta = df[available].copy()
    X_meta['p_primary'] = primary_preds

    return X_meta


# ═══════════════════════════════════════════════════════════════════════════════
# META MODEL (LightGBM binaire)
# ═══════════════════════════════════════════════════════════════════════════════

class MetaModel:
    """
    Meta-labeling model — LightGBM binaire au-dessus d'un primary model existant.

    Usage type :
        # 1. Entrainer le primary (deja fait dans train_lightgbm.py)
        primary = lgb.LGBMClassifier(...).fit(X_primary, y_primary_direction)
        p_primary = primary.predict_proba(X_primary_test)[:, 1]

        # 2. Construire le meta dataset
        y_meta   = build_meta_labels(y_primary_direction, p_primary, threshold=0.30)
        X_meta   = build_meta_features(df, p_primary)

        # 3. Entrainer le meta model
        meta = MetaModel(MetaLabelConfig())
        meta.fit(X_meta, y_meta)

        # 4. Prediction combinee
        p_final = meta.predict_combined(p_primary_new, X_meta_new)
        # Trade si p_final > seuil_decision
        # Size = Half-Kelly * p_meta_new (confiance sur le trade)
    """

    def __init__(self, config: Optional[MetaLabelConfig] = None):
        if not HAS_LIGHTGBM:
            raise ImportError(
                "lightgbm non installe. pip install lightgbm"
            )
        self.config = config or MetaLabelConfig()
        self.model: Optional[lgb.LGBMClassifier] = None
        self.feature_names: List[str] = []

    def fit(
        self,
        X_meta: pd.DataFrame,
        y_meta: pd.Series,
        sample_weight: Optional[np.ndarray] = None,
    ) -> 'MetaModel':
        """
        Entraine le meta model sur les echantillons valides (y_meta != NaN).

        Les echantillons NaN (primary inactif) sont filtres automatiquement :
        le meta n'a rien a apprendre sur eux puisqu'ils ne declencheront jamais
        de trade.
        """
        # Filtrer les NaN (primary n'a pas predit)
        mask = ~y_meta.isna()
        X = X_meta.loc[mask].copy()
        y = y_meta.loc[mask].astype(int).values

        if len(y) < self.config.min_meta_samples:
            raise ValueError(
                f"Pas assez d'echantillons pour entrainer le meta : "
                f"{len(y)} < {self.config.min_meta_samples}. "
                f"Baisser primary_threshold ou collecter plus de data."
            )

        # Check qu'on a au moins 2 classes (sinon LightGBM explose)
        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            raise ValueError(
                f"Meta labels ont une seule classe : {unique_classes}. "
                f"Primary est trop selectif OU label distribution trop skewed."
            )

        sw = None
        if sample_weight is not None:
            sw_arr = np.asarray(sample_weight)
            if len(sw_arr) != len(mask):
                raise ValueError(
                    f"sample_weight taille {len(sw_arr)} != labels taille {len(mask)}"
                )
            sw = sw_arr[mask.values]

        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "verbosity": -1,
            "seed": 42,
            "num_leaves": self.config.num_leaves,
            "max_depth": self.config.max_depth,
            "learning_rate": self.config.learning_rate,
            "n_estimators": self.config.n_estimators,
            "min_child_samples": self.config.min_child_samples,
            "subsample": self.config.subsample,
            "colsample_bytree": self.config.colsample_bytree,
            "reg_alpha": self.config.reg_alpha,
            "reg_lambda": self.config.reg_lambda,
            "is_unbalance": True,
        }

        self.model = lgb.LGBMClassifier(**params)
        if sw is not None:
            self.model.fit(X, y, sample_weight=sw)
        else:
            self.model.fit(X, y)

        self.feature_names = list(X.columns)
        return self

    def predict_proba(self, X_meta: pd.DataFrame) -> np.ndarray:
        """
        Retourne p_meta : probabilite que le trade primaire soit profitable
        conditionnellement aux features de contexte.
        """
        if self.model is None:
            raise RuntimeError("MetaModel pas encore entraine — appeler fit() d'abord")

        # Reordonner les colonnes selon self.feature_names (robustesse)
        missing = [c for c in self.feature_names if c not in X_meta.columns]
        if missing:
            raise ValueError(f"Colonnes manquantes pour predict : {missing}")
        X = X_meta[self.feature_names]

        return self.model.predict_proba(X)[:, 1]

    def predict_combined(
        self,
        p_primary: np.ndarray,
        X_meta: pd.DataFrame,
    ) -> np.ndarray:
        """
        Score final combine : p_primary * p_meta.

        Usage :
          - Comparer a un seuil de decision pour declencher le trade
          - Utiliser comme input au bet sizing (Half-Kelly * p_meta)
        """
        p_meta = self.predict_proba(X_meta)
        return p_primary * p_meta

    def feature_importance(self) -> pd.DataFrame:
        """Retourne l'importance des features du meta model (MDI native LightGBM)."""
        if self.model is None:
            raise RuntimeError("MetaModel pas encore entraine")
        return pd.DataFrame({
            'feature': self.feature_names,
            'importance': self.model.feature_importances_,
        }).sort_values('importance', ascending=False).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST INLINE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test synthetique rapide pour valider que le skeleton fonctionne
    print("=== Test meta_labeler.py ===")

    np.random.seed(42)
    n = 500

    # Simule un DataFrame avec des features de contexte + labels
    df_test = pd.DataFrame({
        'ctx_session_phase': np.random.choice([1, 2, 3], n),
        'ctx_regime_class': np.random.choice([0, 1, 2], n),
        'atr': np.random.uniform(5, 30, n),
        'rvol_relative': np.random.uniform(0.5, 2.5, n),
        'im_rolling_corr_5': np.random.uniform(-1, 1, n),
    })

    # Simule des labels Triple Barrier (+1/-1/0)
    labels = pd.Series(np.random.choice([-1, 0, 1], n, p=[0.2, 0.6, 0.2]), dtype=np.int8)

    # Simule des predictions primary (probabilites buy = label==1)
    # Avec un peu de correlation avec les vrais labels pour etre realiste
    primary_preds = np.where(
        labels.values == 1,
        np.random.uniform(0.4, 0.8, n),
        np.random.uniform(0.1, 0.6, n),
    )

    # 1. Build meta labels
    y_meta = build_meta_labels(labels, primary_preds, primary_threshold=0.30, target_label=1)
    print(f"\n[1] build_meta_labels:")
    print(f"    Total echantillons : {len(y_meta)}")
    print(f"    Non-NaN (primary actif) : {(~y_meta.isna()).sum()}")
    print(f"    y_meta == 1 : {(y_meta == 1).sum()}")
    print(f"    y_meta == 0 : {(y_meta == 0).sum()}")
    print(f"    y_meta == NaN : {y_meta.isna().sum()}")

    # 2. Build meta features
    X_meta = build_meta_features(df_test, primary_preds,
                                  context_features=['ctx_session_phase', 'ctx_regime_class',
                                                    'atr', 'rvol_relative', 'im_rolling_corr_5'])
    print(f"\n[2] build_meta_features:")
    print(f"    Shape : {X_meta.shape}")
    print(f"    Columns : {list(X_meta.columns)}")

    # 3. Train meta model
    if HAS_LIGHTGBM:
        cfg = MetaLabelConfig(min_meta_samples=20)  # Seuil bas pour le test
        meta = MetaModel(cfg)
        try:
            meta.fit(X_meta, y_meta)
            print(f"\n[3] MetaModel.fit:")
            print(f"    Training samples : {(~y_meta.isna()).sum()}")
            print(f"    Feature names : {meta.feature_names}")

            # 4. Predict proba
            p_meta = meta.predict_proba(X_meta)
            print(f"\n[4] MetaModel.predict_proba:")
            print(f"    p_meta range : [{p_meta.min():.3f}, {p_meta.max():.3f}]")
            print(f"    p_meta mean  : {p_meta.mean():.3f}")

            # 5. Combined score
            p_final = meta.predict_combined(primary_preds, X_meta)
            print(f"\n[5] predict_combined:")
            print(f"    p_final range : [{p_final.min():.3f}, {p_final.max():.3f}]")
            print(f"    p_final mean  : {p_final.mean():.3f}")

            # 6. Feature importance
            fi = meta.feature_importance()
            print(f"\n[6] feature_importance:")
            print(fi.to_string(index=False))

            print(f"\n=== TOUS LES TESTS INLINE PASSENT ===")
        except Exception as e:
            print(f"\nERREUR fit/predict : {type(e).__name__}: {e}")
            raise
    else:
        print("\n[SKIP] lightgbm non installe — tests fit/predict skippes")
