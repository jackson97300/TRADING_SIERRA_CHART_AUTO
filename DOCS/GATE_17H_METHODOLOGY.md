# GATE 17h Methodology — Decision rules pre-definies samedi

**Date** : 2026-05-02 01:00 UTC (nuit, doc anti-data-dredging)
**Status** : v2 post-review ml-trainer (9 problemes patches)
**Goal** : pre-definir les seuils GO/NO-GO/MARGINAL **AVANT** de voir les
resultats baselines AUC samedi 17h. Une fois les chiffres connus, biais
de confirmation rend impossible de fixer un seuil objectif.

## Pourquoi ce document existe

Plan revisé samedi : 4 baselines AUC sur 632 features (sans signal rules x 4 TF).
Si baseline = MARGINAL, tentation enorme de :
- "Ajouter signal rules dimanche pour passer le seuil"
- "Re-tuner Optuna avec plus de trials"
- "Essayer un autre regime split"

C'est du **data dredging par phases** : tu fittes ton dataset jusqu'a ce que
ca passe, tu crois avoir un edge, c'est juste overfit.

Pre-definir les regles AVANT = anti-pattern 11 V1 + anti-Lopez De Prado ch.11.

---

## 1. Seuils GO clair — TOUTES conditions reunies

**Walk-forward ES+NQ x BUY+SELL = 4 combinaisons**.

Pour chaque (instrument, side) :
- **PF OOS** >= 1.40 (mediane folds)
- **DSR Bailey-Lopez** >= **0.6** (vs 0.95 initial — corrige post-review : seuil
  0.95 trop strict pour 1m bars, plafond empirique JL2 = PF 1.29 → SR ~0.8-1.0
  annualise. DSR 0.95 demande edge enorme. Cf section 4)
- **WR OOS** >= 45%
- **EV/trade OOS** >= 1.0 tick (ES) / 1.5 tick (NQ)
- **Trades/jour mediane** >= 3
- **Max DD OOS** :
  - ES <= 500 ticks ($625)
  - NQ <= 300 ticks ($150) — symetrie $ ES/NQ (vs 500 ticks naif = $250)
- **Stabilite folds** : std(PF) / mean(PF) < 0.4 ET min(PF) > 0.8
  (1 fold mauvais sur 12 = normal si vrai edge stable)

### 1.bis Apple-to-apple ES vs NQ

- Folds **chronologiquement alignes** ES/NQ (memes dates train, memes dates test)
- Couts inclus dans PF : ES 2.3 ticks, NQ 5.2 ticks (per round-trip, cf
  `train_lightgbm.py:87-88`)
- "Edge brut" complementaire : PF avec cost=0 pour comparer signal pur entre
  instruments. Loggue separement.
- ES_BUY+SELL et NQ_BUY+SELL = **4 modeles separes** (CLAUDE.md ML pipeline).
  Pas de modele joint.

Si 4/4 GO clair → deploy paper integral.

---

## 2. Seuils NO-GO clair — UNE seule condition rouge

**Si une combinaison atteint** :
- PF OOS < 1.0 OU
- DSR < 0 OU
- WR OOS < 35% OU
- EV/trade < 0 OU
- Max DD > 1500 ticks ES / 900 ticks NQ
- min(PF) sur folds < 0.5 (volatilite inacceptable)

→ **NO-GO immediat** sur cette combinaison.

### 2.bis Decision Voie 5 selon mix GO/NO-GO

**Reviser logique simpliste "3/4 NO-GO = abandon"** :

- **4/4 GO** → deploy paper integral
- **3/4 GO** → deploy 3 OK observe-only, investigation 1 NO-GO isolee
- **2/4 GO ET cas symetrique SELL** (ES_SELL + NQ_SELL OK, BUY tous NO-GO)
  → deploy SELL only, archiver BUY pour V6.
  **Justification** : Hong-Stein 2003 — asymetrie BUY/SELL futures index
  attendue (vendeurs paient le hedge, acheteurs payent l'asymetrie fat-tail
  bear). Pas un signal d'abandon.
- **2/4 GO ET cas asymetrique** (ex: ES_BUY OK + NQ_SELL OK, mix incoherent)
  → MARGINAL strict, hold-out unique decide
- **1/4 GO** → MARGINAL strict, hold-out unique decide
- **0/4 GO** → pivot Voie 5

---

## 3. MARGINAL — Le piege

