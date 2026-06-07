# Code Review #1 — Batch B3 (F22 + F12 + F8 + F9)

**Reviewer** : code-reviewer (impitoyable)
**Date** : 2026-06-07
**Scope** : 29 features port C++ Sierra, schema 3.7.20, n_cols 347 -> 376

---

## Verdict review #1 code-reviewer B3

- **VERDICT** : **GO-AVEC-RESERVES**
- **Score** : 7.5/10

**Justification** : le code des 4 helpers F22/F12/F8/F9 est globalement solide,
respecte les conventions B1/B2, gere proprement DMP_INVALID et les PersistVars.
**MAIS** un bug C++ probable dans la persistance du hash F9 (perte de precision
float -> uint32_t) peut faire flagger `is_roll_day=1` faussement, et plusieurs
incoherences de comptage (28 vs 29) traînent dans les commentaires et un fichier
Python ; aucune n'est bloquante prod si le bug F9 est verifie/corrige.

---

## Forces

1. **Architecture 4 headers separes** (DMP_F22 / DMP_F12 / DMP_F8 / DMP_F9) :
   coherent avec le pattern B2 (3 headers F4/F2/F23) et superieur a B1 (1 seul
   header pour 37 features). Chaque famille est isolee, sequencing audit (F22
   -> F12 -> F8 -> F9) explicite. Maintenance et lecture facilitee.

2. **PersistVars sans conflit** : audit cross-codebase exhaustif :
   - F12 : 205-206 ✓ (libres entre B2 PDH/PDL 203-204 et F9 207-210)
   - F9 : 207-210 ✓
   - Pas de conflit avec 50-74 (HVN/LVN), 100-114 (ProfileShape), 117-121 (IB+RTH),
     128-137 (PREV_PRICE, RETEST), 140-161 (EDGE prices), 200-204 (delta_div + B2).

3. **Reset Full Recalc Index 0** pour PersistVars F12 (l.237-240) et F9 (l.121-126).
   Critique pour eviter pollution etat sur reload DLL en session ouverte.

4. **DMP_INVALID propagation explicite** : F22 propage si parent (pct_in_range)
   invalide ; F12 retourne INVALID si OHLC casse ou ATR null ; F8 INVALID si
   `mins_et` hors plage [0, 1440) ; F9 INVALID si contract vide ou
   trading_day <= 0. Pas de silent fallback detecte sur ce point.

5. **F8 anti-sentinel -1** : choix correct de DMP_INVALID pour `mins_since_news` /
   `mins_to_next_news` hors fenetre 7h15-9h30 ET. Pattern documente l.150-167 +
   test parite verifie absence de -1 via `check_mins_since_to_news_invalid()`.
   Anti-pattern Python sentinel evite, LightGBM verra `null` propre.

6. **F12 reuse explicite** du chemin Python `body > 2*ATR_points` (vs reuse SC
   bar_long_up_bar) avec WARNING explicite l.39-44 : "NE PAS reutiliser
   r.bar_long_up_bar ici, c'est un autre signal (Sierra Edge Zone)". Anti pattern
   11 (confondre features de meme nom). Solide.

7. **F9 manual_switch protection** : design 2-letter root correct par concept
   (ESH26 vs ESM26 = meme root → roll legitime, ESM26 vs NQM26 = root different
   → manual switch). Documentation l.34-41 du header explicite.

8. **F8 tableau NEWS_MINS tri ASC** (constexpr l.53-60) : scan O(N=6) trivial,
   logique "dernier <= mins_et" et "premier > mins_et" correcte avec break early.

9. **mins_et exposed seulement dans struct DMP_RawData** mais non emis au
   JSONL : decision intentionnelle documentee, downstream recalcule depuis ts.
   Trade-off acceptable (1 colonne en moins) MAIS attention impact debug
   (cf R3 ci-dessous).

10. **Range sanity tests** dans test_parity_B3.py couvre les boolean (0/1
    strict) et plages (0-100, 0-1, 0-3). Bonne discipline contre regression.

---

## Reserves bloquantes (a fixer AVANT commit)

### R1 — BUG CRITIQUE F9 : cast hash uint32_t -> float -> uint32_t perd de precision

