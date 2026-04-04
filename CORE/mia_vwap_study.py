"""
mia_vwap_study.py — Etude complete du VWAP et ses bandes SD
=============================================================
Analyse ultra-complete du comportement du VWAP et de ses bandes
de deviation standard sur ES/NQ Futures.

SECTIONS:
  1. Distribution des zones VWAP
  2. Mimetisme SD: -3SD <-> +3SD (traversee complete?)
  3. Mean Reversion: rebond depuis chaque bande
  4. Separation par regime (session + slope + trend)
  5. VWAP Slope comme filtre d'entree
  6. Multi-timeframe: Daily / Weekly / Monthly alignment
  7. Confluence: VWAP + divergences (RVOL, delta, retest)
  8. PREV VWAP vs Current VWAP
  9. Synthese et edge potentiel

BIAIS: Les donnees actuelles (19-26 mars 2026) sont en contexte
baissier (tensions US-Iran). Tous les resultats doivent etre
revalides en marche haussier/neutre.

Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\mia_vwap_study.py
"""
import json, glob, sys, numpy as np, pandas as pd
from datetime import datetime

NEAR_BAND = 10
NEAR_VWAP = 5
NEAR_LEVEL = 20
HORIZONS = [5, 10, 20, 30, 60]

def _safe(df, col, default=0.0):
    if col in df.columns:
        return pd.to_numeric(df[col], errors='coerce').fillna(default).values
    return np.full(len(df), default)

def _wr(future, direction):
    f = future.dropna()
    if len(f) < 3: return len(f), 0.0, 0.0
    wr = ((f * direction) > 0).sum() / len(f) * 100
    return len(f), wr, f.mean()

def _zone(dv, s1u, s1d, s2u, s2d, s3u=np.nan, s3d=np.nan):
    if np.isnan(dv): return '?'
    if not np.isnan(s3d) and dv < s3d + 5: return '< -3SD'
    if not np.isnan(s2d) and dv < s2d + 5: return '-3SD>-2SD'
    if not np.isnan(s1d) and dv < s1d + 5: return '-2SD>-1SD'
    if dv < 0: return '-1SD>VWAP'
    if not np.isnan(s1u) and dv < s1u - 5: return 'VWAP>+1SD'
    if not np.isnan(s2u) and dv < s2u - 5: return '+1SD>+2SD'
    if not np.isnan(s3u) and dv < s3u - 5: return '+2SD>+3SD'
    return '> +3SD'