**Definition marginal** :
- PF OOS dans [1.0, 1.4[ ou [1.4, 1.5] avec DSR < 0.6
- DSR dans [0, 0.6[ avec PF >= 1.4
- WR dans [40%, 45%[
- EV/trade dans [0, 1.0[ tick

**Regle souveraine MARGINAL (anti-data-dredging)** :

### Etape 1 — Hold-out absolu (CORRIGE post-review)

Avant de toucher au dataset V5, isoler **12 derniers mois (mai 2025 - mai 2026)**
en 4 trimestres hold-out folds. Ne JAMAIS lancer training, tuning, feature
selection sur cette fenetre. Acces unique = 1 score final.

```python
# 12 mois hold-out, divise en 4 trimestres
hold_out_start  = "2025-05-01"
train_val_end   = "2025-04-30"
hold_out_folds  = [
    ("2025-05-01", "2025-07-31"),  # Q1 hold-out
    ("2025-08-01", "2025-10-31"),  # Q2
    ("2025-11-01", "2026-01-31"),  # Q3 (regime change FED ?)
    ("2026-02-01", "2026-04-30"),  # Q4
]
```

**Justification (vs 3 mois initial)** :
- 12 mois = 4 regimes vol distincts (vs 1 si 3 mois)
- Coherent avec data MenthorQ disponible (depuis 2026 = subset)
- Si regime change Q1/Q2 2026, visible dans le breakdown trimestriel
- Score final = mediane des 4 trimestres + worst-case fold

### Etape 1.bis — Coherence MenthorQ historique

**ALERTE** : V5 inclut `mq_*` features. MenthorQ n'est collecte que depuis 2026.

Sur train 2011-2024 :
- Soit `mq_* = NaN` (LightGBM gere natif, mais info=0)
- Soit exclure `mq_*` features sur fold ou data pre-2024

**Decision avant samedi** : check `dataset_builder.py` comment `mq_*` est rempli
sur dates pre-MenthorQ. Si fill_value=0 ou bfill → **leak avenir** (utilise
valeur 2026 sur 2011 = look-ahead). Trier samedi 9h.

### Etape 2 — Decision marginal samedi soir

Si baseline 632 features = MARGINAL :
- **Option A** : Ajouter signal rules x 4 TF dimanche, RE-train sur train_val
  uniquement, **score final unique sur hold-out** (n_trials cumule = 240+)
- **Option B** : Pivot Voie 5 immediate, pas de signal rules ajout

**Choisir A ou B AVANT de voir les baselines**, pas apres.

### Etape 3 — Decision dimanche soir post hold-out

Apres training V5 + signal rules sur train_val :
- Hold-out PF >= 1.4 + DSR >= 0.6 + degradation < 0.15 PF vs val_set
  → **GO observe-only paper**, n_trials = 240+ dans DSR final
- Degradation hold-out > 0.15 PF vs val_set → **overfit confirme NO-GO**, archive
- Hold-out marginal aussi → **pivot Voie 5**, pas de 3eme ronde

**Pas de 3eme ronde de features**. Une fois hold-out epuise, c'est fini.

---

## 4. DSR Bailey-Lopez — Formule exacte (CORRIGE post-review)

### 4.1 Formule (Bailey & Lopez De Prado 2014, AFML ch.13)

```
DSR = Φ( (SR_obs - SR_threshold) · √(N-1) /
          √(1 - γ₃·SR_obs + ((γ₄-1)/4)·SR_obs²) )

ou:
- SR_obs        = Sharpe ratio observe OOS (returns trade-par-trade, annualise)
- SR_threshold  = E[max{SR_k}] sur n_trials trials (Bailey eq. 13.4)
                  ≈ √(2·ln(n_trials)) pour n_trials grand
- γ₃, γ₄        = skewness, kurtosis returns trade-par-trade
- N             = nb returns OOS
- Φ             = CDF normale standard
```

**Important** : DSR != PSR.
- PSR_0 = P(SR_true > 0)
- DSR penalise par SELECTION BIAS via n_trials (deflate)

### 4.2 n_trials — Calcul honnete (CRITIQUE post-review)

n_trials_REEL = nb total de configs testees historiquement.

```
Samedi      : 4 baselines × 30 Optuna trials = 120
Dimanche A  : +4 reruns × 30 Optuna trials   = +120 → 240
Historique  : iterations features depuis 29/03 (estime conservateur) = +50
n_trials_DECLARE_MIN = 120 (Optuna inclus, samedi seul)
n_trials_DECLARE_MAX = 290 (cumul samedi+dimanche+historique)
```

**Convention finale** :
- Samedi : DSR avec n_trials=120 (Optuna inclus, baseline seul)
- Dimanche : DSR avec n_trials=240 minimum (samedi + reruns)
- Si tu inclus iterations historiques (defendable Lopez ch.13), n_trials=290

**Difference seuil SR_threshold** :
- n=8   : √(2·ln(8))   = 2.04
- n=120 : √(2·ln(120)) = 3.10
- n=290 : √(2·ln(290)) = 3.37

→ Avec n=8 (initial), seuil **trop permissif** par 1.0+ point Sharpe.
→ Avec n=120, plus realiste mais demande SR_obs > 3.1 pour DSR > 0.5.

### 4.3 Code template OBLIGATOIRE avant samedi 9h

Coder `CORE/dsr_calculator.py` :
```python
import numpy as np
from scipy.stats import norm

def compute_dsr(returns: np.ndarray, n_trials: int,
                sr_threshold: float = None) -> dict:
    """
    Deflated Sharpe Ratio (Bailey-Lopez 2014).

    Args:
        returns: trade-by-trade returns (already cost-adjusted)
        n_trials: nb configs testees (Optuna inclus)
        sr_threshold: si None, calcule via sqrt(2*ln(n_trials))

    Returns:
        {dsr, sr_obs, sr_threshold, n, skew, kurt}
    """
    n = len(returns)
    if n < 30:
        raise ValueError(f"N={n} too small for DSR (min 30)")
    sr_obs = returns.mean() / returns.std() * np.sqrt(252 * 6.5 * 60)  # annualise 1m
    skew = ((returns - returns.mean())**3).mean() / returns.std()**3
    kurt = ((returns - returns.mean())**4).mean() / returns.std()**4
    if sr_threshold is None:
        sr_threshold = np.sqrt(2 * np.log(n_trials))
    var_term = 1 - skew*sr_obs + ((kurt-1)/4)*sr_obs**2
    if var_term <= 0:
        return {"dsr": 0.0, "warning": "var_term<=0 (kurt extreme)"}
    dsr = norm.cdf((sr_obs - sr_threshold) * np.sqrt(n-1) / np.sqrt(var_term))
    return {
        "dsr": float(dsr),
        "sr_obs": float(sr_obs),
        "sr_threshold": float(sr_threshold),
        "n": int(n),
        "skew": float(skew),
        "kurt": float(kurt),
        "n_trials": int(n_trials),
    }
```

Tester sur returns synthetiques (Sharpe known) avant samedi 9h.

---

## 5. Patch R4 timing — DECISION REVISEE post-review

**Decision : SAMEDI MATIN 8h-10h, AVANT V5 build**

**Raison du changement** (vs dimanche soir initial) :
- Train V5 sur 728 features × 4 modeles × 30 Optuna trials = 3-6h realiste
- Si MARGINAL Option A → +2-3h reruns + hold-out scoring
- Train ML termine 17-20h dimanche, pas midi
- Patch R4 deploy dimanche soir = **fatigue maximale apres 8-12h cognitive load**
- Pattern 11 V1 garanti

**Plan revisé** :
- Samedi 8h-10h : Patch R4 (~30 LOC, audit deja fait code-reviewer)
  - Code patch dans `databento_paper_trader.py:_on_dtc_fill`
  - Tests `tests/test_bot2_parent_fill_tracking.py` (3 tests)
  - DTC_DEBUG fill.symbol run 1 trade Sim
  - SCP + restart Bot 2
  - Si echec → rollback git, V5 prio
- Samedi 10h-17h : V5 build clean
- Snapshots ML clean des samedi midi (debug eventuel V5 facile)

---

## 6. Critere "pivot Voie 5" si NO-GO

**Voie 5** = MIA hybride humain : score ML observe-only + decision finale Jackson.

Cas pivot :
- 0/4 GO samedi → flag NO-GO immediat
- Hold-out marginal dimanche → pivot Voie 5

Implementation :
1. **Dimanche apres-NO-GO** : decision parametres Voie 5 (latence dashboard,
   alerts Discord, log JSONL decisions Jackson vs ML)
2. **Lundi** : implement Voie 5 dashboard tier "ML Score (observe)" widget
3. **Lundi-Mardi** : Bot 2 reste paper avec rules actuels, dashboard affiche
   score ML observe-only
4. **Semaine prochaine** : Jackson trade manuellement avec score ML comme
   sanity check, collect 100+ trades, re-train post-2 semaines data fresh

**Pas d'abandon**, juste pivot meta : MIA = decision support, pas decision
automatique. Plafond empirique edge 1m bars = PF 1.29 (JL2 best), peut-etre
la voie ML automatique est impossible sur 1m bars seules.

---

## 7. Anti-patterns interdits (COMPLETE post-review)

- ❌ Modifier seuils GO/NO-GO **apres** avoir vu les chiffres samedi
- ❌ Ajouter features dimanche **sans** hold-out absolu intouche
- ❌ Re-tuner Optuna 200 trials parce que 100 n'a pas passe
- ❌ Changer le regime split apres avoir vu les chiffres
- ❌ Ignorer n_trials dans DSR pour avoir un meilleur score
- ❌ "Tester juste pour voir" sur le hold-out avant decision finale
- ❌ Re-entrainer apres avoir vu hold-out (meme "juste pour fix bug") —
     corrompt hold-out a vie
- ❌ Reutiliser memes seeds Optuna entre samedi/dimanche (artificiellement
     reproductible mais correle)
- ❌ Calculer DSR sans inclure couts transaction dans returns
- ❌ Comparer PF samedi vs PF dimanche pour decider "ca s'ameliore" (chaque
     fit = test trial supplementaire)
- ❌ Annoncer verdict GO/NOGO a Jackson **avant** d'avoir loggue les chiffres
     exacts dans `DOCS/V5_GATE_17H_RESULTS.md` avec timestamp UTC

---

## 8. Livrables pre-samedi 9h (CORRIGE post-review)

**Sans ces 4 livrables, samedi 9h pas pret → reporter GATE au lendemain**.

1. **`DOCS/GATE_17H_METHODOLOGY.md`** (ce doc finalise post-review ml-trainer) ✅
2. **`CORE/dsr_calculator.py`** — fonction `compute_dsr()` testee sur returns
   synthetiques (Sharpe known) ⏳ A CODER samedi 8h
3. **`CORE/v5_gate_evaluator.py`** — script qui prend 4 modeles fitted, output
   table verdict ⏳ A CODER samedi 9-10h
4. **`DOCS/V5_GATE_17H_RESULTS.md.template`** — template empty rempli samedi
   17h ⏳ A CODER samedi 8h (15 min)

Commit hash visible avant samedi 9h = engagement public anti-modification.
Si je veux changer seuils, commit explicite avec justification methodo.

---

## 9. Template report verdict (a remplir samedi 17h)

```markdown
# V5 GATE 17h Results — YYYY-MM-DD HH:MM UTC

## Setup
- n_trials declare : ___ (Optuna inclus, minimum 120)
- Hold-out used : NO / YES (si oui : score ___, degradation vs val ___)
- Commit hash methodologie : ___ (verifier = pre-samedi 9h)
- Costs inclus : ES 2.3 ticks, NQ 5.2 ticks (round-trip)

## Resultats par combinaison

| Combo | PF mediane | DSR | WR | EV/trade | Trades/j | Max DD ticks | std/mean | min(PF) | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| ES_BUY  | _ | _ | _ | _ | _ | _ | _ | _ | GO/NOGO/MARG |
| ES_SELL | _ | _ | _ | _ | _ | _ | _ | _ | _ |
| NQ_BUY  | _ | _ | _ | _ | _ | _ | _ | _ | _ |
| NQ_SELL | _ | _ | _ | _ | _ | _ | _ | _ | _ |

## Decision tree applique

- [ ] 4/4 GO → deploy paper integral
- [ ] 3/4 GO → deploy 3 OK observe-only, investigation 1 NO-GO
- [ ] 2/4 GO symetrique SELL → deploy SELL only, archive BUY V6
- [ ] 2/4 GO asymetrique → MARGINAL hold-out
- [ ] 1/4 GO → MARGINAL hold-out
- [ ] 0/4 GO → pivot Voie 5

## Verdict final : ___________

## Justification (5-10 lignes max)
___________

## Next step
- [ ] Continue dimanche signal rules x 4 TF (Option A)
- [ ] Pivot Voie 5 immediate (Option B)
- [ ] Deploy paper observe-only X combos
```

---

## 10. Review agent obligatoire

Avant samedi 9h :
- **ml-trainer** ✅ Done (review v1 → 9 corrections appliquees → v2)
- **ml-trainer 2nd round** ⏳ Validation v2 patche
- **market-analyst** (optionnel) : valide pertinence trading des seuils
  (PF 1.4 vraiment GO, ou trop laxiste sur micro contracts ?)

Si ml-trainer 2nd round NOGO : **corriger AVANT samedi 9h**, pas apres.

---

## 11. Checklist samedi 9h (operational)

```
[ ] git log GATE_17H_METHODOLOGY.md commit hash visible
[ ] CORE/dsr_calculator.py existe + tests passes
[ ] CORE/v5_gate_evaluator.py existe + signature definie
[ ] DOCS/V5_GATE_17H_RESULTS.md.template existe
[ ] Decision Option A/B MARGINAL pre-declaree (ecrite dans le template)
[ ] Patch R4 : code patch + tests prets pour deploy 8h
[ ] V5 dataset enrich : MQ + CAT4 smoke testes (deja fait nuit 02/05)
[ ] Phase B grep : PROHIBITED + WHITELIST_BYPASS verifies
[ ] verify_dataset_v5_complete.py liste 632 features attendues
```

Si **un seul** item manque samedi 9h → reporter GATE 17h au lendemain.
Pattern 11 V1 garanti sinon.
