# Guide Debug Anomalies via Logs MIA V2

**Mise a jour 2026-04-30** : ajout codes pour Bot 1 trailing TR40_20, Bot 2
gates Plan A_v2, SLTPEngine MQ walls + CAS 4, exceptions Python hot path.

Ce guide est une **table de correspondance** entre symptomes observes en prod
et requetes logs precises pour diagnostiquer en < 30 secondes.

---

## Convention

Chaque log emis va dans `LOGS/<categorie>/<categorie>_YYYYMMDD_<process>.jsonl`.
4 categories :

- `errors/`   : niveau MAJEUR + CRITIQUE (a regarder en PRIORITE)
- `events/`   : transitions systeme (boot, session, regime, exceptions)
- `decisions/`: chain of gates + vetos + scoring (chaque bar processed)
- `execution/`: DTC, ordres, OCO, trailing

Process : `paper` (Bot 1 mia_paper_trader), `databento_paper` (Bot 2),
`v2clean` (cerveau Python), etc.

Protocole standard : `errors/ → events/ → decisions/ → suivre signal_id`.
Cf `.claude/rules/log-debug-protocol.md`.

---

## Table ANOMALIE → DIAGNOSTIC

### A. Signal pas de trade (BUY ou SELL)

| Symptome Jackson | Code log | Categorie | Question |
|---|---|---|---|
| "BUY signale mais bot trade rien" | `VETO_BUY_COLOR_WALL` | decisions | Color_dn wall trop proche < seuil ? |
| "SHORT bloque systematiquement" | `VETO_SHORT_NO_WALL` | decisions | TP synthetic OU room < 1.5x SL ? |
| "Hors sessions actives" | `ECO_BLOCK` | decisions | Open US / Close US / pause overnight ? |
| "Tres faible conf" | `GATE_CONF_TOO_LOW` | decisions | Score < min_required ? |
| "MTF pas valide" | `GATE_MTF_INSUFFICIENT` | decisions | Bulls < 3/4 ou bears > 1 ? |
| "SELL bloque" | `GATE_SELL_AUTO_DISABLED` | decisions | Kill-switch auto declenche apres N SL ? |
| **"Haut/bas range achat/vente"** | `GATE_RANGE_BLOCK` | decisions | Confluence VA+IB+DAY+MQ_1D >=2/4 zone extreme ? |
| **"Regime adverse profile/day"** | `GATE_REGIME_BLOCK` | decisions | profile_shape==0 (D Range) OU day_type==1 (Normal) ? |
| **"Order flow contre direction"** | `GATE_ENTRY_QUALITY_BLOCK` | decisions | momentum_5b ET cvd_bar_delta BOTH contra direction ? |

**Cmd type unified : compter blocages funnel par categorie aujourd'hui** :
```bash
grep -E "GATE_(RANGE|REGIME|ENTRY_QUALITY|RISK|HEALTH|SESSION)_BLOCK|VETO_" \
  LOGS/decisions/decisions_$(date +%Y%m%d)_*.jsonl | \
  jq -r .code | sort | uniq -c | sort -rn
```

### A-bis. Funnel Bot 1 (8 steps)

Bot 1 utilise un funnel 8-step. Si trade pas pris, identifier QUEL step a bloque :
```bash
grep "FUNNEL_REJECT" LOGS/decisions/decisions_$(date +%Y%m%d)_paper.jsonl | \
  jq -r '.ctx.step + ": " + .ctx.reason' | sort | uniq -c
```