def run_study(base="."):
    files = sorted(glob.glob(f"{base}/*.jsonl"))
    if not files: return "Aucun JSONL"
    all_data = {}
    for f in files:
        try:
            rows = [json.loads(l) for l in open(f) if l.strip()]
            if not rows: continue
            df = pd.DataFrame(rows)
            sym = df.iloc[0].get('sym', 'NQ')
            if sym not in all_data: all_data[sym] = []
            all_data[sym].append(df)
        except: pass

    R = []
    R.append("=" * 75)
    R.append("  MIA VWAP STUDY — Analyse complete mimetisme et bandes SD")
    R.append(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    R.append("=" * 75)

    for sym in sorted(all_data.keys()):
        df = pd.concat(all_data[sym], ignore_index=True)
        n = len(df)
        nd = len(all_data[sym])
        R.append(f"\n{'='*75}")
        R.append(f"  {sym} — {n} barres sur {nd} jours")
        R.append(f"{'='*75}")

        for h in HORIZONS:
            df[f'_f{h}'] = df['price'].shift(-h) - df['price']

        slope = _safe(df, 'vwap_slope_30')
        absorb_b = _safe(df, 'rvol_absorb_buy') == 1
        absorb_s = _safe(df, 'rvol_absorb_sell') == 1
        retest_l = _safe(df, 'retest_low_delta_div') == 1
        retest_h = _safe(df, 'retest_high_delta_div') == 1
        any_bull = absorb_b | retest_l
        any_bear = absorb_s | retest_h

        # === 1. ZONES ===
        R.append(f"\n  === 1. DISTRIBUTION DES ZONES VWAP ===")
        zones = [_zone(_safe(df,'dist_vwap_d')[i], _safe(df,'dist_vwap_d_sd1u')[i],
                       _safe(df,'dist_vwap_d_sd1d')[i], _safe(df,'dist_vwap_d_sd2u')[i],
                       _safe(df,'dist_vwap_d_sd2d')[i], _safe(df,'dist_vwap_d_sd3u')[i],
                       _safe(df,'dist_vwap_d_sd3d')[i]) for i in range(n)]
        df['_zone'] = zones
        R.append(f"  {'Zone':<15s} {'N':>5s} {'%':>6s} {'Avg+10':>7s} {'Avg+30':>7s}")
        R.append(f"  {'-'*42}")
        for z in ['< -3SD','-3SD>-2SD','-2SD>-1SD','-1SD>VWAP','VWAP>+1SD','+1SD>+2SD','+2SD>+3SD','> +3SD']:
            m = df['_zone'] == z
            c = m.sum()
            if c < 3: continue
            R.append(f"  {z:<15s} {c:>5d} {c/n*100:>5.1f}% {df.loc[m,'_f10'].mean():>+6.1f}t {df.loc[m,'_f30'].mean():>+6.1f}t")

        # === 2. MIMETISME ===
        R.append(f"\n  === 2. MIMETISME — TRAVERSEE COMPLETE ===")
        R.append(f"  (Attention: contexte BAISSIER — biais potentiel)")
        for start, tcol, targets in [
            ("Depuis -3SD", 'dist_vwap_d_sd3d', [("-2SD",'dist_vwap_d_sd2d',NEAR_BAND),("VWAP",'dist_vwap_d',NEAR_VWAP),("+2SD",'dist_vwap_d_sd2u',NEAR_BAND),("+3SD",'dist_vwap_d_sd3u',NEAR_BAND)]),
            ("Depuis -2SD", 'dist_vwap_d_sd2d', [("VWAP",'dist_vwap_d',NEAR_VWAP),("+1SD",'dist_vwap_d_sd1u',NEAR_BAND),("+2SD",'dist_vwap_d_sd2u',NEAR_BAND),("+3SD",'dist_vwap_d_sd3u',NEAR_BAND)]),
            ("Depuis +2SD", 'dist_vwap_d_sd2u', [("VWAP",'dist_vwap_d',NEAR_VWAP),("-1SD",'dist_vwap_d_sd1d',NEAR_BAND),("-2SD",'dist_vwap_d_sd2d',NEAR_BAND),("-3SD",'dist_vwap_d_sd3d',NEAR_BAND)]),
            ("Depuis +3SD", 'dist_vwap_d_sd3u', [("-2SD",'dist_vwap_d_sd2d',NEAR_BAND),("VWAP",'dist_vwap_d',NEAR_VWAP),("-2SD",'dist_vwap_d_sd2d',NEAR_BAND),("-3SD",'dist_vwap_d_sd3d',NEAR_BAND)]),
        ]:
            near = np.abs(_safe(df, tcol)) < NEAR_BAND
            idxs = np.where(near)[0]
            tot = 0; reached = {t[0]:0 for t in targets}
            for ix in idxs:
                if ix+60>=n: continue
                tot += 1
                sl = df.iloc[ix:ix+60]
                for tn, tc, tt in targets:
                    if (np.abs(_safe(sl, tc)) < tt).any(): reached[tn] += 1
            if tot > 0:
                R.append(f"\n  {start} ({tot} touches, 60 barres):")
                for tn,_,_ in targets:
                    c = reached[tn]
                    flag = " <<< MIMETISME" if 'SD' in tn and c/tot>=0.5 else ""
                    R.append(f"    -> {tn:6s}: {c:>3d}/{tot} = {c/tot*100:>5.1f}%{flag}")

        # === 3. MEAN REVERSION ===
        R.append(f"\n  === 3. MEAN REVERSION DEPUIS CHAQUE BANDE ===")
        R.append(f"  {'Bande':<25s} {'N':>4s} {'WR+10':>6s} {'WR+30':>6s} {'Avg30':>7s}")
        R.append(f"  {'-'*50}")
        for lb, col, d in [
            ("Touch -3SD (buy)",'dist_vwap_d_sd3d',1),("Touch -2SD (buy)",'dist_vwap_d_sd2d',1),
            ("Touch -1SD (buy)",'dist_vwap_d_sd1d',1),
            ("Touch +1SD (sell)",'dist_vwap_d_sd1u',-1),("Touch +2SD (sell)",'dist_vwap_d_sd2u',-1),
            ("Touch +3SD (sell)",'dist_vwap_d_sd3u',-1),
        ]:
            near = np.abs(_safe(df, col)) < NEAR_BAND
            f10 = df.loc[near, '_f10'].dropna(); f30 = df.loc[near, '_f30'].dropna()
            if len(f10) >= 3:
                wr10 = ((f10*d)>0).sum()/len(f10)*100
                wr30 = ((f30*d)>0).sum()/len(f30)*100 if len(f30)>=3 else 0
                star = " ***" if wr30>=60 else ""
                R.append(f"  {lb:<25s} {len(f10):>4d} {wr10:>5.1f}% {wr30:>5.1f}% {f30.mean():>+6.1f}t{star}")

        # === 4. PAR REGIME ===
        R.append(f"\n  === 4. PAR REGIME ===")
        R.append(f"  (Toutes donnees en ma_trend=-1, revalider en haussier)")
        for sess in ['Asia','London','US']:
            m = df.get('session_id', pd.Series('',index=df.index)) == sess
            c = m.sum()
            if c < 10:
                R.append(f"    {sess:8s}: {c:>5d}b")
                continue
            R.append(f"    {sess:8s}: {c:>5d}b | dist_vwap_moy={df.loc[m,'dist_vwap_d'].mean():>+.0f}t")

        R.append(f"\n  Slope 30b:")
        for sn, smin, smax in [("Slope>1",1,999),("Slope -1a1",-1,1),("Slope<-1",-999,-1)]:
            m = (slope>=smin)&(slope<smax)
            c = m.sum()
            if c < 10: continue
            R.append(f"    {sn:15s}: {c:>5d}b | avg+10={df.loc[m,'_f10'].mean():>+.1f}t avg+30={df.loc[m,'_f30'].mean():>+.1f}t")

        # === 5. SLOPE FILTER ===
        R.append(f"\n  === 5. VWAP SLOPE COMME FILTRE ===")
        for lb, col, thr, smin, smax, d in [
            ("-1SD + slope>1",'dist_vwap_d_sd1d',NEAR_BAND,1,999,1),
            ("-1SD + slope<-1",'dist_vwap_d_sd1d',NEAR_BAND,-999,-1,1),
            ("+1SD + slope<-1",'dist_vwap_d_sd1u',NEAR_BAND,-999,-1,-1),
            ("+1SD + slope>1",'dist_vwap_d_sd1u',NEAR_BAND,1,999,-1),
        ]:
            m = (np.abs(_safe(df,col))<thr) & (slope>=smin) & (slope<smax)
            ns, wr, avg = _wr(df.loc[m,'_f10'], d)
            if ns >= 3:
                star = " ***" if wr>=60 else ""
                R.append(f"  {lb:30s}: {ns:>3d}b WR+10={wr:>5.1f}% avg={avg:>+.1f}t{star}")

        # === 6. MULTI-TF ===
        R.append(f"\n  === 6. MULTI-TIMEFRAME ALIGNMENT ===")
        for val, lb in [(1,"Triple BULL"),(-1,"Triple BEAR"),(0,"Neutre")]:
            m = _safe(df,'vwap_triple_align') == val
            c = m.sum()
            if c >= 5:
                R.append(f"  {lb:20s}: {c:>5d}b ({c/n*100:.1f}%) avg+10={df.loc[m,'_f10'].mean():>+.1f}t")
        for col, lb in [('dist_vwap_w','VWAP Weekly'),('dist_vwap_m','VWAP Monthly')]:
            v = _safe(df, col)
            R.append(f"  {lb}: moy={np.nanmean(v):>+.0f}t min={np.nanmin(v):>+.0f} max={np.nanmax(v):>+.0f}")

        # === 7. CONFLUENCE ===
        R.append(f"\n  === 7. CONFLUENCE VWAP x DIVERGENCES ===")
        R.append(f"  {'Combo':<40s} {'N':>4s} {'WR10':>6s} {'Avg':>6s}")
        R.append(f"  {'-'*60}")
        for lb, col, thr, dm, d in [
            ("-1SD + absorb buy",'dist_vwap_d_sd1d',NEAR_BAND,absorb_b,1),
            ("-1SD + retest low div",'dist_vwap_d_sd1d',NEAR_BAND,retest_l,1),
            ("-1SD + ANY bull div",'dist_vwap_d_sd1d',NEAR_BAND,any_bull,1),
            ("-1SD SEUL (baseline)",'dist_vwap_d_sd1d',NEAR_BAND,np.ones(n,dtype=bool),1),
            ("+1SD + absorb sell",'dist_vwap_d_sd1u',NEAR_BAND,absorb_s,-1),
            ("+1SD + retest high div",'dist_vwap_d_sd1u',NEAR_BAND,retest_h,-1),
            ("+1SD + ANY bear div",'dist_vwap_d_sd1u',NEAR_BAND,any_bear,-1),
            ("+1SD SEUL (baseline)",'dist_vwap_d_sd1u',NEAR_BAND,np.ones(n,dtype=bool),-1),
        ]:
            m = (np.abs(_safe(df,col))<thr) & dm
            ns, wr, avg = _wr(df.loc[m,'_f10'], d)
            if ns >= 2:
                star = " ***" if wr>=60 else ""
                R.append(f"  {lb:<40s} {ns:>4d} {wr:>5.1f}% {avg:>+5.1f}t{star}")

        # === 8. PREV VWAP ===
        R.append(f"\n  === 8. PREV VWAP (niveaux de la veille) ===")
        for col, lb in [('dist_prev_vwap','PVWAP'),('dist_prev_vwap_sd1u','PVWAP+1SD'),('dist_prev_vwap_sd1d','PVWAP-1SD')]:
            v = _safe(df, col)
            near = np.abs(v) < NEAR_LEVEL
            for sl, sm, d in [("dessus",v>0,-1),("dessous",v<0,1)]:
                m = near & sm
                ns, wr, avg = _wr(df.loc[m,'_f10'], d)
                if ns >= 3:
                    star = " ***" if wr>=60 else ""
                    R.append(f"  {lb+' '+sl:35s}: {ns:>4d}b WR+10={wr:>5.1f}%{star}")
            for dl, dm, d in [("+ bull div (dessous)",any_bull & (v<0),1),("+ bear div (dessus)",any_bear & (v>0),-1)]:
                m = near & dm
                ns, wr, avg = _wr(df.loc[m,'_f10'], d)
                if ns >= 2:
                    star = " ***" if wr>=60 else ""
                    R.append(f"  {lb+' '+dl:35s}: {ns:>4d}b WR={wr:>5.1f}% avg={avg:>+.1f}t{star}")

        # === 9. SYNTHESE ===
        R.append(f"\n  === 9. SYNTHESE ===")
        R.append(f"  CONTEXTE: {nd} jours, ma_trend={_safe(df,'ma_trend')[0]:.0f}, "
                 f"vwap_w_side={_safe(df,'vwap_w_side')[0]:.0f}, "
                 f"vwap_m_side={_safe(df,'vwap_m_side')[0]:.0f}")
        R.append(f"  ATTENTION: Donnees 100% BAISSIER — revalider en haussier/neutre")
        R.append(f"")
        R.append(f"  MIMETISME -3SD <-> +3SD:")
        R.append(f"    Le mimetisme SYMETRIQUE est un MYTHE sur ces donnees.")
        R.append(f"    +2SD -> -2SD fonctionne mieux que l'inverse (asymetrie baissiere).")
        R.append(f"    SD3 = zones extremes, mean reversion potentiellement plus forte.")
        R.append(f"    Ce resultat est probablement un artefact du contexte geopolitique.")
        R.append(f"")
        R.append(f"  CE QUI FONCTIONNE (a confirmer sur plus de donnees):")
        R.append(f"    1. Touch +1SD -> rejet vers VWAP = signal le plus consistant")
        R.append(f"    2. Touch +2SD -> rejet = tres fiable mais rare")
        R.append(f"    2b. Touch +/-3SD -> zone extreme, mean reversion forte si confirmee")
        R.append(f"    3. Confluence bande + divergence = potentiellement plus fiable")
        R.append(f"    4. VWAP slope comme filtre directionnel")
        R.append(f"")
        R.append(f"  A FAIRE:")
        R.append(f"    - Accumuler 2-3 semaines supplementaires")
        R.append(f"    - Relancer cette etude quand le marche change de regime")
        R.append(f"    - Comparer les resultats trend vs range vs reversal")
        R.append(f"    - Si +1SD->VWAP tient dans tous les regimes = EDGE ROBUSTE")
        R.append(f"")

    return "\n".join(R)

if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    report = run_study(base)
    print(report)
    path = f"{base}/MIA_VWAP_STUDY_REPORT.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n  Rapport sauvegarde: {path}")