**Fichier** : `DMP_F9_Roll.h:164, 168, 183`

**Probleme** :
```cpp
last_hash_persist = (float)cur_hash;     // l.164
// ...
uint32_t prev_hash = (uint32_t)last_hash_persist;  // l.168
```

`float` IEEE 754 32-bit n'a que **24 bits de mantissa** : il preserve les
entiers exactement uniquement jusqu'a 2^24 = 16'777'216. Au-dela, **arrondi**.

Le hash djb2 d'un string comme `"ESH26-CME"` produit aisement des valeurs
> 2^24 (max possible 2^32 - 1). Donc :
```cpp
uint32_t cur_hash = DMP_F9_HashContract("ESH26-CME");  // ex: 3'421'905'672
float    f       = (float)cur_hash;                     // ARRONDI ~3'421'905'920
uint32_t roundtrip = (uint32_t)f;                       // 3'421'905'920 != cur_hash !
```

**Consequence** : a chaque bar, `prev_hash != cur_hash` peut etre TRUE meme
si sc.Symbol n'a pas change. La protection root (cur_root == prev_root)
laisse passer ce cas (root identique) → `roll_flag_persist = 1.0f` flagge
en permanence. **is_roll_day fire faux positif sur quasi toutes les sessions**.

**Note** : cur_root est < 2^17 (65536 max pour 2 chars ASCII), donc roundtrip
preserve. Mais hash NON.

**Fix recommande** (3 options, par ordre de preference) :

**Option A (recommandee)** : utiliser **deux** PersistVars pour stocker le
hash en 2 morceaux de 16 bits :
```cpp
constexpr int DMP_PERSIST_F9_LAST_HASH_HI = 207;   // bits 16-31
constexpr int DMP_PERSIST_F9_LAST_HASH_LO = 211;   // bits 0-15 (NEW)
// stockage : hi = hash >> 16, lo = hash & 0xFFFF (les deux < 2^17 = preserve)
// lecture  : prev_hash = ((uint32_t)hi << 16) | (uint32_t)lo
```
Necessite ajouter 1 PersistVar (212 disponible).

**Option B** : utiliser `sc.GetPersistentInt(207)` au lieu de
`GetPersistentFloat`. ACSIL fournit `GetPersistentInt` qui prend un int 32-bit
sans risque de perte de precision. Verifier que 207 n'est pas deja utilise
pour un Int (l'audit cross-codebase montre que 207 = libre pour les deux
namespaces). **Le plus simple si Sierra ACSIL le permet.**

**Option C** : remplacer le hash djb2 par une comparaison `strncmp(d.contract,
last_contract_str, 32)` avec un buffer persistant — necessite d'ajouter un
chunk de PersistVars pour stocker 32 caracteres (8 floats x 4 chars). Plus
lourd, moins propre.

**Severite** : **BLOQUANTE**. Un is_roll_day=1 faux positif fait que le
RiskManager (et tout consumer ML downstream) declenche des comportements
"jour de roll" tous les jours = decision business cassee.

**Verification** : ecrire un test C++ unitaire qui prend 10 hashes
deterministes et verifie roundtrip preservation. Si Sierra ACSIL fournit
`GetPersistentUInt32` c'est encore plus simple.

---

### R2 — INCOHERENCE COMPTAGE 28 vs 29 dans 5+ endroits

Le code lui-meme expose **29 features** (4 F22 + 10 F12 + 14 F8 + 1 F9),
correctement comptabilises dans :
- `DMP_Writer.h:574` : `n_columns: 376` ✓
- `dmp_validator.py:178` : `EXPECTED_COLS_3720 = 376` ✓
- CSV header `DMP_Transform.h:2061-2071` : 29 colonnes B3 listees ✓
- meta JSON `DMP_Writer.h:763-774` : 29 colonnes B3 listees ✓
- JSONL serialisation `DMP_Writer.h:1348-1384` : 29 KV* ✓

