# Checklist — Ajout d'une feature (batch et/ou streaming)

**Source** : Review #3 R3 GO NET (15/05/2026) + INCIDENT_LOG 15/05 11:50 Pattern V1 cousin
(asymmetrie semantique batch/stream) + IDEAS_BACKLOG dette `check_feature_added_consistency`.

**Usage** : a parcourir AVANT commit d'un PR introduisant une nouvelle feature
dans pipeline ML (live_enricher streaming, build_dataset_v4_phase_b, phase_b_helpers,
rolling_features, game_changers, etc.).

**Trigger** : toute ligne `out["nom_feature"] = ...` ou `df["nom_feature"] = ...`
ajoutee dans un module pipeline.

---

## Checklist (6 points obligatoires)

### 1. SET `*_GENERATED` du module mis a jour

- [ ] Si le module a un set `MODULE_GENERATED = {...}` (cf
      `PHASE_B_PLUS_GENERATED`, `PHASE_B_PLUS_PLUS_GENERATED`,
      `EDGE_ZONES_GENERATED`, `PHASE_D_DALTON_GENERATED`, etc.) → ajouter
      la nouvelle feature.
- [ ] Si streaming-only, verifier qu'aucun set `*_STREAMING_GENERATED` separe
      necessaire (cf `phase_b_v6_complete.py`).
- [ ] Si batch produit la feature mais streaming non (ou inverse), DOCUMENTER
      l'asymmetrie dans IDEAS_BACKLOG comme DETTE.

**Pourquoi** : `drop_existing` idempotent dans `apply_all_*` enleve les cols
existantes avant recalcul. Sans ajout au SET, re-run = duplication silencieuse
(2 versions de la feature, deuxieme ecrase la 1ere via merge).

### 2. Path no-trades / footprint-absent (init defaults)

- [ ] Si feature derivee de trades/footprint : ajouter init `out["nom"] = X`
      dans le code path "trades_df.empty" / "vap_absent" / "no_footprint".
- [ ] Choisir default value qui represente correctement l'absence
      (np.nan pour valeurs continues, 0 pour counters, -1 pour categories).

**Pourquoi** : sans init no-trades, les bars sans donnees retournent dict
sans la cle -> downstream consumer fait `.get()` qui retourne None silencieux
-> Pattern V1 (feature dead inaperçue).

### 3. Mirror batch + stream alignement

- [ ] Si batch existe (`module_X.py:apply_X` ou `add_X`), verifier que le
      streaming (`module_X_streaming.py:add_X_streaming`) produit la MEME
      feature avec MEME semantique.
- [ ] **CRITIQUE Pattern V1 cousin** : verifier que le **scope groupby** match.
      Si batch `groupby("session_date_trading")` → streaming DOIT reset sur
      `session_date_trading` change, PAS `date_et`. Cf INCIDENT_LOG 15/05
      11:50 game_changers.
- [ ] Verifier scope SEED M-1 : si batch utilise seed M-1 (cf
      `process_partition` build_dataset_v4_phase_b.py:550), streaming = pas
      de visibility seed → comparaison sur les 1ers jours du mois = drift
      legitime. Documenter dans test V4 parity (`captured_dates_*` filter).

**Pourquoi** : detection precoce du Pattern V1 cousin V2 (semantic mismatch).
Cf `INCIDENT_LOG.md` Pattern_11 occurrences.

### 4. `log_catalog.py` (si emit log nouveau)

- [ ] Si la nouvelle feature emet un log (`_emit_log("CODE_X", ...)`), AJOUTER
      le code dans `CORE/log_catalog.py:LOG_CODES`.
- [ ] Format strict : `(LogLevel.{INFO|MAJEUR|CRITIQUE|ALERTE}, "{cat}", "{template}")`
- [ ] Categorie correcte :
  - `decisions` : gates, filtres, score, tier, veto
  - `execution` : ordres, fills, cancels, brackets
  - `events` : boot, shutdown, kill_switch, heartbeat, enricher
