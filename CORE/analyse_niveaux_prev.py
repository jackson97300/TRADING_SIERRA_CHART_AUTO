"""
Analyse des niveaux Previous Day + Clusters + Open Type + Combinaisons BN
Objectif : trouver des regles de trading discretionnaires validees par les donnees.

Auteur : MIA Feature Engineer
Date   : 2026-04-02
"""

import sys, os, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/TRADING_SIERRA_CHART_AUTO/CORE')

import pandas as pd
import numpy as np
from dmp_reader import DmpReader

# =============================================================================
# CHARGEMENT
# =============================================================================
reader = DmpReader('D:/TRADING_SIERRA_CHART_AUTO/DATA')
dates = ['2026-03-29', '2026-03-30', '2026-03-31', '2026-04-01', '2026-04-02']

frames = []
for sym in ['ES', 'NQ']:
    for d in dates:
        df = reader.load(sym, d)
        if not df.empty:
            df['symbol'] = sym
            frames.append(df)

if not frames:
    print("ERREUR: aucune donnee chargee")
    sys.exit(1)

raw = pd.concat(frames, ignore_index=True)
print(f"Donnees brutes chargees: {len(raw)} barres")

# Filtre US only
if 'session' in raw.columns:
    df = raw[raw['session'] == 2].copy()
elif 'session_id' in raw.columns:
    df = raw[raw['session_id'] == 'US'].copy()
else:
    df = raw.copy()

print(f"Session US: {len(df)} barres")
print(f"Symboles: {df['symbol'].value_counts().to_dict()}")

# Forcer numerique sur les colonnes dist_* et bn_*
num_cols = [c for c in df.columns if c.startswith('dist_') or c.startswith('bn_')
            or c.startswith('va_') or c == 'bar_close' or c == 'bar_high' or c == 'bar_low'
            or c == 'price']
for c in num_cols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors='coerce')

# =============================================================================
# LABELING : +20t avant -20t = BUY WIN, -20t avant +20t = SELL WIN
# =============================================================================
TICK_SIZE = 0.25  # ES et NQ
MOVE_TICKS = 20
HORIZON = 20  # barres

def label_future_move(group, tick_size=0.25, move_ticks=20, horizon=20):
    """Pour chaque barre, regarde les N barres suivantes.
    Si +move_ticks atteint avant -move_ticks => BUY_WIN
    Si -move_ticks atteint avant +move_ticks => SELL_WIN
    Sinon => NEUTRAL
    """
    prices = group['bar_close'].values if 'bar_close' in group.columns else group['price'].values
    prices = prices.astype(float)
    n = len(prices)
    labels = np.full(n, 0, dtype=int)  # 0=neutral, 1=buy_win, -1=sell_win

    move_pts = move_ticks * tick_size

    for i in range(n):
        ref = prices[i]
        for j in range(i+1, min(i+horizon+1, n)):
            up = prices[j] - ref
            dn = ref - prices[j]
            if up >= move_pts:
                labels[i] = 1  # BUY WIN
                break
            elif dn >= move_pts:
                labels[i] = -1  # SELL WIN
                break
    return labels

# Label par jour et symbole
print("\nLabeling (+/-20 ticks, horizon 20 barres)...")
df['label'] = 0

# Grouper par date + symbole
if 'datetime_et' in df.columns:
    df['date_str'] = pd.to_datetime(df['datetime_et']).dt.date.astype(str)
elif 'ts' in df.columns:
    df['date_str'] = pd.to_datetime(df['ts']).dt.date.astype(str)
else:
    df['date_str'] = 'unknown'

for (sym, dt), grp in df.groupby(['symbol', 'date_str']):
    idx = grp.index
    labels = label_future_move(grp)
    df.loc[idx, 'label'] = labels

label_counts = df['label'].value_counts()
print(f"Labels: BUY_WIN={label_counts.get(1,0)}, SELL_WIN={label_counts.get(-1,0)}, NEUTRAL={label_counts.get(0,0)}")

# =============================================================================
# 1. NIVEAUX PREVIOUS DAY
# =============================================================================
print("\n" + "="*80)
print("1. NIVEAUX PREVIOUS DAY")
print("="*80)

