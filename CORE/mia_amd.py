"""
mia_amd.py — Module AMD (Accumulation, Manipulation, Distribution)
===================================================================

Détecte le cycle ICT Power of 3 sur ES/NQ Futures à partir des
258 features DMP du pipeline MIA.

Concept (ICT / Smart Money):
  A = Accumulation : range étroit, volume faible (Asia 18:00-03:00 ET)
  M = Manipulation : faux breakout du range Asia, sweep des stops (London 03:00-09:00)
  D = Distribution : vrai mouvement directionnel (US 09:00-17:00 ET)

Règles:
  1. Accumulation: range Asia < 60% ATR + range significatif
  2. Sweep: prix dépasse high/low Asia de SWEEP_MIN ticks (ONE-SHOT)
  3. Judas Swing: sweep PUIS prix revient dans le range (reversal confirmé)
  4. Manipulation Score: pondéré par RVOL, delta div, absorption, retest
  5. Distribution: volume + delta + momentum alignés APRÈS manipulation
  6. PO3: les 3 phases validées → scoring combiné

Features exportées (18 colonnes amd_*).

Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\mia_amd.py
Schema: 3.7.0 — 258 colonnes
"""

import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

ACCUM_MAX_ATR_RATIO = 0.60
ACCUM_MIN_TICKS = {"NQ": 50, "ES": 12}
SWEEP_MIN_TICKS = {"NQ": 15, "ES": 4}
MANIP_RVOL_SPIKE = 1.5
MANIP_DELTA_THR = 0.10
JUDAS_REENTRY_TICKS = {"NQ": 10, "ES": 3}
DIST_RVOL_MIN = 1.3
DIST_DELTA_MIN = 0.05
DIST_MOMENTUM_MIN = 5.0
PO3_W_ACCUM = 0.25
PO3_W_MANIP = 0.40
PO3_W_DIST  = 0.35

FEATURES = [
    'amd_phase', 'amd_asia_range_ticks', 'amd_asia_high', 'amd_asia_low',
    'amd_sweep_up', 'amd_sweep_dn', 'amd_sweep_depth_ticks',
    'amd_manip_score', 'amd_manip_dir', 'amd_judas_swing',
    'amd_dist_score', 'amd_dist_dir', 'amd_dist_confirmed',
    'amd_reversal_prob', 'amd_po3_bullish', 'amd_po3_bearish',
    'amd_po3_score', 'amd_session_bias',
]