Steps actuels (mia_paper_trader FUNNEL_STEPS) :
1. `1_position_day` — already_position OR max_trades_day
2. `2_cooldown_cb` — cooldown_active OR circuit_breaker
3. `3_conseil` — conseil_attendre OR conseil_conflit OR sell_auto_disabled
4. `4_freshness` — freshness_not_new
5. `5_dedup` — signal_already_traded
6. `6_conf_mtf` — confidence_too_low OR mtf_insufficient
7. `6bis_bias` — bar_dmp_missing
8. `6ter_range` — range_extreme (RangeGate confluence VA+IB+DAY+MQ_1D)
9. `6quart_regime` — regime_loser_profile_shape OR regime_loser_day_type
10. `6cinq_entry_quality` — entry_quality_both_contra (momentum + CVD)
11. `7_sltp` — sltp_no_wall OR sltp_rr_low OR sltp_budget_exceeded
12. `8_payoff` — expected_payoff_low

Commande type :
```bash
# Compter blocages aujourd'hui par categorie
grep "GATE_.*_BLOCK\|VETO_" LOGS/decisions/decisions_YYYYMMDD_*.jsonl | jq -r .code | sort | uniq -c
```

### B. TP non atteint malgre prix favorable

| Symptome | Code | Categorie | Diagnostic |
|---|---|---|---|
| **"TP devant un mur"** (cas screen 30/04) | `SLTP_CAS4_TRIGGERED` | decisions | CAS 4 a corrige : verif tp_ticks vs wall_dist |
| "TP fixe arbitraire" | `SLTP_NO_VALID_WALL` | decisions | SLTPEngine reject → fallback FIXED applique |
| "MQ wall ignore" | `SLTP_MQ_WALL_USED` | decisions | Si absent : promotion TIER1/2 pas effective ? |
| "TP_STANDARD bizarre" | `SLTP_FALLBACK_STANDARD` | decisions | Verif reason_fallback (no_obstacle vs wall_far) |
| **"TP atteindre derriere mur (BUG)"** | `SLTP_TP_BEHIND_WALL_DETECTED` | decisions | CRITIQUE — anti-pattern echappe |

Commande type :
```bash
# Verifier que CAS 4 trigger sur trades MQ wall recents
grep "SLTP_CAS4_TRIGGERED" LOGS/decisions/decisions_YYYYMMDD_*.jsonl | jq '.ctx | {sym, wall_name, tp_ticks, rr}'

# Frequence MQ wall utilisation (post fix 30/04)
grep "SLTP_MQ_WALL_USED" LOGS/decisions/decisions_YYYYMMDD_*.jsonl | jq -s 'group_by(.ctx.wall_name) | map({wall: .[0].ctx.wall_name, count: length})'
```

### C. Trailing TR40_20 NQ (Bot 1)

| Symptome | Code | Categorie | Diagnostic |
|---|---|---|---|
| "Trail jamais arme" | absence `TRAILING_TR40_ARMED` | execution | MFE jamais >= 40% × SL_init ? |
| "Trail s'arme mais bouge pas" | `TRAILING_TR40_LOOSEN_BLOCK` | execution | Aligned SL en defaveur — calcul give_back ? |
| "Tick mis-align" | `TRAILING_TR40_NOT_ALIGNED` | execution | delta > 0.5t : bug calcul ou prix exotique |
| "Trail OK normal" | `TRAILING_TR40_UPDATED` | execution | old/new/give_back/count visible |

Commande type :
```bash
# Suivre cycle de vie trailing pour un trade NQ specifique
grep -E "TRAILING_TR40_(ARMED|UPDATED|LOOSEN_BLOCK)" LOGS/execution/execution_YYYYMMDD_paper.jsonl | jq -r '"\(.ts) \(.code) sl=\(.ctx.new_sl // .ctx.sl_aligned // \"N/A\") mfe=\(.ctx.mfe // \"N/A\")"'

# Compter trail update vs block aujourd'hui
grep "TRAILING_TR40_" LOGS/execution/*.jsonl | jq -r .code | sort | uniq -c
```

### D. Position fantome / OCO