prev_cols = [c for c in df.columns if 'prev' in c.lower() and c.startswith('dist_')]
print(f"\nColonnes previous trouvees ({len(prev_cols)}):")
for c in prev_cols:
    vals = pd.to_numeric(df[c], errors='coerce')
    non_null = vals.notna().sum()
    print(f"  {c}: non-null={non_null}, mean={vals.mean():.2f}, std={vals.std():.2f}")

# Analyse proximite niveaux previous
print("\n--- Proximite niveaux previous (|dist| < seuil en ticks) ---")

for col in prev_cols:
    vals = pd.to_numeric(df[col], errors='coerce')
    level_name = col.replace('dist_prev_', '').replace('dist_', '')

    for threshold in [3, 5]:
        mask = vals.abs() < threshold
        n_close = mask.sum()
        if n_close < 5:
            continue

        sub = df[mask]
        buy_win = (sub['label'] == 1).sum()
        sell_win = (sub['label'] == -1).sum()
        neutral = (sub['label'] == 0).sum()
        total_decided = buy_win + sell_win

        if total_decided == 0:
            continue

        buy_wr = buy_win / total_decided * 100
        sell_wr = sell_win / total_decided * 100

        print(f"\n  {col} |< {threshold}t : {n_close} barres")
        print(f"    BUY WR: {buy_wr:.1f}% ({buy_win}/{total_decided})")
        print(f"    SELL WR: {sell_wr:.1f}% ({sell_win}/{total_decided})")

        # Direction attendue
        if 'vah' in col:
            print(f"    [EXPECTED SHORT] -> Sell WR {sell_wr:.1f}%")
        elif 'val' in col:
            print(f"    [EXPECTED LONG] -> Buy WR {buy_wr:.1f}%")
        elif 'vpoc' in col:
            print(f"    [MEAN REVERSION] -> bias neutre, best={('BUY' if buy_wr > sell_wr else 'SELL')} {max(buy_wr, sell_wr):.1f}%")

# =============================================================================
# 2. OPEN TYPE
# =============================================================================
print("\n" + "="*80)
print("2. OPEN TYPE")
print("="*80)

if 'open_type' in df.columns:
    for ot_val in sorted(df['open_type'].dropna().unique()):
        sub = df[df['open_type'] == ot_val]
        n_bars = len(sub)
        buy_win = (sub['label'] == 1).sum()
        sell_win = (sub['label'] == -1).sum()
        total_decided = buy_win + sell_win

        if total_decided == 0:
            print(f"\n  OT={ot_val}: {n_bars} barres, 0 trades decides")
            continue

        buy_wr = buy_win / total_decided * 100
        sell_wr = sell_win / total_decided * 100
        print(f"\n  OT={ot_val}: {n_bars} barres")
        print(f"    BUY WR: {buy_wr:.1f}% ({buy_win}), SELL WR: {sell_wr:.1f}% ({sell_win})")
        print(f"    Bias: {'BUY' if buy_wr > sell_wr else 'SELL'} ({max(buy_wr, sell_wr):.1f}%)")
else:
    print("  Colonne open_type non trouvee")

# =============================================================================
# 3. CLUSTERS DE NIVEAUX
# =============================================================================
print("\n" + "="*80)
print("3. CLUSTERS DE NIVEAUX (3+ dist_* < 5 ticks simultanement)")
print("="*80)

dist_cols = [c for c in df.columns if c.startswith('dist_') and c != 'date_str']
print(f"\nColonnes dist_ utilisees: {len(dist_cols)}")

# Compter combien de dist_* sont < 5 ticks par barre
dist_df = df[dist_cols].apply(pd.to_numeric, errors='coerce')
close_count = (dist_df.abs() < 5).sum(axis=1)
df['n_levels_close'] = close_count

print("\nDistribution du nb de niveaux proches (|dist| < 5t):")
for n_lvl in sorted(close_count.unique()):
    cnt = (close_count == n_lvl).sum()
    if cnt > 0:
        print(f"  {n_lvl} niveaux: {cnt} barres ({cnt/len(df)*100:.1f}%)")