class AmdEngine:
    def __init__(self, symbol="NQ"):
        self.symbol = symbol.upper()
        self.tick = 0.25
        self.sweep_min = SWEEP_MIN_TICKS.get(self.symbol, 15)
        self.accum_min = ACCUM_MIN_TICKS.get(self.symbol, 50)
        self.judas_re = JUDAS_REENTRY_TICKS.get(self.symbol, 10)

    @staticmethod
    def _col(df, name, default=0.0):
        if name in df.columns:
            return pd.to_numeric(df[name], errors='coerce').fillna(default).values
        return np.full(len(df), default)

    def _get_sessions(self, df):
        if 'session_id' in df.columns:
            return df['session_id'].astype(str).values
        s = self._col(df, 'session', 2)
        return np.where(s == 0, 'Asia', np.where(s == 1, 'London', 'US'))

    # ── COMPUTE ──────────────────────────────────────────────────────

    def compute(self, df):
        df = df.copy()
        n = len(df)
        for f in FEATURES:
            df[f] = np.nan if f in ('amd_asia_high','amd_asia_low','amd_asia_range_ticks') else 0.0
        df['amd_phase'] = -1.0
        if n < 10:
            return df

        sess = self._get_sessions(df)
        px = df['price'].values.astype(float)
        atr = self._col(df, 'atr', 100.0)

        # 1. Asia range
        a_h, a_l, a_rng, a_valid = self._asia_range(sess, px, atr)
        df['amd_asia_high'], df['amd_asia_low'], df['amd_asia_range_ticks'] = a_h, a_l, a_rng

        # 2. Phase
        df['amd_phase'] = np.where(sess=='Asia', 0, np.where(sess=='London', 1,
                          np.where(sess=='US', 2, -1)))

        # 3. Sweep (one-shot)
        sw_u, sw_d, sw_dep = self._detect_sweeps(sess, px, a_h, a_l)
        df['amd_sweep_up'], df['amd_sweep_dn'], df['amd_sweep_depth_ticks'] = sw_u, sw_d, sw_dep

        # 4. Judas Swing (sweep + reversal)
        judas, m_dir = self._detect_judas(sess, px, a_h, a_l, sw_u, sw_d)
        df['amd_judas_swing'], df['amd_manip_dir'] = judas, m_dir

        # 5. Propagate manip_dir
        prop_dir = self._propagate_dir(sess, m_dir)

        # 6. Manipulation score
        df['amd_manip_score'] = self._score_manip(df, sw_dep, prop_dir, a_valid)

        # 7. Distribution
        ds, dd, dc = self._score_dist(df, sess, prop_dir)
        df['amd_dist_score'], df['amd_dist_dir'], df['amd_dist_confirmed'] = ds, dd, dc

        # 8. PO3
        self._score_po3(df, sess, a_valid, prop_dir)

        # 9. Bias
        df['amd_session_bias'] = np.where(dc==1, dd, np.where(judas==1, -m_dir, 0))
        return df

    # ── ASIA RANGE ───────────────────────────────────────────────────

    def _asia_range(self, sess, px, atr):
        n = len(sess)
        a_h, a_l, a_rng, a_valid = [np.full(n, np.nan) for _ in range(3)] + [np.zeros(n)]
        cur_h = cur_l = np.nan
        fr_h = fr_l = np.nan
        fr_valid = False
        prev = ''
        for i in range(n):
            s, p = sess[i], px[i]
            if s == 'Asia':
                if prev != 'Asia': cur_h = cur_l = p
                else:
                    cur_h = max(cur_h, p) if not np.isnan(cur_h) else p
                    cur_l = min(cur_l, p) if not np.isnan(cur_l) else p
                a_h[i], a_l[i] = cur_h, cur_l
            elif s in ('London', 'US'):
                if prev == 'Asia' and not np.isnan(cur_h):
                    fr_h, fr_l = cur_h, cur_l
                    rng = (fr_h - fr_l) / self.tick
                    a = atr[i] if atr[i] > 0 else 100.0
                    fr_valid = rng >= self.accum_min and (fr_h-fr_l)/a <= ACCUM_MAX_ATR_RATIO
                a_h[i], a_l[i] = fr_h, fr_l
                a_valid[i] = 1.0 if fr_valid else 0.0
            if not np.isnan(a_h[i]) and not np.isnan(a_l[i]):
                a_rng[i] = (a_h[i] - a_l[i]) / self.tick
            prev = s
        return a_h, a_l, a_rng, a_valid

    # ── SWEEP (ONE-SHOT) ─────────────────────────────────────────────

    def _detect_sweeps(self, sess, px, a_h, a_l):
        n = len(sess)
        sw_u, sw_d, sw_dep = np.zeros(n), np.zeros(n), np.zeros(n)
        done_u = done_d = False
        mx_u = mx_d = 0.0
        prev = ''
        for i in range(n):
            s, p = sess[i], px[i]
            if s != prev and s in ('London', 'US'):
                done_u = done_d = False; mx_u = mx_d = 0.0
            if s in ('London', 'US') and not np.isnan(a_h[i]) and not np.isnan(a_l[i]):
                if p > a_h[i] and not done_u:
                    d = (p - a_h[i]) / self.tick
                    if d >= self.sweep_min:
                        sw_u[i] = 1; mx_u = d; done_u = True
                if p < a_l[i] and not done_d:
                    d = (a_l[i] - p) / self.tick
                    if d >= self.sweep_min:
                        sw_d[i] = 1; mx_d = d; done_d = True
                if done_u and p > a_h[i]: mx_u = max(mx_u, (p-a_h[i])/self.tick)
                if done_d and p < a_l[i]: mx_d = max(mx_d, (a_l[i]-p)/self.tick)
                sw_dep[i] = max(mx_u, mx_d)
            prev = s
        return sw_u, sw_d, sw_dep

    # ── JUDAS SWING (REVERSAL) ───────────────────────────────────────

    def _detect_judas(self, sess, px, a_h, a_l, sw_u, sw_d):
        n = len(sess)
        judas, m_dir = np.zeros(n), np.zeros(n)
        had_u = had_d = j_done_u = j_done_d = False
        prev = ''
        for i in range(n):
            s, p = sess[i], px[i]
            if s != prev and s in ('London','US'):
                had_u = had_d = j_done_u = j_done_d = False
            if sw_u[i] == 1: had_u = True
            if sw_d[i] == 1: had_d = True
            if s in ('London','US') and not np.isnan(a_h[i]) and not np.isnan(a_l[i]):
                # Bear Judas: sweep UP → price comes back below asia high
                if had_u and not j_done_u:
                    re = (a_h[i] - p) / self.tick
                    if re >= self.judas_re:
                        judas[i] = 1; m_dir[i] = 1; j_done_u = True
                # Bull Judas: sweep DN → price comes back above asia low
                if had_d and not j_done_d:
                    re = (p - a_l[i]) / self.tick
                    if re >= self.judas_re:
                        judas[i] = 1; m_dir[i] = -1; j_done_d = True
            prev = s
        return judas, m_dir

    # ── PROPAGATE DIRECTION ──────────────────────────────────────────

    def _propagate_dir(self, sess, m_dir):
        n = len(sess)
        prop = np.zeros(n)
        last = 0
        for i in range(n):
            if sess[i] == 'Asia': last = 0
            if m_dir[i] != 0: last = int(m_dir[i])
            prop[i] = last
        return prop

    # ── MANIPULATION SCORE ───────────────────────────────────────────

    def _score_manip(self, df, sw_dep, prop_dir, a_valid):
        n = len(df)
        score = np.zeros(n)
        rvol = self._col(df, 'rvol', 1.0)
        dpct = self._col(df, 'delta_pct', 0.0)
        fin  = self._col(df, 'finish_strength', 0.0)
        rt_h = self._col(df, 'retest_high_delta_div', 0.0)
        rt_l = self._col(df, 'retest_low_delta_div', 0.0)
        ab_b = self._col(df, 'rvol_absorb_buy', 0.0)
        ab_s = self._col(df, 'rvol_absorb_sell', 0.0)
        prof = self._col(df, 'profile_shape', 0.0)

        for i in range(n):
            d = int(prop_dir[i])
            if d == 0: continue
            s = 0.0
            if sw_dep[i] >= self.sweep_min * 2: s += 0.20
            elif sw_dep[i] >= self.sweep_min: s += 0.10
            if rvol[i] >= MANIP_RVOL_SPIKE: s += 0.20
            if d==1 and dpct[i]>MANIP_DELTA_THR and fin[i]<0: s += 0.20
            elif d==-1 and dpct[i]<-MANIP_DELTA_THR and fin[i]>0: s += 0.20
            if d==1 and rt_h[i]>0: s += 0.15
            elif d==-1 and rt_l[i]>0: s += 0.15
            if d==-1 and ab_b[i]>0: s += 0.10
            elif d==1 and ab_s[i]>0: s += 0.10
            if a_valid[i]>0: s += 0.10
            if prof[i]==3: s += 0.05
            score[i] = min(s, 1.0)
        return score

    # ── DISTRIBUTION SCORE ───────────────────────────────────────────

    def _score_dist(self, df, sess, prop_dir):
        n = len(df)
        score, d_dir, conf = np.zeros(n), np.zeros(n), np.zeros(n)
        rvol = self._col(df, 'rvol', 1.0)
        dpct = self._col(df, 'delta_pct', 0.0)
        mom5 = self._col(df, 'momentum_5b', 0.0)
        ib_u = self._col(df, 'ib_broken_up', 0.0)
        ib_d = self._col(df, 'ib_broken_down', 0.0)
        cvd  = self._col(df, 'cvd_day_dir', 0.0)

        for i in range(n):
            d = int(prop_dir[i])
            if d == 0 or sess[i] == 'Asia': continue
            exp = -d  # distribution = opposé manipulation
            d_dir[i] = exp
            s = 0.0
            if rvol[i] >= DIST_RVOL_MIN: s += 0.25
            if exp>0 and dpct[i]>DIST_DELTA_MIN: s += 0.25
            elif exp<0 and dpct[i]<-DIST_DELTA_MIN: s += 0.25
            m5 = mom5[i]
            if exp>0 and m5>DIST_MOMENTUM_MIN: s += 0.20
            elif exp<0 and m5<-DIST_MOMENTUM_MIN: s += 0.20
            if exp>0 and ib_u[i]>0: s += 0.15
            elif exp<0 and ib_d[i]>0: s += 0.15
            if exp>0 and cvd[i]>0: s += 0.15
            elif exp<0 and cvd[i]<0: s += 0.15
            score[i] = min(s, 1.0)
            if score[i] >= 0.50: conf[i] = 1
        return score, d_dir, conf

    # ── PO3 SCORE ────────────────────────────────────────────────────

    def _score_po3(self, df, sess, a_valid, prop_dir):
        n = len(df)
        judas = df['amd_judas_swing'].values
        ms = df['amd_manip_score'].values
        md = df['amd_manip_dir'].values
        ds = df['amd_dist_score'].values
        dc = df['amd_dist_confirmed'].values

        po3b, po3br, po3s, rev = [np.zeros(n) for _ in range(4)]
        had_j = False; last_ms = 0.0; last_md = 0
        for i in range(n):
            if sess[i] == 'Asia':
                had_j = False; last_ms = 0.0; last_md = 0; continue
            if judas[i] == 1:
                had_j = True
                last_md = int(md[i]) if md[i]!=0 else last_md
                last_ms = ms[i]
            if not had_j: continue

            a_s = 0.33 if a_valid[i]>0 else 0.0
            m_s = max(last_ms, ms[i])
            po3s[i] = min(a_s*PO3_W_ACCUM + m_s*PO3_W_MANIP + ds[i]*PO3_W_DIST, 1.0)

            if last_md == -1 and dc[i] == 1: po3b[i] = 1
            elif last_md == 1 and dc[i] == 1: po3br[i] = 1

            if had_j and dc[i]==0: rev[i] = min(m_s*1.2, 1.0)
            elif had_j and dc[i]==1: rev[i] = min(m_s*0.8 + ds[i]*0.2, 1.0)

        df['amd_po3_bullish'] = po3b
        df['amd_po3_bearish'] = po3br
        df['amd_po3_score'] = po3s
        df['amd_reversal_prob'] = rev

    # ── SUMMARY ──────────────────────────────────────────────────────

    def summary(self, df):
        n = len(df)
        if n == 0: return "  Pas de données"
        L = [f"  Barres: {n} | {self.symbol}"]
        for p, lb in [(0,'Accum'),(1,'Manip'),(2,'Dist')]:
            c = (df['amd_phase']==p).sum()
            L.append(f"    {lb:6s}: {c:>5d} ({c/n*100:>5.1f}%)")
        L.append(f"    Sweep UP/DN: {(df['amd_sweep_up']>0).sum()} / {(df['amd_sweep_dn']>0).sum()}")
        ar = df['amd_asia_range_ticks'].dropna()
        if len(ar)>0: L.append(f"    Asia range: {ar.mean():.0f}t moy")
        L.append(f"    Judas: {(df['amd_judas_swing']>0).sum()}")
        ms = df.loc[df['amd_manip_score']>0,'amd_manip_score']
        if len(ms)>0: L.append(f"    Manip score: {ms.mean():.2f}")
        L.append(f"    Dist conf: {(df['amd_dist_confirmed']>0).sum()}")
        L.append(f"    PO3 Bull/Bear: {(df['amd_po3_bullish']>0).sum()}/{(df['amd_po3_bearish']>0).sum()}")
        return "\n".join(L)