| Symptome | Code | Categorie |
|---|---|---|
| "Position dans state.json sans bracket" | `STATE_VS_BROKER_MISMATCH` | execution |
| "Cancel orphan au boot" | `OCO_RECOVERY_BOOT` | events |
| "OCO orphan detected" | `OCO_ORPHAN_DETECTED` | execution |
| "Cancel envoye" | `OCO_CANCEL_OPPOSITE` | execution |

### E. Exceptions Python uncaught

| Symptome | Code | Categorie |
|---|---|---|
| **"TypeError signature kwargs"** (bug 30/04 _funnel_reject) | `FUNNEL_REJECT_CONTRACT_BUG` | events |
| "Exception SLTP" | `PY_EXCEPTION_HOT_PATH` (fn_name=SLTPEngine.evaluate_single) | events |
| "Exception bar processing" | `PY_EXCEPTION_HOT_PATH` (fn_name=_process_bar) | events |
| **"EMIT_FAIL code log inconnu"** | print direct stderr (`databento_paper_bot.err.log`) | err.log |

Commande type :
```bash
# Toutes les exceptions Python du jour
grep "PY_EXCEPTION_HOT_PATH" LOGS/events/events_YYYYMMDD_*.jsonl | jq '.ctx | {fn_name, exc_type, exc_msg}'

# EMIT_FAIL (codes log inconnus a ajouter au catalogue)
grep "EMIT_FAIL" LOGS/*paper_bot.err.log | sort | uniq -c
```

### F. Verifier MQ levels reellement vus par SLTPEngine

```bash
# Sur N derniers trades, quel mur SL/TP utilise ?
grep -E "SLTP_MQ_WALL_USED|TRADE_OPEN" LOGS/decisions/decisions_YYYYMMDD_*.jsonl | tail -50

# Frequence CAS 4 (anti-TP-derriere-mur) — bench post-fix 30/04
grep "SLTP_CAS4_TRIGGERED" LOGS/decisions/decisions_*.jsonl | wc -l
```

---

## Workflow pre-deploy : verifier que les 3 modifs sont bien actives en prod

Apres deploy mia_sltp.py + restart bots, on doit voir dans les 24h :

1. **MQ walls scannes** (au moins 1 trade) :
   ```bash
   grep "SLTP_MQ_WALL_USED" LOGS/decisions/decisions_$(date +%Y%m%d)_*.jsonl | head -3
   ```
   Si 0 → MQ levels pas presents dans les bars (verif `dist_mq_call` colonne)

2. **CAS 4 declenche occasionnellement** (~5-15% des trades attendu) :
   ```bash
   grep "SLTP_CAS4_TRIGGERED" LOGS/decisions/decisions_$(date +%Y%m%d)_*.jsonl | head -3
   ```
   Si 0 et beaucoup de TP_STANDARD : code probablement non-deploye ou flag pas set

3. **Trailing TR40 arme et update** (au moins 1 trade NQ avec MFE >= 40%) :
   ```bash
   grep "TRAILING_TR40_ARMED" LOGS/execution/execution_$(date +%Y%m%d)_paper.jsonl
   ```

4. **Bot 2 vetos visibles** :
   ```bash
   grep -E "VETO_BUY_COLOR_WALL|VETO_SHORT_NO_WALL" LOGS/decisions/decisions_$(date +%Y%m%d)_databento_paper.jsonl | wc -l
   ```

---

## Anti-patterns interdits (rappel)

- ❌ Lire 30j de logs dans le contexte Claude (overflow garanti)
- ❌ Chercher sans categorie + date precise
- ❌ Ignorer `.code` stable, se baser sur prose fr variable
- ❌ Diagnostiquer sans consulter `errors/` en premier
- ❌ Affirmer "feature deployee" sans verifier emit dans logs

---

## Liens

- Catalog codes : `CORE/log_catalog.py`
- Module logging : `CORE/logging_v2.py`
- Protocole debug : `.claude/rules/log-debug-protocol.md`
- Memoire : `feedback_log_debug_protocol.md` (pattern anti-oubli)