# Analyse WR pour clusters >= 3, >= 5, >= 7
for min_cluster in [3, 5, 7, 10]:
    mask = close_count >= min_cluster
    n_cluster = mask.sum()
    if n_cluster < 5:
        continue

    sub = df[mask]
    buy_win = (sub['label'] == 1).sum()
    sell_win = (sub['label'] == -1).sum()
    total_decided = buy_win + sell_win

    if total_decided == 0:
        continue

    buy_wr = buy_win / total_decided * 100
    sell_wr = sell_win / total_decided * 100
    print(f"\n  Cluster >= {min_cluster} niveaux: {n_cluster} barres")
    print(f"    BUY WR: {buy_wr:.1f}% ({buy_win}), SELL WR: {sell_wr:.1f}% ({sell_win})")

# Quels niveaux sont les plus souvent dans les clusters?
print("\n--- Top niveaux les plus souvent proches (< 5t) ---")
close_freq = (dist_df.abs() < 5).sum().sort_values(ascending=False)
for col, freq in close_freq.head(20).items():
    print(f"  {col}: {freq} barres ({freq/len(df)*100:.1f}%)")

# =============================================================================
# 4. VA POSITION + PREVIOUS
# =============================================================================
print("\n" + "="*80)
print("4. VA POSITION + PREVIOUS LEVELS")
print("="*80)

if 'va_position_pct' in df.columns:
    va_pos = pd.to_numeric(df['va_position_pct'], errors='coerce')

    # VA > 0.8 + proche prev_vah => short
    for prev_col in prev_cols:
        if 'vah' in prev_col:
            dist_prev = pd.to_numeric(df[prev_col], errors='coerce')
            mask = (va_pos > 0.8) & (dist_prev.abs() < 5)
            n = mask.sum()
            if n < 3: continue
            sub = df[mask]
            buy_win = (sub['label'] == 1).sum()
            sell_win = (sub['label'] == -1).sum()
            td = buy_win + sell_win
            if td == 0: continue
            print(f"\n  va_pos > 0.8 AND |{prev_col}| < 5t: {n} barres")
            print(f"    SELL WR: {sell_win/td*100:.1f}% ({sell_win}/{td}) [SHORT expected]")
            print(f"    BUY WR: {buy_win/td*100:.1f}% ({buy_win}/{td})")

    # VA < 0.2 + proche prev_val => long
    for prev_col in prev_cols:
        if 'val' in prev_col:
            dist_prev = pd.to_numeric(df[prev_col], errors='coerce')
            mask = (va_pos < 0.2) & (dist_prev.abs() < 5)
            n = mask.sum()
            if n < 3: continue
            sub = df[mask]
            buy_win = (sub['label'] == 1).sum()
            sell_win = (sub['label'] == -1).sum()
            td = buy_win + sell_win
            if td == 0: continue
            print(f"\n  va_pos < 0.2 AND |{prev_col}| < 5t: {n} barres")
            print(f"    BUY WR: {buy_win/td*100:.1f}% ({buy_win}/{td}) [LONG expected]")
            print(f"    SELL WR: {sell_win/td*100:.1f}% ({sell_win}/{td})")
else:
    print("  va_position_pct non trouve")

# =============================================================================
# 5. BN ABSORB + PREVIOUS
# =============================================================================
print("\n" + "="*80)
print("5. BN ABSORB + PREVIOUS LEVELS")
print("="*80)

bn_absorb_cols = [c for c in df.columns if 'bn_absorb' in c]
print(f"Colonnes bn_absorb: {bn_absorb_cols}")

for bn_col in bn_absorb_cols:
    bn_vals = pd.to_numeric(df[bn_col], errors='coerce')
    if bn_vals.std() < 1e-6:
        print(f"  {bn_col}: MORTE (std={bn_vals.std():.8f})")
        continue

    # Seuil = percentile 80
    threshold = bn_vals.quantile(0.80)
    if threshold < 1e-6:
        threshold = bn_vals.quantile(0.90)

    print(f"\n  {bn_col}: mean={bn_vals.mean():.2f}, P80={threshold:.2f}")

    for prev_col in prev_cols:
        dist_prev = pd.to_numeric(df[prev_col], errors='coerce')
        mask = (bn_vals >= threshold) & (dist_prev.abs() < 5)
        n = mask.sum()
        if n < 5:
            continue

        sub = df[mask]
        buy_win = (sub['label'] == 1).sum()
        sell_win = (sub['label'] == -1).sum()
        td = buy_win + sell_win
        if td == 0: continue

        buy_wr = buy_win / td * 100
        sell_wr = sell_win / td * 100
        best_dir = 'BUY' if buy_wr > sell_wr else 'SELL'
        best_wr = max(buy_wr, sell_wr)

        if best_wr >= 55:  # Seuil d'interet
            print(f"    + {prev_col} < 5t: {n} barres -> {best_dir} {best_wr:.1f}% ({td} trades)")