**MAIS** plusieurs commentaires/comptages textuels disent **28** :
| Fichier:Ligne | Texte incorrect | Correction |
|---|---|---|
| `DMP_Transform.h:663` | `B3 — F22 + F12 + F8 + F9 (28 features)` | 29 |
| `DMP_Transform.h:665` | `28 features Python live_enriched manquantes` | 29 |
| `DMP_Transform.h:666` | `28 GO PORT, 1 DEFER... 4 DROP (... discount_zone doublon premium_zone)` | 29 GO PORT, 3 DROP (sans discount_zone) — incoherent avec Jackson rectif ! |
| `DMP_Transform.h:708` | `n_cols 347 -> 375 = +28 strict` | 347 -> 376 = +29 |
| `DMP_Transform.h:752` | `4 headers... 1 famille a la fois` (OK) + commentaire suivant ligne 753 `3 features Position session/MQ daily` | 4 features F22 (avec discount_zone) |
| `DMP_Transform.h:753-756` | bloc include comment `3+10+14+1=28` | 4+10+14+1=29 |
| `DMP_Transform.h:1338,1340` | `B3 — F22 + F12 + F8 + F9 (28 champs)` + `F22 (3) -> ... = 28 features` | 29 champs, F22 (4) -> ... = 29 |
| `DMP_Writer.h:761` | `B3 (Schema 3.7.20) — F22 + F12 + F8 + F9 (28 features)` | 29 |
| `DMP_Writer.h:768` | `F8 — News (14 — mins_et utilise en interne)` (OK 14) |
| `DMP_F22_PositionRange.h:5` | `Role : Exposer 3 features` | 4 features |
| `DMP_F22_PositionRange.h:100` | `Remplit les 3 champs F22` | 4 champs |
| `DMP_Config.h:88` | `mins_et (scalar [0, 1440) DST-aware)` listee comme feature dans le groupe F8 | mins_et N'EST PAS expose au JSONL (cf decision audit) → SUPPRIMER de la liste F8 docu Config |
| `DMP_Config.h:93` | `Schema 347 -> 376 colonnes (+29)` ✓ (lui est correct) |
| `DMP_Config.h:97-99` | `+28 fields struct + 4 includes B3 + 4 appels`, `+28 KV serialisation + 28 columns meta JSON` | 29 partout |
| `dmp_validator.py:82` | `# 3.7.20 = Batch B3 F22 + F12 + F8 + F9 (375 cols = 347 + 28 : 3 PositionRange + ...)` | 376 cols = 347 + 29 : 4 PositionRange + ... |
| `tools/test_parity_B3.py:5,471` | `28 features exposees par le port B3` | 29 features |
| `tools/test_parity_B3.py:471` | print `28 features` | 29 features |

