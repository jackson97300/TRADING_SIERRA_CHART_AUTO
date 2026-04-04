# MIA V1 Audit Complet — Lecons pour V2
# Date: 29 mars 2026
# Source: D:\MIA_IA_system (11 725 fichiers Python, ~148K LOC)

---

## A GARDER — Idees et composants valides

### 1. LightGBM comme modele ML
- Choix correct. Split temporel (pas random) = bonne pratique.
- Threshold optimal = 0.45 (vs 0.50 defaut), F1 +116%.
- 88% accuracy sur test set (petit echantillon: 10 jours Nov 2025).

### 2. NQ Validation = preuve d'edge
- V31 DEFINITIVE NQ Validation: **70.3% WR, 2.55 PF, +$6,142, drawdown $795**
- Walkforward NQ: **56.79% WR, 1.58 PF sur 2,430 trades** (robuste)
- NQ surperforme ES systematiquement dans tous les backtests.

### 3. Parametres TP/SL valides par backtest
- NQ: SL=25t, TP=30t (V31 valide)
- ES: SL=12t, TP=28t (V31 valide, R:R 2.33:1)
- Trailing stop V49: activation 10t, distance 6-10t, **77% win rate**

### 4. DTC Connector (sierra_dtc_connector.py)
- Protocol JSON sur TCP, port 11099, localhost
- OCO manuel (Sierra ne supporte pas nativement)
- Auto-reconnect, symbol normalization, rollover
- **Reutilisable tel quel pour V2 live execution**

### 5. Safety / Risk Management
- Kill switch multi-conditions (perte journaliere, VIX, data stale)
- Circuit breaker: 3 pertes consecutives = 30min cooldown
- Trailing stop progressif (paliers de profit locks)
- Cooldown adaptatif (win rate + volatilite + session)
- Daily loss limit ($500-$1800 selon compte)

### 6. MenthorQ comme source de features
- Gamma levels, blind spots, HVL = features validees
- dist_vix_*, dist_mq_* dans le top 20 Spearman V2
- Concept de "distance au niveau" > prix brut des niveaux

### 7. Prop Firm Framework
- APEX 150K: profit target $9,000, trailing drawdown $5,000
- Max 17 contrats ES, 1 position a la fois (conservative)
- Procedure de passage compte reel documentee

---

## A NE PAS REPRODUIRE — Patterns toxiques

### 1. Over-engineering massif
- **148K LOC pour un trading bot** = intenable
- 494 fichiers dans core/, 120 configs, 11 strategies
- Launch script de 6,500 lignes monolithique
- V2 cible: ~2,000 LOC Python + DMP C++ existant

### 2. Cascade de 4 filtres = 95% de rejection
- Layer1 (MenthorQ) -> Layer2 (OrderFlow) -> Layer3 (Context) -> Layer4 (Combo)
- Certains jours: **0 trade en 7 heures de scan**
- Le bot trouvait toujours une raison de NE PAS trader
- V2: ML decide directement (score > seuil = trade)

### 3. 100 features dont 50+ a importance zero
- GEX raw levels (1-10), DOM slope, microprice = bruit
- V1 utilisait TOUT sans selection
- V2: 75 features validees par Spearman (|rho| >= 0.02)

### 4. TP/SL "intelligent" base sur niveaux GEX
- Cause directe du bug TP sous l'entree
- HQ multiplier sans re-limiter = TP de 64 ticks au lieu de 32
- V2: TP/SL fixes + assertions de securite

### 5. Trading multi-session (Asia, London, US)
- Asia: 0 volume, spreads larges, faux signaux
- London: orderflow bruyant, 80% de rejection Layer2
- Seul US (9:30-16:00 ET) a du volume pour notre edge
- V2: Session US uniquement

### 6. Positions multiples simultanees
- Max 10 positions concurrentes en mode data collection
- Pas de gestion de position existante avant nouvelle entree
- V2: 1 position max par instrument, toujours

### 7. ML comme filtre go/no-go
- LightGBM a 0.45 threshold laissait passer presque tout
- N'ajoutait pas de valeur reelle au pipeline
- V2: ML est le DECIDEUR, pas un filtre optionnel