# =============================================================================
# 6. TOP REGLES - SCORING COMPLET
# =============================================================================
print("\n" + "="*80)
print("6. TOP REGLES - RECHERCHE EXHAUSTIVE")
print("="*80)

# Generer des regles candidates
rules = []

# Regle type 1: Proche d'un previous level seul
for col in prev_cols:
    vals = pd.to_numeric(df[col], errors='coerce')
    for thresh in [3, 5]:
        for direction in ['BUY', 'SELL']:
            mask = vals.abs() < thresh
            n = mask.sum()
            if n < 10: continue
            sub = df[mask]
            if direction == 'BUY':
                wins = (sub['label'] == 1).sum()
                losses = (sub['label'] == -1).sum()
            else:
                wins = (sub['label'] == -1).sum()
                losses = (sub['label'] == 1).sum()
            td = wins + losses
            if td < 5: continue
            wr = wins / td * 100
            pf = wins / max(losses, 1)
            ev = (wins * 20 - losses * 20) / td  # EV en ticks (TP=SL=20t)
            rules.append({
                'rule': f"|{col}| < {thresh}t -> {direction}",
                'signals': n,
                'trades': td,
                'wins': wins,
                'losses': losses,
                'wr': wr,
                'pf': pf,
                'ev_ticks': ev,
            })

# Regle type 2: VA position + previous
if 'va_position_pct' in df.columns:
    va_pos = pd.to_numeric(df['va_position_pct'], errors='coerce')
    for prev_col in prev_cols:
        dist_prev = pd.to_numeric(df[prev_col], errors='coerce')

        # High VA + prev_vah -> SHORT
        mask = (va_pos > 0.8) & (dist_prev.abs() < 5)
        n = mask.sum()
        if n >= 5:
            sub = df[mask]
            for direction in ['BUY', 'SELL']:
                wins = (sub['label'] == (1 if direction == 'BUY' else -1)).sum()
                losses = (sub['label'] == (-1 if direction == 'BUY' else 1)).sum()
                td = wins + losses
                if td < 3: continue
                wr = wins / td * 100
                pf = wins / max(losses, 1)
                ev = (wins * 20 - losses * 20) / td
                rules.append({
                    'rule': f"va_pos>0.8 AND |{prev_col}|<5t -> {direction}",
                    'signals': n, 'trades': td, 'wins': wins, 'losses': losses,
                    'wr': wr, 'pf': pf, 'ev_ticks': ev,
                })

        # Low VA + prev_val -> LONG
        mask = (va_pos < 0.2) & (dist_prev.abs() < 5)
        n = mask.sum()
        if n >= 5:
            sub = df[mask]
            for direction in ['BUY', 'SELL']:
                wins = (sub['label'] == (1 if direction == 'BUY' else -1)).sum()
                losses = (sub['label'] == (-1 if direction == 'BUY' else 1)).sum()
                td = wins + losses
                if td < 3: continue
                wr = wins / td * 100
                pf = wins / max(losses, 1)
                ev = (wins * 20 - losses * 20) / td
                rules.append({
                    'rule': f"va_pos<0.2 AND |{prev_col}|<5t -> {direction}",
                    'signals': n, 'trades': td, 'wins': wins, 'losses': losses,
                    'wr': wr, 'pf': pf, 'ev_ticks': ev,
                })