**Severite** : **MODEREE**. Le code et le validator Python sont coherents
(376 cols, 29 features). MAIS les commentaires mensongers vont semer la
confusion en maintenance future (qui croira "il manque une colonne dans
struct"?). Pire : ligne 666 Transform.h dit "4 DROP (incluant discount_zone
doublon)" — qui contredit la rectif Jackson 22:50 GARDE.

**Fix recommande** : sed global remplacement `28` -> `29` dans les
commentaires B3, et reformulation du paragraphe Transform.h:663-668 pour
refleter rectif Jackson (3 DROP, 1 DEFER, 0 inclus discount_zone).

---

### R3 — F9 manual_switch SAFE-RESET manquant entre 2 instruments

**Fichier** : `DMP_F9_Roll.h:171-185`

**Probleme** : quand Jackson fait un manual switch ES → NQ (cur_root != prev_root),
le code dit "NE PAS toucher a roll_flag_persist (reste a sa valeur courante)".

Mais **last_hash_persist et last_root_persist sont mis a jour** (l.183-184) au
nouveau contract. Donc :
1. ES (root ES, hash H1) → bar normal, last_root=ES, last_hash=H1
2. Manual switch NQ (root NQ, hash H2) → last_root=NQ, last_hash=H2
3. Sur NQ, si le contract roll *legitimement* (NQM26 → NQU26) → flag 1.

OK pour ce cas. **MAIS** :
1. ES roll legitime ESH26 → ESM26 jour J : flag=1, date=J
2. Jackson manual switch ES → NQ jour J apres roll : last_root=NQ (last_hash mis a jour)
3. roll_flag_persist **reste = 1.0f** pour la session J (jour roll ES J),
   mais on est maintenant sur NQ qui n'a pas eu de roll
4. → `is_roll_day = 1` sur NQ ce jour-la = **faux positif**

**Severite** : MODEREE. Cas operationnel rare (manual switch jour roll), mais
non-trivial si trader voit dashboard "is_roll_day=1 NQ" et croit qu'il y a eu
un roll NQ.

**Fix recommande** : quand manual_switch detecte (cur_root != prev_root, root
both valid), forcer `roll_flag_persist = 0.0f` avant update last_root/hash.
Documentation : "Manual switch instrument → reset flag, on n'herite pas du
contexte roll de l'ancien instrument."

---

## Reserves importantes (non-bloquantes, a tracker)

### R4 — F12 bar_no_trade trop laxiste sur fpbs_delta INVALID

**Fichier** : `DMP_F12_BarShape.h:208-215`

```cpp
if (DMP_F12_IsInvalid(r.fpbs_delta)) {
    f.bar_no_trade = 1.0f;
}
```

Si l'etude FPBS n'est pas peinte (cas reload SC ou bug temporaire),
fpbs_delta = DMP_INVALID → `bar_no_trade=1` systematiquement. Pas une vraie
"no trade" mais une "data missing". Bot/ML va apprendre "FPBS down" comme
signal de "pas de trade".

**Fix recommande** : distinguer 3 etats — fpbs_delta INVALID → DMP_INVALID
(unknown), fpbs_delta=0 ou |delta|<0.5 → 1 (no trade), sinon → 0 (trade).
Eviter le silent fallback "missing data = feature".

### R5 — F12 long_dn_up_pattern / long_up_dn_pattern : convention valeur "0 par defaut" si t-1 invalide

**Fichier** : `DMP_F12_BarShape.h:247-263`

Si PersistVar t-1 invalide (1er bar ou apres reset) :
```cpp
f.long_dn_up_pattern = 0.0f;  // PAS DMP_INVALID
```

Documentation explicite (l.249-250) : "0 = pas detecte est semanticement OK".
Defendable mais oblige downstream a distinguer "vraiment 0" vs "1er bar sans
historique" via une autre feature (bars_since_start ?). Pour LightGBM qui
voit beaucoup de 0 sur quelques milliers de bars, l'impact reste marginal,
mais c'est un compromis de design qui colle Python.

**Fix optionnel** : passer a DMP_INVALID pour le 1er bar, downstream gere null.
Plus propre semantiquement.

### R6 — F22 `range < 0.01f` magic number

**Fichiers** : `DMP_F22_PositionRange.h:76, 89`, `DMP_F12_BarShape.h:132, 148`

```cpp
if (range < 0.01f) return DMP_INVALID;
```

0.01 point = 4 ticks pour ES/NQ (0.25 tick), MAIS 0.1 tick pour MGC
(tick=0.10). Pour MGC, range=0.05 point = 0.5 tick serait considere INVALID
alors que c'est legitime.

**Fix recommande** : utiliser `tick * 0.04f` (= 1% du tick) comme seuil
adaptatif, ou bien `tick_size * 0.5f` pour exclure les ranges < demi-tick.
Pas critique pour ES/NQ B3 mais sera bug futur quand MGC sera ajoute au DMP
(Bot 1 MGC roadmap).

### R7 — F8 sentinel `IntToFeature` helper inutile (dead code partial)

**Fichier** : `DMP_F8_News.h:76-78`

```cpp
static inline float DMP_F8_IntToFeature(int v) {
    return (float)v;
}
```

Commentaire dit "si v < 0 OU sentinel -> retourne default_val. Sinon (float)v".
Le code ne fait que `(float)v`. Le commentaire est mensonger. Soit la logique
manque (le `if v<0` n'est pas implementee), soit le commentaire est obsolete.

**Fix recommande** : soit retirer le helper (juste utiliser `(float)v` inline,
3 occurrences), soit implementer le check `if v<0 return DMP_INVALID`.
Actuellement helper trompeur.

### R8 — Documentation mins_et N'EST PAS expose JSONL mais visible en debug ?

**Fichier** : `DMP_F8_News.h:11-15`

Decision documentee : `mins_et` reste interne (`r.mins_et`), pas serialise.
**Trade-off operationnel** :
- AVANTAGE : 1 colonne en moins, n_cols stable.
- INCONVENIENT : si demain Jackson doit debugger "pourquoi is_news_730=0 a
  7h30:30?", il doit recalculer mins_et depuis ts → friction. Pour debug
  prod, exposer `mins_et` simplifierait. Avec 376 cols, 1 de plus ne casse
  rien.

**Fix optionnel** : reconsiderer cette decision si Jackson rapporte friction
debug news timing. Pas bloquant.

### R9 — F22 `position_in_range` HIGH_CORR_INSTRUMENT — VERIFIE OK

Documentation dit (DMP_F22_PositionRange.h:46-48) :
> ATTENTION : `position_in_range` est tagge HIGH_CORR_INSTRUMENT par audit
> 28/04 (ks=1.044). Flagger NATURALLY_DIFFERENT cote quality_validator.py

**Verification effectuee** : `quality_validator.py:229` contient bien
`"position_in_range"` dans la liste `NATURALLY_DIFFERENT` (l.127).
**Pas de fix necessaire.**

NB : verifier que les 3 autres F22 (pct_in_range, premium_zone, discount_zone)
sont legitimes en SHARED_FEATURES (calculees depuis sess_high/low identiques
pour ES et NQ par convention session intraday).

### R10 — F12 ATR cast TICKS → POINTS hardcode tick fallback 0.25f

**Fichier** : `DMP_F12_BarShape.h:128`

```cpp
const float tick  = (r.tick_size > 0.0f) ? r.tick_size : 0.25f;
```

Fallback silencieux a 0.25f si tick_size invalide. Si Sierra retourne
tick_size = 0 (bug), le calcul ATR_points = atr_14m * 0.25 sera **faux pour
MGC** (vrai tick = 0.10).

**Fix recommande** : si `r.tick_size <= 0.0f`, retourner directement
DMP_INVALID pour les features F12. Le silent fallback 0.25 contredit la
regle `tick-size-policy.md` ligne 70-78 ("Pas de fallback silencieux sans
warning"). Pour ES/NQ ce silent fallback est inoffensif (0.25 correct), mais
pour MGC futur c'est un bug latent.

---

## Verification coherence 29 features

| Endroit | Compte detecte | Status |
|---|---|---|
| struct DMP_MLFeatures (Transform.h:687-726) | 4+10+14+1 = **29** | OK |
| CSV header (Transform.h:2061-2071) | 4+10+14+1 = **29** | OK |
| KV2/KVB/KVE serialisation (Writer.h:1348-1384) | 4+10+14+1 = **29** | OK |
| meta JSON columns (Writer.h:763-774) | 4+10+14+1 = **29** | OK |
| meta JSON feature_families (Writer.h:616-627) | 4+10+14+1 = **29** | OK |
| n_columns (Writer.h:574) | **376** | OK |
| dmp_validator.py EXPECTED_COLS_3720 (l.178) | **376** | OK |
| dmp_validator.py has_b3_features (l.338-343) | check 4 cols cles (pct_in_range, bar_body_pct, is_news_730, is_roll_day) | OK |
| test_parity_B3.py B3_FEATURES dict (l.55-89) | **29** | OK |
| test_parity_B3.py FEATURE_RANGES (l.93-127) | **29** | OK |
| **Commentaires textuels** | divers "28 features" | **FAIL** (R2) |

**Verdict** : le code C++ + JSONL + Python validator sont **bit-for-bit coherents
en 29 features / 376 colonnes**. Seuls les commentaires sont incoherents (R2).

---

## Patterns reproductibles B4+

### Pattern 1 — Ne JAMAIS persister un uint32/uint64 dans un float Sierra

Si un futur batch a besoin de persister un identifiant compact entre bars,
utiliser :
- `sc.GetPersistentInt(N)` (32 bits exact)
- OU 2 PersistentFloat pour stocker hi/lo en 16-bits chacun
- JAMAIS `(float)cur_hash` -> `(uint32_t)f` (perte mantissa pour hash > 2^24)

Documenter cette regle dans `.claude/rules/cpp.md` ou
`DOCS/PERSISTVARS_BEST_PRACTICES.md`.

### Pattern 2 — Sequencing par bloc avec commentaire "1 famille a la fois"

L'organisation B3 (F22 → F12 → F8 → F9) avec sequencing explicite l.1881-1889
de Transform.h est exemplaire. Reproduire B4+ avec meme template.

### Pattern 3 — Comptage de features = SOURCE UNIQUE

Pour eviter les R2-like a chaque batch, ajouter un script de verification
post-commit qui :
1. Parse `DMP_Transform.h` pour extraire les fields B3 (count = 29)
2. Parse `DMP_Writer.h` pour compter les KV* B3 (count = 29)
3. Parse `dmp_validator.py` pour extraire `EXPECTED_COLS_BX`
4. Verifie egalite. Fail commit si divergence.

Format `tools/check_schema_coherence.py`.

### Pattern 4 — sanity tests avec tolerance par famille

Test parity B3 distingue parite stricte (F22, F8, F9) vs info-only (F12 a
cause de divergence ATR). Pattern a reproduire dans test_parity_B4+.

### Pattern 5 — Audit cross-PersistVar avant ajout

Audit B3 a verifie 50-211 pour eviter conflit. Continuer cette discipline.
Backlog : creer un fichier de registre `DOCS/PERSISTVARS_REGISTRY.md`
explicite, generation automatique depuis grep des `DMP_P[SR]?_*`.

---

## Critere GO deploy

**Avant deploy VPS, OBLIGATOIRE** :

1. **R1 FIX** : corriger le cast hash float in DMP_F9_Roll.h (Option B
   recommandee si Sierra ACSIL supporte `GetPersistentInt`). Test unitaire
   roundtrip preservation sur 10 hashes deterministes.

2. **R2 FIX (cosmetique mais important)** : corriger comptages dans les 11+
   endroits (commentaires + ligne 82 dmp_validator.py + test_parity_B3.py
   strings). Surtout : reformuler Transform.h:663-668 pour refleter rectif
   Jackson 22:50 (discount_zone GARDE, 3 DROP).

3. **R3 FIX** : ajouter `roll_flag_persist = 0.0f` au moment du manual_switch
   detecte dans DMP_F9_Roll.h:179. Documenter.

4. **R9 VERIFY** : grep quality_validator.py pour position_in_range +
   NATURALLY_DIFFERENT. Si absent, ajouter.

**Recommande (non-bloquant)** :

5. **R4** : differencier fpbs_delta INVALID vs delta=0 dans bar_no_trade.
6. **R7** : nettoyer helper DMP_F8_IntToFeature ou son commentaire.
7. **R10** : remplacer fallback silencieux tick_size 0.25 par DMP_INVALID.

**Apres fixes** :

- Compiler dans Sierra Chart Build Custom Studies DLL (5 sec).
- Reloader Charts 23/24/25/26 + Charts 30/31.
- Verifier au moins 60 min de bars live ES + NQ avec :
  - is_roll_day = 0 (pas de roll en cours juin 2026) : CRITIQUE pour valider fix R1.
  - is_news_HHMM fire correctement aux 6 heures d'event (lancer test_parity_B3.py).
  - test_parity_B3.py : 29 features all PASS sanity range.
- Update INCIDENT_LOG si bug R1 reproduit (categorie `PATTERN_11`).
- Update DOCS/BOT_CHANGELOG.md entry post-deploy.

---

## Notes de fin

**Effort agent invest** : ~30 min (lecture 4 headers + Reader + Transform +
Writer + validator + test + cross-grep PersistVars).

**Niveau de confiance verdict** : eleve sur R1 (bug reproductible math
IEEE 754), eleve sur R2 (cosmetique trivial), modere sur R3 (cas operationnel
rare), faible sur R4-R10 (nuances).

**Continuation review #2** : Plan agent cross-check obligatoire (Tier 1
critical-tasks-review.md) avant commit.
