"""
rvol.py — Relative Volume (RVOL) Module for MIA Pipeline
=========================================================

Calcul professionnel du volume relatif, basé sur les méthodes
institutionnelles (RVOL, Z-Score, confirmation delta).

Remplace les signaux SC bn_volume_up/dn (seuil fixe V>400/1200)
par un système adaptatif qui s'ajuste au contexte de marché.

Méthode:
  RVOL = Volume_courant / SMA(Volume, lookback)
  Confirmation = delta_pct aligné + finish_strength

Seuils professionnels:
  < 1.0  = volume faible (pas de conviction)
  1.3-1.8 = participation institutionnelle progressive
  > 2.0  = spike confirmé (signal exploitable)
  > 4.0  = extrême (exhaustion probable)

Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\rvol.py
Schema: 3.6.0+
Auteur: MIA Trading System
Date:   2026-03-12
"""

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

RVOL_LOOKBACK = 20          # Barres pour la SMA volume
RVOL_SPIKE_THRESHOLD = 2.0  # 2x = spike confirmé (consensus pro)
RVOL_EXTREME_THRESHOLD = 4.0  # 4x = exhaustion probable
DELTA_CONFIRM_PCT = 0.10    # Delta doit confirmer à ≥10%
ZSCORE_THRESHOLD = 2.0      # Z-Score ≥ 2.0 = statistiquement significatif

# Sessions à exclure pour le signal (volume de clôture = bruit)
EXCLUDE_AFTER_EDT_HOUR = 15   # Ignorer après 15:50 EDT
EXCLUDE_AFTER_EDT_MIN = 50


# ═══════════════════════════════════════════════════════════════════════
# FEATURES EXPORTÉES
# ═══════════════════════════════════════════════════════════════════════

FEATURES = [
    'rvol',                 # Volume relatif (ratio)
    'rvol_zscore',          # Z-Score du volume
    'rvol_buy',             # Tier 1: RVOL UP (spike + delta>5%)
    'rvol_sell',            # Tier 1: RVOL DN (spike + delta<-5%)
    'rvol_buy_strong',      # Tier 2: RVOL UP confirmé (+ finish aligné)
    'rvol_sell_strong',     # Tier 2: RVOL DN confirmé (+ finish aligné)
    'rvol_absorb_buy',      # Absorption: vendeurs absorbés (delta<0, finish>0)
    'rvol_absorb_sell',     # Absorption: acheteurs absorbés (delta>0, finish<0)
    'rvol_extreme',         # Volume extrême > 4x (bool)
    'rvol_regime',          # 0=low, 1=normal, 2=high, 3=spike, 4=extreme
]


# ═══════════════════════════════════════════════════════════════════════
# CORE
# ═══════════════════════════════════════════════════════════════════════