# Regle type 3: Cluster + direction label
for min_c in [5, 7, 10]:
    mask = df['n_levels_close'] >= min_c
    n = mask.sum()
    if n < 10: continue
    sub = df[mask]
    for direction in ['BUY', 'SELL']:
        wins = (sub['label'] == (1 if direction == 'BUY' else -1)).sum()
        losses = (sub['label'] == (-1 if direction == 'BUY' else 1)).sum()
        td = wins + losses
        if td < 5: continue
        wr = wins / td * 100
        pf = wins / max(losses, 1)
        ev = (wins * 20 - losses * 20) / td
        rules.append({
            'rule': f"cluster>={min_c} niveaux -> {direction}",
            'signals': n, 'trades': td, 'wins': wins, 'losses': losses,
            'wr': wr, 'pf': pf, 'ev_ticks': ev,
        })

# Regle type 4: BN absorb eleve + previous level
for bn_col in bn_absorb_cols:
    bn_vals = pd.to_numeric(df[bn_col], errors='coerce')
    if bn_vals.std() < 1e-6: continue
    threshold = bn_vals.quantile(0.80)
    if threshold < 1e-6: threshold = bn_vals.quantile(0.90)

    for prev_col in prev_cols:
        dist_prev = pd.to_numeric(df[prev_col], errors='coerce')
        mask = (bn_vals >= threshold) & (dist_prev.abs() < 5)
        n = mask.sum()
        if n < 5: continue
        sub = df[mask]
        for direction in ['BUY', 'SELL']:
            wins = (sub['label'] == (1 if direction == 'BUY' else -1)).sum()
            losses = (sub['label'] == (-1 if direction == 'BUY' else 1)).sum()
            td = wins + losses
            if td < 3: continue
            wr = wins / td * 100
            pf = wins / max(losses, 1)
            ev = (wins * 20 - losses * 20) / td
            rules.append({
                'rule': f"{bn_col}>=P80 AND |{prev_col}|<5t -> {direction}",
                'signals': n, 'trades': td, 'wins': wins, 'losses': losses,
                'wr': wr, 'pf': pf, 'ev_ticks': ev,
            })

# Regle type 5: Open type + previous level
if 'open_type' in df.columns:
    for ot_val in df['open_type'].dropna().unique():
        for prev_col in prev_cols:
            dist_prev = pd.to_numeric(df[prev_col], errors='coerce')
            mask = (df['open_type'] == ot_val) & (dist_prev.abs() < 5)
            n = mask.sum()
            if n < 5: continue
            sub = df[mask]
            for direction in ['BUY', 'SELL']:
                wins = (sub['label'] == (1 if direction == 'BUY' else -1)).sum()
                losses = (sub['label'] == (-1 if direction == 'BUY' else 1)).sum()
                td = wins + losses
                if td < 3: continue
                wr = wins / td * 100
                pf = wins / max(losses, 1)
                ev = (wins * 20 - losses * 20) / td
                rules.append({
                    'rule': f"OT={ot_val} AND |{prev_col}|<5t -> {direction}",
                    'signals': n, 'trades': td, 'wins': wins, 'losses': losses,
                    'wr': wr, 'pf': pf, 'ev_ticks': ev,
                })

# Regle type 6: Cluster + previous level specifique
for prev_col in prev_cols:
    dist_prev = pd.to_numeric(df[prev_col], errors='coerce')
    for min_c in [5, 7]:
        mask = (df['n_levels_close'] >= min_c) & (dist_prev.abs() < 3)
        n = mask.sum()
        if n < 5: continue
        sub = df[mask]
        for direction in ['BUY', 'SELL']:
            wins = (sub['label'] == (1 if direction == 'BUY' else -1)).sum()
            losses = (sub['label'] == (-1 if direction == 'BUY' else 1)).sum()
            td = wins + losses
            if td < 3: continue
            wr = wins / td * 100
            pf = wins / max(losses, 1)
            ev = (wins * 20 - losses * 20) / td
            rules.append({
                'rule': f"cluster>={min_c} AND |{prev_col}|<3t -> {direction}",
                'signals': n, 'trades': td, 'wins': wins, 'losses': losses,
                'wr': wr, 'pf': pf, 'ev_ticks': ev,
            })

# Compilation et tri
rules_df = pd.DataFrame(rules)
if rules_df.empty:
    print("AUCUNE REGLE TROUVEE")
    sys.exit(0)