### 8. Binary WIN/LOSS = target trop simple
- pnl > 0 = WIN, sinon LOSS
- Pas de nuance (un gain de 1 tick = "WIN")
- V2: label tri-classe (BUY +1 / SELL -1 / HOLD 0) avec TP/SL simule

### 9. Config dupliquee
- trading_params.py (55KB) + unified_thresholds.py (32KB)
- Deux sources de verite = bugs silencieux
- V2: un seul fichier de config

### 10. Bugs critiques non-fixes a l'arret
- 0DTE levels jamais lus dans le C++ bot
- Daily loss limit ne flatten pas les positions ouvertes
- Session Quality Monitor en test_mode (pas actif)

---

## QUESTIONS — Points a clarifier avec Jackson

### 1. Focus NQ ou ES+NQ?
NQ surperforme dans TOUS les backtests V1 (70% WR vs 48-54% ES).
Les features V2 Spearman sont calculees sur ES uniquement.
Recommendation: commencer par NQ, ajouter ES apres validation.

### 2. Micro ou Mini contrats?
V1 utilisait des minis (MNQ $5/tick, MES $12.50/tick).
Les SL de 25 ticks NQ = $125 risk par trade (micro = $31.25).
Pour le debut: micro contrats pour limiter le risque.

### 3. Trailing stop dans V2?
V1 trailing = 77% WR, +$20,558 vs version sans.
Les parametres V49 (activation 10t, distance 6-10t) sont prouves.
Integrer dans l'execution C++ Sierra Chart.

### 4. MenthorQ toujours disponible?
V1 dependait fortement de MenthorQ pour Layer1 (50% du signal).
V2 DMP capture deja dist_mq_*, dist_vix_*, dist_gex_*.
Verifier que MenthorQ tourne toujours et alimente les niveaux.

### 5. DTC connector reutilisable?
Le fichier sierra_dtc_connector.py est fonctionnel.
Mais V2 execute dans Sierra Chart nativement (C++ ACSIL).
Le DTC serait utile uniquement pour un dashboard Python externe.

---

## COMPOSANTS REUTILISABLES (copie directe possible)

| Fichier V1 | Usage V2 | Modifications necessaires |
|---|---|---|
| execution/sierra_dtc_connector.py | Dashboard live / monitoring externe | Adapter symbols, cleanup |
| core/trailing_stop_manager.py | Logique trailing dans C++ bot | Traduire en C++ |
| core/safety_kill_switch.py | Circuit breaker V2 | Simplifier, garder les 3 conditions cles |
| core/adaptive_cooldowns.py | Cooldown entre trades | Integrer dans le C++ bot |
| ml/4_TRAINING/train_lightgbm_classifier.py | Reference pour training V2 | Remplacer par DatasetBuilder V2 |
| config/trading_params.py | Reference TP/SL valides | Extraire valeurs, jeter le reste |
| BACKTEST_OUT/V31_DEFINITIVE/ | Benchmark de comparaison | Read-only reference |

---

## BUGS CORRIGES V2

| Date | Bug | Cause | Fix |
|------|-----|-------|-----|
| 30/03/2026 | IB High null — dist_ib_high = INVALID sur charts footprint | sc.High sur chart footprint renvoie le high du footprint (prix le plus haut avec volume), pas le vrai high de la barre 1min. IB calculee avec des valeurs fausses. | ib_recalc.py — Python post-processing recalcule ib_high/ib_low depuis bar_high/bar_low (colonnes 3.7.1+). Integre dans DatasetBuilder. Le C++ reste inchange (collecteur muet). |

---

## METRIQUES CLES V1 (reference pour V2)

| Metrique | V1 Meilleur (NQ V31) | V1 Pire (ES V31 train) | Cible V2 |
|---|---|---|---|
| Win Rate | 70.3% | 47.7% | > 55% |
| Profit Factor | 2.55 | 0.85 | > 1.5 |
| Max Drawdown | $795 | $1,906 | < $1,000 |
| Trades/jour | 0-3 (trop peu) | 0 (aucun) | 3-5 |
| Rejection rate | 95% | 100% | < 50% |
| LOC total | 148,000 | - | < 3,000 |
| Fichiers Python | 11,725 | - | < 10 |