class RvolEngine:
    """
    Calcule le RVOL et génère les signaux volume directionnels.
    
    Usage:
        engine = RvolEngine()
        df = engine.compute(df)
        # df contient maintenant les colonnes rvol, rvol_zscore, etc.
    """
    
    def __init__(self, lookback=RVOL_LOOKBACK, spike_threshold=RVOL_SPIKE_THRESHOLD,
                 delta_confirm=DELTA_CONFIRM_PCT, zscore_threshold=ZSCORE_THRESHOLD,
                 filter_close=True):
        self.lookback = lookback
        self.spike_threshold = spike_threshold
        self.delta_confirm = delta_confirm
        self.zscore_threshold = zscore_threshold
        self.filter_close = filter_close
    
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ajoute les colonnes RVOL au DataFrame.
        
        Colonnes requises: total_vol, delta_pct, finish_strength
        Colonne optionnelle: ts (pour filtrage session)
        """
        df = df.copy()
        vol = df['total_vol'].astype(float)
        
        # ── 1. RVOL = volume / SMA(volume, lookback) ──
        vol_sma = vol.rolling(self.lookback, min_periods=5).mean()
        vol_std = vol.rolling(self.lookback, min_periods=5).std()
        
        df['rvol'] = np.where(vol_sma > 0, vol / vol_sma, 1.0)
        
        # ── 2. Z-Score = (volume - mean) / std ──
        df['rvol_zscore'] = np.where(
            vol_std > 0,
            (vol - vol_sma) / vol_std,
            0.0
        )
        
        # ── 3. Régime volume ──
        # 0=low (<0.7x), 1=normal (0.7-1.3x), 2=high (1.3-2x), 
        # 3=spike (2-4x), 4=extreme (>4x)
        df['rvol_regime'] = 1  # normal par défaut
        df.loc[df['rvol'] < 0.7, 'rvol_regime'] = 0
        df.loc[df['rvol'] > 1.3, 'rvol_regime'] = 2
        df.loc[df['rvol'] > self.spike_threshold, 'rvol_regime'] = 3
        df.loc[df['rvol'] > RVOL_EXTREME_THRESHOLD, 'rvol_regime'] = 4
        
        # ── 4. Confirmation directionnelle ── 
        # 2 TIERS de signaux:
        #   Tier 1 (rvol_buy/sell): RVOL spike + delta confirme direction (≥5%)
        #   Tier 2 (rvol_buy_strong/sell_strong): Tier 1 + finish aligné
        #   Bonus: rvol_absorb = spike + delta vs finish contradictoires (absorption)
        delta_pct = df['delta_pct'].astype(float)
        finish = df['finish_strength'].astype(float) if 'finish_strength' in df.columns else pd.Series(0, index=df.index)
        
        is_spike = df['rvol'] >= self.spike_threshold
        
        # Tier 1: spike + delta confirme (seuil bas = 5%)
        df['rvol_buy'] = (
            is_spike &
            (delta_pct > 0.05)
        ).astype(int)
        
        df['rvol_sell'] = (
            is_spike &
            (delta_pct < -0.05)
        ).astype(int)
        
        # Tier 2: spike + delta fort (≥10%) + finish aligné
        df['rvol_buy_strong'] = (
            is_spike &
            (delta_pct > self.delta_confirm) &
            (finish > 0)
        ).astype(int)
        
        df['rvol_sell_strong'] = (
            is_spike &
            (delta_pct < -self.delta_confirm) &
            (finish < 0)
        ).astype(int)
        
        # Absorption: spike + delta et finish contradictoires
        # Ex: gros volume vendeur (delta<-5%) mais prix ferme en haut (finish>0)
        #     = acheteurs absorbent les vendeurs
        df['rvol_absorb_buy'] = (
            is_spike &
            (delta_pct < -0.05) &
            (finish > 20)
        ).astype(int)
        
        df['rvol_absorb_sell'] = (
            is_spike &
            (delta_pct > 0.05) &
            (finish < -20)
        ).astype(int)
        
        # ── 5. Extreme (exhaustion warning) ──
        df['rvol_extreme'] = (df['rvol'] >= RVOL_EXTREME_THRESHOLD).astype(int)
        
        # ── 6. Filtre session (optionnel) ──
        # Après 15:50 EDT = volume de clôture, pas un signal actionnable
        if self.filter_close and 'ts' in df.columns:
            ts_s = pd.to_datetime(df['ts'], unit='ms', utc=True)
            # EDT = UTC-4 (pendant DST, ce qui est le cas mars→nov)
            edt_hour = (ts_s.dt.hour - 4) % 24
            edt_min = ts_s.dt.minute
            
            is_close = (
                (edt_hour > EXCLUDE_AFTER_EDT_HOUR) |
                ((edt_hour == EXCLUDE_AFTER_EDT_HOUR) & (edt_min >= EXCLUDE_AFTER_EDT_MIN))
            )
            
            # On garde le rvol brut mais on annule les signaux
            df.loc[is_close, 'rvol_buy'] = 0
            df.loc[is_close, 'rvol_sell'] = 0
        
        return df
    
    def summary(self, df: pd.DataFrame) -> str:
        """Résumé des signaux RVOL pour le rapport bench."""
        n = len(df)
        if n == 0:
            return "  Pas de données"
        
        lines = []
        lines.append(f"  Barres: {n}")
        lines.append(f"  RVOL moyen: {df['rvol'].mean():.2f}")
        lines.append(f"  RVOL max: {df['rvol'].max():.2f}")
        
        # Régimes
        for regime, label in [(0, 'Low'), (1, 'Normal'), (2, 'High'), 
                               (3, 'Spike'), (4, 'Extreme')]:
            count = (df['rvol_regime'] == regime).sum()
            pct = count / n
            lines.append(f"  Régime {label:8s}: {count:>4d}/{n} ({pct:>5.1%})")
        
        # Signaux
        buy_count = df['rvol_buy'].sum()
        sell_count = df['rvol_sell'].sum()
        buy_s = df['rvol_buy_strong'].sum()
        sell_s = df['rvol_sell_strong'].sum()
        abs_b = df['rvol_absorb_buy'].sum()
        abs_s = df['rvol_absorb_sell'].sum()
        lines.append(f"  RVOL BUY (T1):    {buy_count:>3d}/{n} ({buy_count/n:.1%})")
        lines.append(f"  RVOL SELL (T1):   {sell_count:>3d}/{n} ({sell_count/n:.1%})")
        lines.append(f"  RVOL BUY strong:  {buy_s:>3d}/{n} ({buy_s/n:.1%})")
        lines.append(f"  RVOL SELL strong: {sell_s:>3d}/{n} ({sell_s/n:.1%})")
        lines.append(f"  ABSORB BUY:       {abs_b:>3d}/{n} ({abs_b/n:.1%})")
        lines.append(f"  ABSORB SELL:       {abs_s:>3d}/{n} ({abs_s/n:.1%})")
        
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# C++ SNIPPET — À intégrer dans DMP_Reader.h
# ═══════════════════════════════════════════════════════════════════════
#
# // PersistentFloat slots pour RVOL (choisir des slots libres)
# // Slot 130 = vol_sum (somme rolling 20 barres)
# // Slot 131 = vol_count (nombre de barres dans le buffer)
# // Slot 132 = vol_ring[0..19] → slots 132-151
#
# inline float DMP_ComputeRVOL(SCStudyInterfaceRef sc, float total_vol) {
#     const int RING_START = 132;
#     const int LOOKBACK = 20;
#     
#     // Ring buffer dans PersistentFloat
#     int idx = (int)sc.GetPersistentFloat(131) % LOOKBACK;
#     float old_val = sc.GetPersistentFloat(RING_START + idx);
#     
#     // Mettre à jour le ring
#     sc.SetPersistentFloat(RING_START + idx, total_vol);
#     
#     // Mettre à jour la somme
#     float vol_sum = sc.GetPersistentFloat(130) - old_val + total_vol;
#     sc.SetPersistentFloat(130, vol_sum);
#     
#     // Incrémenter le compteur
#     float count = sc.GetPersistentFloat(131) + 1;
#     sc.SetPersistentFloat(131, count);
#     
#     // Calculer RVOL
#     int n = (int)fminf(count, LOOKBACK);
#     if (n < 5) return 1.0f;  // Pas assez de données
#     
#     float vol_avg = vol_sum / n;
#     if (vol_avg <= 0) return 1.0f;
#     
#     return total_vol / vol_avg;
# }
#
# // Dans DMP_FillFlatRow():
# //   f.rvol = DMP_ComputeRVOL(sc, d.total_vol);
# //   f.rvol_buy = (f.rvol >= 2.0f && d.delta_pct > 0.10f && d.finish_strength > 0) ? 1.0f : 0.0f;
# //   f.rvol_sell = (f.rvol >= 2.0f && d.delta_pct < -0.10f && d.finish_strength < 0) ? 1.0f : 0.0f;


# ═══════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json
    import sys
    import glob
    
    # Chercher les JSONL
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    files = sorted(glob.glob(f"{base}/*.jsonl"))
    
    if not files:
        print(f"❌ Aucun .jsonl trouvé dans {base}")
        sys.exit(1)
    
    engine = RvolEngine()
    
    for path in files:
        lines = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
        
        if not lines:
            continue
        
        df = pd.DataFrame(lines)
        sym = df.iloc[0].get('sym', '?')
        
        print(f"\n{'='*60}")
        print(f"  {sym} — {path} ({len(df)} barres)")
        print(f"{'='*60}")
        
        df = engine.compute(df)
        print(engine.summary(df))
        
        # Afficher les signaux
        buys = df[df['rvol_buy'] == 1]
        sells = df[df['rvol_sell'] == 1]
        
        if len(buys) > 0:
            print(f"\n  🟢 RVOL BUY signals:")
            for _, r in buys.iterrows():
                from datetime import datetime, timezone
                ts = datetime.fromtimestamp(r['ts']/1000, tz=timezone.utc)
                edt_h = (ts.hour - 4) % 24
                print(f"    {edt_h}:{ts.strftime('%M')} EDT | px={r['price']:.2f} | "
                      f"rvol={r['rvol']:.1f}x | delta={r['delta_pct']:+.1%} | "
                      f"vol={r['total_vol']:.0f} | finish={r['finish_strength']:.0f}")
        
        if len(sells) > 0:
            print(f"\n  🔴 RVOL SELL signals:")
            for _, r in sells.iterrows():
                from datetime import datetime, timezone
                ts = datetime.fromtimestamp(r['ts']/1000, tz=timezone.utc)
                edt_h = (ts.hour - 4) % 24
                print(f"    {edt_h}:{ts.strftime('%M')} EDT | px={r['price']:.2f} | "
                      f"rvol={r['rvol']:.1f}x | delta={r['delta_pct']:+.1%} | "
                      f"vol={r['total_vol']:.0f} | finish={r['finish_strength']:.0f}")
        
        if len(buys) == 0 and len(sells) == 0:
            print(f"\n  Aucun signal RVOL confirmé (filtrage clôture actif)")
        
        # Comparaison avec les signaux SC
        sc_up = (df['bn_volume_up'] > 0).sum() if 'bn_volume_up' in df.columns else 0
        sc_dn = (df['bn_volume_dn'] > 0).sum() if 'bn_volume_dn' in df.columns else 0
        print(f"\n  Comparaison SC vs RVOL:")
        print(f"    SC bn_volume_up:  {sc_up:>3d}  →  RVOL buy:  {len(buys):>3d}")
        print(f"    SC bn_volume_dn:  {sc_dn:>3d}  →  RVOL sell: {len(sells):>3d}")