# Filtre minimum: 5 trades, WR > 50%, PF > 1.0
valid = rules_df[(rules_df['trades'] >= 5) & (rules_df['wr'] > 50) & (rules_df['pf'] > 1.0)]
valid = valid.sort_values('ev_ticks', ascending=False)

print(f"\nRegles generees: {len(rules_df)}")
print(f"Regles valides (>=5 trades, WR>50%, PF>1.0): {len(valid)}")

print("\n" + "="*80)
print("TOP 20 REGLES (triees par EV/trade)")
print("="*80)
print(f"{'#':>3} {'WR%':>6} {'PF':>6} {'EV_t':>6} {'W':>4} {'L':>4} {'Sig':>5}  Regle")
print("-" * 100)

for i, (_, row) in enumerate(valid.head(20).iterrows()):
    print(f"{i+1:>3} {row['wr']:>5.1f}% {row['pf']:>6.2f} {row['ev_ticks']:>+5.1f} {row['wins']:>4} {row['losses']:>4} {row['signals']:>5}  {row['rule']}")

# =============================================================================
# DETAIL TOP 5 avec conditions exactes
# =============================================================================
print("\n" + "="*80)
print("DETAIL TOP 5 REGLES")
print("="*80)

for i, (_, row) in enumerate(valid.head(5).iterrows()):
    print(f"\n--- REGLE #{i+1} ---")
    print(f"  Condition : {row['rule']}")
    print(f"  Signaux   : {row['signals']} barres matchent la condition")
    print(f"  Trades    : {row['trades']} (avec outcome +/-20t)")
    print(f"  Wins      : {row['wins']}")
    print(f"  Losses    : {row['losses']}")
    print(f"  Win Rate  : {row['wr']:.1f}%")
    print(f"  Profit Factor : {row['pf']:.2f}")
    print(f"  EV/trade  : {row['ev_ticks']:+.1f} ticks")
    print(f"  P&L simule (SL=20t, TP=20t) : {row['wins']*20 - row['losses']*20:+d} ticks sur {row['trades']} trades")

# =============================================================================
# RESUME PAR SYMBOLE
# =============================================================================
print("\n" + "="*80)
print("RESUME PAR SYMBOLE")
print("="*80)

for sym in ['ES', 'NQ']:
    sub = df[df['symbol'] == sym]
    n = len(sub)
    buy_win = (sub['label'] == 1).sum()
    sell_win = (sub['label'] == -1).sum()
    neutral = (sub['label'] == 0).sum()
    print(f"\n  {sym}: {n} barres US")
    print(f"    BUY_WIN: {buy_win} ({buy_win/n*100:.1f}%)")
    print(f"    SELL_WIN: {sell_win} ({sell_win/n*100:.1f}%)")
    print(f"    NEUTRAL: {neutral} ({neutral/n*100:.1f}%)")

# =============================================================================
# ANALYSE SUPPLEMENTAIRE : Direction du dist (signe)
# =============================================================================
print("\n" + "="*80)
print("BONUS: PREVIOUS LEVELS - ANALYSE PAR SIGNE (au-dessus vs en-dessous)")
print("="*80)

for col in prev_cols:
    vals = pd.to_numeric(df[col], errors='coerce')

    # Au-dessus du niveau (dist > 0 et < 5) -> typiquement resistance testee par en bas
    mask_above = (vals > 0) & (vals < 5)
    mask_below = (vals < 0) & (vals > -5)

    for mask, label_str in [(mask_above, "AU-DESSUS (0 a +5t)"), (mask_below, "EN-DESSOUS (-5 a 0t)")]:
        n = mask.sum()
        if n < 5: continue
        sub = df[mask]
        buy_win = (sub['label'] == 1).sum()
        sell_win = (sub['label'] == -1).sum()
        td = buy_win + sell_win
        if td < 3: continue
        buy_wr = buy_win / td * 100
        sell_wr = sell_win / td * 100
        print(f"\n  {col} {label_str}: {n} barres, {td} trades")
        print(f"    BUY: {buy_wr:.1f}% ({buy_win}), SELL: {sell_wr:.1f}% ({sell_win})")

print("\n\nAnalyse terminee.")