- [ ] Tester emit fonctionne en local : `grep CODE_X CORE/log_catalog.py` doit
      matcher AVANT le commit (sinon KeyError silent au runtime).

**Pourquoi** : regle souveraine logs 01/05 (Jackson) — code non enregistre
= silent no-op + audit J+1 grep impossible.

### 5. Test `critical_keys` si feature ML-critical

- [ ] Si la feature alimente le ML training (`ML_EXCLUDE_FEATURES` exclusion
      non-applicable, donc lue par `get_ml_features()`) → ajouter aux
      `critical_keys` dans `TOOLS/test_live_enricher_integration.py:433-468`.
- [ ] Tester PRESENCE + variance > 0 (pas juste presence — sinon Pattern V1
      passe si valeur constante).

**Pourquoi** : test integration verifie que la feature arrive bien au modele.
Si manquante → modele entraine sans cette feature mais inference l'attend
(ou inverse) → drift train/inference garanti.

### 6. INCIDENT_LOG patterns connus

- [ ] Grep `DOCS/INCIDENT_LOG.md` pour la categorie matching la modification
      (cf `PATTERN_11`, `VALIDATION_MISS`, `COMMENT_FALSE`).
- [ ] Verifier que la feature ne reproduit pas un pattern documente.
- [ ] Si nouvelle decouverte de Pattern V1 cousin → ajouter entry INCIDENT_LOG.

**Pourquoi** : evite repetition d'erreur connue. Cf `.claude/rules/incident-protocol.md`.

---

## Etapes post-commit obligatoires

### A. Test integration en local

- [ ] Lancer `pytest tests/test_live_enricher_parity_v4.py -v` (si feature
      live_enricher).
- [ ] Lancer `python TOOLS/test_engine_parity.py --engine all` (si refactor
      streaming sub-engine).
- [ ] Verifier 100% PASS — sinon corriger avant push.

### B. Verification J+1 logs reels (post-deploy)

- [ ] Si feature avec emit log : `grep <CODE> LOGS/*/{date}.jsonl` doit
      retourner > 0 hits.
- [ ] Si 0 hits : instrumentation muette → INCIDENT_LOG categorie
      `VALIDATION_MISS` + investigate.

### C. Update CHANGELOG si change moteur decision

- [ ] Si la feature modifie le scoring / gates / sizing → entry
      `DOCS/BOT_CHANGELOG.md` (cf CLAUDE.md regle 25/04).

---

## Anti-patterns interdits

- ❌ Ajouter feature sans test parite batch/stream (sauf streaming-only documente)
- ❌ Silent fallback `try: ... except: pass` sans `_emit_log`
- ❌ Reutiliser nom de feature batch existante avec semantique differente en stream
  (cf R1 Pass 4 `diag_imbalance` vs `diag_imbalance_ofi_proxy` — RENAME obligatoire)
- ❌ Ajouter au critical_keys sans test variance (presence only = piege Pattern V1)
- ❌ Code log nouveau sans entry log_catalog.py (KeyError silent runtime)

---

## Lint guard automatique (en parallele)

- `tools/check_feature_added_consistency.py` execute les checks 1-4
  automatiquement (cf IDEAS_BACKLOG dette 15/05 + commit suivant).
- Pre-commit hook installable via `python tools/install_precommit_hook.py`
  (cf `.claude/rules/tick-size-policy.md` pattern existant).
- En CI : exit 1 si check critique fail, warning si MEDIUM.

---

## References

- `.claude/rules/critical-tasks-review.md` — protocole agent review
- `.claude/rules/module-review-protocol.md` — STEPS 1-6 pour module V2-bis
- `.claude/rules/log-debug-protocol.md` — regle souveraine logs 01/05
- `DOCS/INCIDENT_LOG.md` — Pattern V1 cousins documentes (2 entries 15/05)
- `DOCS/IDEAS_BACKLOG.md` — dette technique avec deadlines
- `tests/test_live_enricher_parity_v4.py` — exemple V4 oracle test
- `TOOLS/test_engine_parity.py` — framework parite batch/stream (18 engines)