# ═══════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json, sys, glob
    from datetime import datetime, timezone, timedelta

    base = sys.argv[1] if len(sys.argv) > 1 else "."
    files = sorted(glob.glob(f"{base}/*.jsonl"))
    if not files:
        print(f"Aucun .jsonl dans {base}"); sys.exit(1)

    for path in files:
        rows = [json.loads(l) for l in open(path) if l.strip()]
        if len(rows) < 10: continue
        df = pd.DataFrame(rows)
        sym = df.iloc[0].get('sym', 'NQ')
        engine = AmdEngine(sym)
        df = engine.compute(df)

        print(f"\n{'='*60}")
        print(f"  {sym} — {path.split('/')[-1]} ({len(df)} barres)")
        print(f"{'='*60}")
        print(engine.summary(df))

        jb = df[df['amd_judas_swing']>0]
        if len(jb)>0:
            print(f"\n  Judas Swings ({len(jb)}):")
            for _, r in jb.head(5).iterrows():
                ts = datetime.fromtimestamp(r['ts']/1000, tz=timezone.utc)
                et = ts - timedelta(hours=4)
                d = "↑BEAR" if r['amd_manip_dir']>0 else "↓BULL"
                print(f"    {et.strftime('%H:%M ET')} {d} manip={r['amd_manip_score']:.2f} px={r['price']:.2f}")

        if len(df)>20:
            df['fut10'] = df['price'].shift(-10) - df['price']
            print(f"\n  Performance +10b:")
            for lb, mask, d in [
                ("Judas BULL", (df['amd_judas_swing']>0)&(df['amd_manip_dir']<0), 1),
                ("Judas BEAR", (df['amd_judas_swing']>0)&(df['amd_manip_dir']>0), -1),
                ("PO3 Bull", df['amd_po3_bullish']>0, 1),
                ("PO3 Bear", df['amd_po3_bearish']>0, -1),
            ]:
                fut = df.loc[mask,'fut10'].dropna()
                if len(fut)>=2:
                    wr = ((fut*d)>0).sum()/len(fut)*100
                    print(f"    {lb:15s}: {len(fut):>3d} sig WR={wr:>5.1f}% avg={fut.mean():>+7.2f}t")
