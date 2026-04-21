# V2-bis C++ ACSIL — Design doc P0 (v1.4)

**Date** : 2026-04-20
**Version** : 1.4 (post 4 reviews Plan agent adversarial — 49 items appliques au total)
**Statut** : DRAFT P0 — re-audit final Plan agent en cours (viser GO SANS RESERVE)
**Auteur** : Jackson + Claude (collaboration 19-20/04)
**Gates** :
  - P0→P1 : V2CLEAN **shadow mode stable 7j** (cible debut juin 2026) — decouple du paper GO
  - P4→P5 : V2CLEAN paper GO + V2-bis paper **100 trades clean** (pas "10 jours")
**Estimation implementation** : 9.5-10.5 semaines apres gate P0→P1 (P1 1.5 + P2 3 + P3 1 + P4 4-5)

## Changelog v1.4 (post 4e review Plan agent 20/04 soir final — 10 reserves mineures appliquees)

10 corrections editoriales "zero dette" Jackson :
1. Section 4.2 body : `ring buffer 100` → `300` (alignement C4 v1.3 qui l'avait laisse en Section 5.1 bis seulement)
2. Section 4.13 : 78 tests v1.1 supprime, remplace par "79 tests v1.3" coherent (suppression contradiction interne)
3. Section 6 tableau decisions : "78 tests v1.2" → "79 tests v1.3"
4. P1 gate : formule recalibree "~14 tests" (6 Config + 8 StatePersistence). Interfaces/Mock = scaffolding pas tests propres
5. P2 gate : 65 tests additionnels (pas 54), total 79
6. Section 3 tree : "717 LOC Python" → "716" (alignement avec Section 4.4)
7. Changelog v1.2 : refs 4.7/4.9 notees "(v1.2, devenues 4.11/4.13 en v1.3)"
8. Section 14 : meme re-ancrage refs historiques
9. P4 : 2-3 sem → 4-5 sem realiste (100 trades atteignables a 3-5 trades/jour)
10. Section 10 roadmap : Gate P0→P1 "formel" debloque fin S6 (shadow stable), pre-work P1 possible S5 sans crosser gate

**Erreur math historique corrigee** :
- Changelog v1.1 : "sous-estime 95%" incorrect → "sous-estime ~49% vs realite"

**Section 5 renumerotation** :
- 5.1 bis → 5.2 (Dedup cross-restart)
- 5.2 → 5.3 (V2CLEAN heartbeat)
- 5.3 → 5.4 (V2-bis → SC ACSIL)
- 5.4 → 5.5 (Feedback loop)
Refs croisees correspondantes mises a jour.

## Changelog v1.3 (post re-re-review Plan agent 20/04 soir — 21 reserves appliquees)

**6 critiques** :
- C1 : Section 3 → 9 interfaces (retire IMarketData/IClock doublons)
- C2 : Retire ref fantome `V2_KillSwitch` (R8 reportee P1)
- C3 : Section 4.1.1 "Chain of gates" documentee explicitement (HealthCheck → Session → Risk → Execute)
- C4 : Ring buffer dedup 100 → 300 avec justification calculee (480 signaux/4h downtime worst case)
- C5 : Scenario zombie V2CLEAN couvert via `last_signal_emitted_ts_ms` (warning 15 min, block 30 min RTH)
- C6 : 3 refs croisees brisees corrigees

**7 majeures** :
- M1 : Numerotation Section 4 lineaire 4.1→4.13 (ordre physique coherent)
- M2 : Section 6 tableau stale "50+ tests" → "79 tests v1.3" (recalibre a v1.3 post M5)
- M3 : Frequence heartbeat 1s (pas 5s) coherent 4.7 + 5.2
- M4 : Timeline 7.5-8.5 sem exact (sum phases)
- M5 : SessionGuard 9 tests clarifie (+1 statique MarketDataProvider), total 79
- M6 : P1 gate "~28 tests" (pas 78 — impossible en P1 seule)
- M7 : Test statique 8.4 #4 renforce : SnapshotWriter ET V2_Main avec meme anti-branching rigueur

**8 mineures** :
- m1-m8 : changelog formulation, version tags, helpers test definis, LOC V1 DNA precises, 716 LOC Python (pas 717), etc.

**4 scenarios residuels** (Section 7.10-7.13) :
- 7.10 flatten_all sans position → no-op + log
- 7.11 meme ts + signal_id differents → garder dernier + log anomaly
- 7.12 rollover contrat → reject + Discord alert
- 7.13 exit_manual pendant kill-switch → execute closing (pas bloque)

## Changelog v1.2 (post re-review Plan agent 20/04 apres-midi)

11 reserves editoriales corrigees (voir Section 14 pour traçabilite complete) :
- LOC Section 3/4 reconcilies (3390 total, sum verifiee)
- Section 5.2 dedoublonnee (heartbeat = 5.2, ACSIL = 5.3, feedback = 5.4)
- Section 4.7 v1.2 (devenue 4.11 Interfaces en v1.3) : consolidee 9 interfaces (fusion IClock/ITimeProvider, IMarketData/IMarketDataProvider)
- Section 4.9 v1.2 (devenue 4.13 en v1.3) : 78 tests breakdown (vs "54+" v1.1 stale; recalibre a 79 en v1.3 via M5)
- Schema JSONL : 23 champs verifies (non 24)
- Section 4.6 : "20 LOC critiques" (verifie, pas "60 LOC" invente)
- Section 7 : +4 questions fondamentales (backpressure, schema evolution, flatten+kill, cross-instrument)
- Section 9 timeline 7-8 sem coherent avec intro
- Section 14 nouvelle : 6 recommandations v1.0 tracees + 11 corrections v1.2
- Test statique 8.4 #4 renforce : V2_Main peut LIRE scores (pour SnapshotWriter) mais pas BRANCHER
- Cross-instrument state : mutex kernel + fichier atomic **co-existent** (clarifie 11.2 + 7.9)

## Changelog v1.1 (post review Plan agent 20/04 matin)

Corrections post review Plan agent adversarial :
1. +4 modules bloquants : V2_Config, V2_StatePersistence, V2_HealthCheck, V2_EventJournal
2. LOC corriges : ~3390 total (sum Section 3 re-verifie, v1.0 ~1740 = 51% du reel soit sous-estime de ~49% vs realite)
3. `V2_RiskManager.allow_trade()` recoit `RiskSignal` subset (pas `Signal` complet) —
   empeche structurellement pattern 11
4. Heartbeat V2CLEAN ajoute (`V2CLEAN_HEARTBEAT/hb.json`)
5. Schema JSONL : ajout `signal_kind` (entry/exit_manual/flatten_all)
6. Dedup cross-restart persiste (`V2_BIS_STATE/signal_dedup.json`)
7. Tests statiques CI pattern 11 + 4 criteres testables "logique trading"
+ Ajout 8 risques section 11 (crash DLL, CPU overload, race ES/NQ, SC auto-update,
  clock drift, reset SC, fichier > 1GB, coupure AMP)

---

## 1. Contexte et objectifs

### 1.1 Pourquoi V2-bis ?

V2CLEAN Python (externe DTC) fonctionne mais a 2 limites structurelles :
- **Latence** : DTC bracket complet 1.2-3.2s (mesure 02/04/2026)
- **Robustesse** : process externe peut etre tue/disconnecte sans detection immediate

V2-bis C++ ACSIL attache directement au chart Sierra Chart :
- **Latence <1ms** (in-process SC)
- **Fiabilite** : si SC tourne, V2-bis tourne
- **Snapshot ML V3-ready** : 40+ champs versionnes par trade pour feedback loop

### 1.2 Pourquoi maintenant ? (pas avant)

V1 C++ (`MIA_AutoTrader_BN_v1.cpp`, 8925 LOC) est mort le 09/04/2026. Raisons :
- Data cassee (bar_color 100% sature, delta_divergence idem)
- MenthorQ geometrique sans contexte
- 9 gates cascade L1-L4 (95-98% rejet)
- 0 try/catch, 244 sprintf sans bornes
- **Risk management absent**

**Aujourd'hui (20/04/2026)** :
- Data propre depuis 17/04 (fix DMP 3.7.7)
- Validator V2 bulletproof (35 tests, detection 5 types pollution)
- Pipeline ML Lopez-compliant (PSR/DSR validation)
- Kill-switch DD $300 implemente (V2CLEAN)

V2-bis peut enfin etre **simple et correct** car les fondations le sont.

### 1.3 Objectifs V2-bis

| Objectif | Mesure de succes |
|---|---|
| Execution native SC ACSIL | Latence decision→OCO <1ms |
| Zero logique trading (pure bras) | Aucun `if ml_score > X AND my_filter then skip` |
| Parite bit-for-bit avec V2CLEAN | 0 MISMATCH sur 1000 bars audit |
| Snapshot ML V3-ready | 40+ champs versionnes par trade |
| Robustesse kill-switch | DD intraday $300 declenche en <1s |
| Sessions disciplinees | London 08:00-09:15 + pause OPR + US 10:00-16:00 ET |

### 1.4 Non-objectifs

- **V2-bis NE fait PAS de ML** (LightGBM dans V2CLEAN Python)
- **V2-bis NE calcule PAS de features** (lit features DMP pour snapshot)
- **V2-bis NE remplace PAS V2CLEAN** (coexistence validee 19/04)
- **V2-bis NE trade PAS plusieurs strategies** (1 signal ML = 1 action)

---

## 2. Principe directeur

```
┌─────────────────────┐        ┌──────────────────────┐        ┌────────────────────┐
│   DMP C++ (VPS)     │  ───►  │   V2CLEAN Python     │  ───►  │   V2-bis C++       │
│                     │ JSONL  │                      │ JSONL  │   ACSIL            │
│  - 266 features     │        │  - ML LightGBM       │ signal │  - File watch      │
│  - Schema 3.7.7     │        │  - Meta-labeling     │        │  - OCO native      │
│  - Data collecte    │        │  - PSR/DSR validate  │        │  - Risk manager    │
│                     │        │  - Score p_primary   │        │  - Snapshot log    │
└─────────────────────┘        │  - Score p_meta      │        │  - Kill-switch     │
                               │  - score_combined    │        └────────────────────┘
                               └──────────────────────┘                  │
                                                                         ▼
                                                              ┌─────────────────────┐
                                                              │  Sierra Chart       │
                                                              │  → AMP broker       │
                                                              │  (Teton CME)        │
                                                              └─────────────────────┘
```

**V2CLEAN Python = CERVEAU** (decide si achat/vente, calibre seuils, valide edge)
**V2-bis C++ = BRAS** (execute OCO, gere risk, snapshot, coupe si DD)

---

## 3. Architecture cible (~3390 LOC total — 13 modules)

Correction v1.1 : v1.0 sous-estimait ~49% les LOC (v1.0 ~1740 / reel 3390). Aligner estimation avec la realite du port
Python → C++ et du overhead Sierra Chart compile/reload. La sum des modules ci-dessous fait
3390 LOC, verifie manuellement par re-review Plan agent.

```
V2_BIS/
├── V2_Main.cpp              (~200 LOC) dispatcher ACSIL + chain of gates
├── V2_JSONLBridge.h         (~280 LOC) file watch + dedup persist + heartbeat V2CLEAN check
├── V2_OrderExec.h           (~450 LOC) OCO + Trailing + BE + Smart entry + orphelin retry
├── V2_RiskManager.h         (~450 LOC) port V2CLEAN/risk_manager.py (716 LOC Python)
├── V2_SnapshotWriter.h      (~280 LOC) JSONL append ML V3-ready + MFE/MAE + rotation
├── V2_SessionGuard.h        (~120 LOC) London 08:00 ET + pause OPR + US 16:00 ET (PURE time-based)
├── V2_Interfaces.h          (~280 LOC) DI : 9 interfaces (IStudyReader, IMarketDataProvider,
│                                      IOrderExecutor, ILogger, ITimeProvider, ISignalSource,
│                                      IPersistence, IEventJournal, IConfigProvider)
├── V2_Config.h              (~100 LOC) [NEW v1.1] centralisation config (paths, thresholds, sessions)
├── V2_StatePersistence.h    (~120 LOC) [NEW v1.1] atomic write + corruption recovery + backup
├── V2_HealthCheck.h         (~80 LOC)  [NEW v1.1] heartbeat liveness + staleness V2CLEAN + telemetry
├── V2_EventJournal.h        (~80 LOC)  [NEW v1.1] tracer structure : trade_open/close/reject, kill, reset
├── V2_MockImpl.h            (~350 LOC) mocks des 9 interfaces + scenario helpers
└── V2_Tests.cpp             (~600 LOC) Catch2 : 79 tests unit + integration + statiques pattern 11
```

**Total verifie** : ~3390 LOC (vs V1 C++ 8925 LOC monolithique = -62%)
**Vs V1 refactored** (17284 LOC en 22 fichiers) : reutilise DNA testable (MIA_Interfaces.h 291 LOC source adaptee a V2_Interfaces 280 LOC + scaffolding MockImpl V1 source pour V2_MockImpl 350 LOC)

### 3.1 Pourquoi 4 modules additionnels ?

| Module | Raison | Anti-pattern evite |
|---|---|---|
| V2_Config | Config centralisee | V1 : 32 fichiers config concurrents → derive |
| V2_StatePersistence | Atomic I/O | Python `_write_snapshot_atomic` = 20 LOC critiques (mkstemp+replace+fsync). V2-bis en naif = race conditions |
| V2_HealthCheck | Liveness + heartbeat V2CLEAN | V1 : process mort non detecte. Meme erreur si on oublie |
| V2_EventJournal | Tracer rejets | SnapshotWriter ne couvre que trades executes. Rejets invisibles = debug impossible |

---

## 4. Modules detailles

### 4.1 V2_Main.cpp (~200 LOC)

**Responsabilite** : dispatcher ACSIL Sierra Chart. Boucle par barre via `scsf_V2_Bis`.

**Inputs** :
- `SCStudyInterfaceRef sc` (Sierra Chart state, barres, volumes)
- Config via V2_Config.instance() : instrument (ES/NQ), symbole contrat, paths

**Outputs** :
- Appels `V2_JSONLBridge.poll()` → signal
- Chain of gates (4.1.1) → decision
- Delegation `V2_OrderExec.execute(signal)` si toutes gates passent
- Delegation `V2_RiskManager.on_bar()` chaque barre
- Delegation `V2_HealthCheck.tick()` chaque barre

**Dependencies** : V2_JSONLBridge, V2_OrderExec, V2_RiskManager, V2_SessionGuard, V2_SnapshotWriter,
V2_HealthCheck, V2_EventJournal, V2_Config

**Tests** : 5 scenarios dispatcher (bar open/close, signal present/absent, kill-switch triggered).

#### 4.1.1 Chain of gates (ordre strict documente v1.3)

V2_Main applique les verifications dans cet ordre **non-negociable** avant execution :

```cpp
void on_bar_close() {
  // 1. HealthCheck V2CLEAN (le plus tot possible)
  health.tick(state);
  if (!health.is_v2clean_alive() && v2clean_down > 120s) {
    // V2CLEAN down : pas de nouveau signal, mais gerer positions ouvertes
    order_exec.manage_open_positions();  // SL/TP/trailing
    return;
  }

  // 2. Lecture signal (dedup + staleness)
  auto signal = bridge.poll();
  if (!signal) return;

  // 3. Session (time-based pure, PAS de market data)
  if (!session_guard.is_trading_window(now_et)) {
    journal.log(EventType::SIGNAL_REJECTED, {"reason": "out_of_session"});
    return;
  }

  // 4. Risk (RiskSignal subset, pas de score_* visible)
  RiskSignal rs = strip_to_risk_signal(signal);
  if (!risk.allow_trade(rs)) {
    journal.log(EventType::SIGNAL_REJECTED, {"reason": risk.reason()});
    return;
  }

  // 5. Execute (V2_OrderExec route selon signal.signal_kind)
  order_exec.execute(signal, risk.state());
}
```

**Pourquoi cet ordre** :
- HealthCheck EN PREMIER : evite de traiter signal si V2CLEAN muet
- Session AVANT Risk : rejet fast-path (0 LOC risk state touche) si hors heures
- Risk APRES Session : evite de consumer budget risk si on n'aurait pas trade anyway
- Execute DERNIER : seule action irreversible (ordre envoye broker)

---

### 4.2 V2_JSONLBridge.h (~280 LOC)

**Responsabilite** : file watch `ml_signal.jsonl` produit par V2CLEAN Python. Parse derniere ligne. Deduplique par `signal_id` avec persistance cross-restart. Verifie heartbeat V2CLEAN.

**Schema JSONL** : voir Section 5.1 (23 champs v1.1, ne pas dupliquer ici).

**Contrat** :
- Polling : toutes les 100ms
- Deduplication cross-restart : ring buffer **300** `signal_id` persiste via `V2_StatePersistence`
  (voir Section 5.2 pour protocole complet + justification dimensionnement)
- Staleness guard : si `ts > signal.entry_window_sec` du current SC time → reject, log EventJournal
- Hash features : audit-trail log-only (decision v1.1 dans section 6, cf decision 14 tableau)
- Heartbeat V2CLEAN check : delegue a `V2_HealthCheck`, bloque signaux si > 120s (Section 5.2)

**Dependencies** : `std::filesystem`, parser JSON minimal, V2_StatePersistence, V2_HealthCheck, V2_EventJournal

**Tests** : 8 scenarios (fichier absent, ligne malformee, staleness, dedup cross-restart, parsing OK, hash log, multiple signals, file rotation)

---

### 4.3 V2_OrderExec.h (~450 LOC)

**Responsabilite** : execute signal via ACSIL natif Sierra Chart. OCO, trailing stop, break-even. Reutilise DNA V1 OCO validee 02/04/2026.

**API** :
```cpp
class V2OrderExec {
public:
  ExecutionResult execute(const Signal& s, const RiskState& risk);
  void on_fill(int order_id, double fill_price);
  void on_sl_tp_hit(int order_id, PositionSide side);
  void update_trailing(double current_price);
};
```

**Logique OCO** (inspiree V1 C++ DNA) :
- Parent ordre `sc.BuyEntry` ou `sc.SellEntry` avec `AllocateOrderType = SCT_ORDERTYPE_MARKET`
- Attach child SL : `sc.SellStop` (SL distance from entry)
- Attach child TP : `sc.SellLimit` (TP distance from entry)
- Sierra ACSIL gere OCO natif (PAS le bug DTC OCO silencieux)
- Cancel oppose automatique quand SL OU TP hit

**Smart entry** (V1-inspired) :
- Si `dist_entry_bid > 3 ticks` → LIMIT
- Sinon → MARKET

**Trailing stop** :
- Activation seuil : `profit > 0.5 * sl_ticks`
- Trail distance : `atr * 0.05` (ticks)

**Break-Even** :
- Declenchement : `profit > 0.3 * tp_ticks`
- Nouveau SL : entry_price

**Dependencies** : Sierra Chart SCStudyInterface

**Tests** : 15 scenarios Catch2 (bracket complet, fill parent, fill TP, fill SL, cancel oppose, trailing update, BE hit, orphelin detection, etc.)

---

### 4.4 V2_RiskManager.h (~450 LOC)

**Responsabilite** : port direct `V2CLEAN/risk/risk_manager.py` (716 LOC Python, 4 tests valides 19/04).

**Kill-switch hierarchie** :
1. CATASTROPHE : P&L journee < -$850 → flatten all, stop trading jour
2. DAILY_LOSS : P&L journee < -$500 → stop trading jour
3. INTRADAY_DD : peak-to-trough < -$300 → stop trading jour
4. MAX_TRADES : > 5 trades/jour → stop trading jour

**API (avec RiskSignal subset — garde-fou pattern 11 v1.1)** :

```cpp
// Subset Signal qui strippe tous les champs ML.
// V2_RiskManager.allow_trade() NE PEUT PAS cheater car le code n'a
// PAS acces a score_combined, p_primary, p_meta, features_hash.
struct RiskSignal {
  SymbolId sym;               // ES | NQ
  Direction direction;        // BUY | SELL
  int sl_ticks;
  int tp_ticks;
  int size_contracts;         // deja clippe par risk_budget cote V2CLEAN
  double risk_budget_usd;     // budget maximum alloue par V2CLEAN
  int64_t signal_ts_ms;       // pour cooldown
  // PAS DE : score_combined, p_primary, p_meta, features_hash, atr_ticks
};

class V2RiskManager {
public:
  // V2_Main fait le strip Signal -> RiskSignal avant appel
  bool allow_trade(const RiskSignal& r);
  void on_trade_close(double pnl_usd);
  void on_bar(double mtm_pnl_usd);
  bool is_killed() const;
  KillReason reason() const;
  void reset_session();
};
```

**Garde-fou** : compilation echoue si quelqu'un tente d'ajouter `score_*` a `RiskSignal`
(test statique CI : `grep "score_combined\|p_primary\|p_meta" V2_RiskManager.h` doit retourner vide).

**Persistance** : via `V2_StatePersistence` (atomic write) vers `V2_BIS_STATE/risk_state.json`.

**Dependencies** : Python risk_manager.py comme reference, port C++ strict 1-to-1. V2_StatePersistence,
V2_EventJournal. Split interne en `V2_KillSwitch` reporte a P1 (R8 section 14).

**Tests** : 12 scenarios (4 declencheurs + persistence + reset + edge cases + strip RiskSignal).

---

### 4.5 V2_Config.h (~100 LOC) [NEW v1.1]

**Responsabilite** : centralisation configuration. Un point unique de verite.

**Sections config** :
- `paths` : chemins fichiers (JSONL signal, state, snapshots, heartbeat)
- `risk` : thresholds kill-switch (800/500/300/5), cooldowns, max_hold_bars
- `sessions` : fenetres London/US/pause OPR (HH:MM ET)
- `execution` : smart entry (3t LIMIT/MARKET), trailing thresholds, BE thresholds
- `health` : intervalles heartbeat (1s), staleness threshold V2CLEAN (30s)

**API** :
```cpp
class V2Config {
public:
  static const V2Config& instance();
  // Getters typed : pas de stringly-typed config
  PathConfig paths() const;
  RiskConfig risk() const;
  SessionConfig sessions() const;
  ExecutionConfig execution() const;
  HealthConfig health() const;
  // Reload at hot (via ACSIL reload DLL)
  void reload_from_disk();
};
```

**Format stockage** : `V2_BIS_CONFIG/config.json` (versionne, validable JSON schema)

**Fallback** : si config.json absent → hardcoded defaults (evite crash demarrage).

**Tests** : 6 scenarios (load OK, missing file, malformed, partial, reload, version mismatch).

---

### 4.6 V2_StatePersistence.h (~120 LOC) [NEW v1.1]

**Responsabilite** : atomic file I/O pour tous les etats persistents (risk_state.json,
signal_dedup.json, heartbeat.json).

**Port Python V2CLEAN** (20 LOC critiques `_write_snapshot_atomic` lignes 545-564 risk_manager.py + ~40 LOC restore + backup logique) :
- tempfile.mkstemp dans meme filesystem que target
- write + fsync
- os.replace (atomic rename)
- gestion Windows (MoveFileEx + MOVEFILE_REPLACE_EXISTING)

**API** :
```cpp
class V2StatePersistence : public IPersistence {
public:
  // Atomic : tempfile + write + fsync + rename
  Result write_json(const std::filesystem::path& target, const nlohmann::json& data);

  // Lecture avec validation : si parse JSON echoue, charge backup .bak
  Result<nlohmann::json> read_json(const std::filesystem::path& target);

  // Backup explicite avant modification schema_version
  Result backup_before_migration(const std::filesystem::path& target);
};
```

**Garanties** :
- Jamais de fichier partiel apres crash
- Corruption = fallback backup (.bak)
- Schema version check avant parse

**Tests** : 8 scenarios (atomic OK, crash mid-write simule, corruption detect, backup restore,
Windows rename edge cases, concurrent write ES+NQ, disk full, permissions).

---

### 4.7 V2_HealthCheck.h (~80 LOC) [NEW v1.1]

**Responsabilite** : detection silence bilateral (V2-bis mort OU V2CLEAN mort).

**Liveness V2-bis** :
- Ecrit `V2_BIS_STATE/heartbeat.json` toutes les 1s : `{ts, bar_count, last_signal_id, is_killed}`
- Un monitoring externe Python (cron) peut detecter V2-bis mort

**Staleness V2CLEAN (crash + zombie detection v1.3)** :
- Lit `V2CLEAN_HEARTBEAT/hb.json` ecrit par V2CLEAN Python toutes les 1s
- **Crash** : si derniere ecriture `ts_ms` > 30s → alerte; > 120s → block signaux
- **Zombie** : si `last_signal_emitted_ts_ms` > 15 min en RTH → warning; > 30 min → block
- Cf Section 5.3 pour logique complete

**Telemetry** :
- Memory used, CPU tick time dans heartbeat (diagnostic overload)

**API** :
```cpp
class V2HealthCheck {
public:
  void tick(const V2State& state);  // appele par V2_Main a chaque bar close
  bool is_v2clean_alive() const;
  int seconds_since_v2clean_hb() const;
  HealthReport status() const;
};
```

**Dependencies** : V2_StatePersistence, V2_EventJournal, V2_Config (intervalles).

**Tests** : 6 scenarios (heartbeat OK, V2CLEAN down 30s alert, > 120s block, file missing,
telemetry overflow, reboot recovery).

---

### 4.8 V2_EventJournal.h (~80 LOC) [NEW v1.1]

**Responsabilite** : tracer TOUS les evenements structures (pas juste trades executes).

**Types d'evenements** :
- `trade_open`, `trade_close`, `trade_reject` (raison enum)
- `kill_switch_trigger` (niveau + peak/trough)
- `session_transition` (London → Pause → US)
- `v2clean_stale_warning`, `v2clean_down`
- `signal_received`, `signal_deduped`, `signal_stale`
- `order_error` (ack timeout, broker reject)
- `daily_reset`
- `dll_reload`, `state_restored`

**Format** : JSONL append dans `V2_BIS_JOURNAL/events_YYYYMMDD.jsonl`

**API** :
```cpp
class V2EventJournal : public IEventJournal {
public:
  void log(EventType type, const nlohmann::json& payload);
  void flush();  // force fsync
};
```

**Rotation** : 1 fichier par jour UTC. Apres 30 jours, compression/archivage.

**Usage** : debug post-mortem "pourquoi ce trade refuse a 10:03:47" = grep dans events_YYYYMMDD.

**Tests** : 4 scenarios (append, rotation jour, flush, format valide).

---

### 4.9 V2_SnapshotWriter.h (~280 LOC)

**Responsabilite** : log JSONL append ML V3-ready pour feedback loop futur.

**Format** (40+ champs versionnes) :
```json
{
  "snapshot_version": "3.0",
  "trade_id": "uuid-...",
  "signal_id": "uuid-...",
  "instrument": "NQ",
  "contract": "NQM26-CME",
  "entry_ts": 1776636060000,
  "entry_price": 26569.50,
  "exit_ts": 1776636360000,
  "exit_price": 26589.00,
  "direction": "SELL",
  "size_contracts": 1,
  "pnl_ticks": 78,
  "pnl_usd": 39.00,
  "outcome": "TP" | "SL" | "TRAIL" | "BE" | "MANUAL" | "KILL",
  "duration_sec": 300,
  "slippage_ticks_entry": 0.5,
  "slippage_ticks_exit": 0.2,
  "score_combined": 0.68,
  "p_primary": 0.72,
  "p_meta": 0.85,
  "atr_ticks_at_entry": 445.68,
  "features_hash_entry": "a3f2b1c0",
  "model_version": "NQ_SELL_v4_20260615",
  "validator_version": "2.0",
  "v2bis_version": "0.1.0",
  "sc_session_id": "London" | "US",
  "bars_held": 5,
  "max_favorable_excursion_ticks": 82,
  "max_adverse_excursion_ticks": -12,
  "was_trailing_active": true,
  "was_be_hit": false,
  "kill_switch_triggered": false,
  "... (10+ champs context regime)"
}
```

**Rejected snapshots** : si `allow_trade() == false`, loguer raison rejet (risk kill, session hors heure, stale signal, etc.)

**Dependencies** : fichier local ecriture append, rotation quotidienne

**Tests** : 6 scenarios (trade gagnant, perdant, trail hit, BE hit, rejet session, rejet risk)

---

### 4.10 V2_SessionGuard.h (~120 LOC)

**Responsabilite** : filtrer trades par session. Decision 19/04 : **London + US** pour V2-bis (vs V2CLEAN US only).

**Fenetres autorisees** :
- **London early** : 08:00-09:15 ET (MenthorQ niveaux publies 08:00)
- **Pause OPR** : 09:15-10:00 ET (ouverture US erratique, skip)
- **US RTH** : 10:00-16:00 ET

**Fenetres interdites** :
- Asia 18:00-03:00 ET (ranges thin, spreads x3)
- London pre-news 03:00-08:00 ET
- Apres 16:00 ET (flatten si position ouverte a 15:55 ET)

**API** :
```cpp
class V2SessionGuard {
public:
  bool is_trading_window(const SCDateTime& now_et);
  bool is_flatten_required(const SCDateTime& now_et);
  SessionPhase current_phase(const SCDateTime& now_et);
};
```

**Dependencies** : SCDateTime utility SC

**Tests** : 8 scenarios (transitions chaque frontiere heure + weekend + jour ferie)

---

### 4.11 V2_Interfaces.h (~280 LOC)

**Responsabilite** : DI pour testabilite. Reutilise DNA `MIA_Interfaces.h` V1 refactored (291 LOC).

**9 interfaces v1.1** (consolidation vs v1.0 qui avait 6 + ajouts Plan agent) :

| Interface | Role | Notes |
|---|---|---|
| `IStudyReader` | Lecture barres SC | DNA V1 |
| `IMarketDataProvider` | Prix/volume temps reel | **PAS injecte dans V2_SessionGuard** (garde-fou pattern 11) |
| `IOrderExecutor` | Passage ordres ACSIL | DNA V1 |
| `ILogger` | Log console + fichier | DNA V1 |
| `ITimeProvider` | Horloge (time-travel tests) | = IClock (consolidation v1.1) |
| `ISignalSource` | Lecture signal JSONL | V2-bis specifique |
| `IPersistence` | Atomic file I/O (mock) | [NEW v1.1] pour tester V2_StatePersistence |
| `IEventJournal` | Tracer evenements | [NEW v1.1] |
| `IConfigProvider` | Injection config en test | [NEW v1.1] |

**Renomages v1.1** : `IClock` (Plan agent suggestion) fusionne avec `ITimeProvider`, `IMarketData` fusionne avec `IMarketDataProvider` (pas de doublons).

**Pattern** : header-only, heritage simple, pas de dynamic_cast

---

### 4.12 V2_MockImpl.h (~350 LOC)

**Responsabilite** : implementations mock des 9 interfaces pour tests Catch2.

**9 Mocks (v1.1)** :
- `MockStudyReader` : retourne bars predefinies
- `MockMarketDataProvider` : injection prix/volume sequentiels
- `MockOrderExecutor` : enregistre ordres passes sans envoyer a SC
- `MockLogger` : capture logs en memoire
- `MockTimeProvider` : time-travel deterministe
- `MockSignalSource` : injection JSONL signals
- `MockPersistence` [NEW v1.1] : I/O en memoire, simulate crash/corruption
- `MockEventJournal` [NEW v1.1] : capture events pour assertions tests
- `MockConfigProvider` [NEW v1.1] : config par constructor param

**Pattern** : header-only, constructor pour injection params, assertion helpers

---

### 4.13 V2_Tests.cpp (~600 LOC)

**Responsabilite** : suite Catch2 E2E. Total **79 tests v1.3** (decompose par module ci-dessous).

**Breakdown v1.1** :
- V2_JSONLBridge : 8 tests (unit + dedup cross-restart)
- V2_OrderExec : 15 tests (unit + integration mock)
- V2_RiskManager : 12 tests (port 4 tests V2CLEAN + 8 edge cases + RiskSignal subset)
- V2_SnapshotWriter : 6 tests
- V2_SessionGuard : 9 tests (8 scenarios transitions + 1 test statique absence MarketDataProvider injection)
- V2_Main : 5 tests (dispatcher E2E + chain of gates)
- V2_Config [NEW] : 6 tests (load OK, missing, malformed, partial, reload, version mismatch)
- V2_StatePersistence [NEW] : 8 tests (atomic, crash mid-write, corruption, backup, concurrent ES+NQ, Windows rename edge, disk full, permissions)
- V2_HealthCheck [NEW] : 6 tests (hb OK, V2CLEAN down 30s, > 120s block, file missing, telemetry overflow, reboot recovery)
- V2_EventJournal [NEW] : 4 tests (append, rotation jour, flush, format valide)

**Tests statiques pattern 11** (Section 8.4, inclus ci-dessus dans V2_RiskManager et V2_SessionGuard counts) : 4 grep tests CI.

**Total v1.3** : 79 tests (8+15+12+6+9+5+6+8+6+4 = 79, correction M5 +1 test statique SessionGuard).

**Execution** : CI Windows (SC DLL compile) estimee 2-5 min. Statiques quasi-instantanes.

---

## 5. Contrats d'interface (critiques)

### 5.1 V2CLEAN Python → V2-bis C++ (ml_signal.jsonl)

**Chemin** : `C:/TRADING_SIERRA_CHART_AUTO/ML_SIGNAL/ml_signal.jsonl`

**Schema ligne v1.1 — 23 champs (17 initiaux + 6 ajouts v1.1)** :

```json
{
  "ts": 1776636060000,
  "sym": "NQ",
  "contract": "NQM26-CME",
  "bar_close_price": 26569.50,
  "atr_ticks": 445.68,

  "signal_kind": "entry",
  // [NEW v1.1] enum : "entry" | "exit_manual" | "flatten_all"
  // Sans ce champ, V2CLEAN ne peut pas commander un flatten global
  // (ex: news FOMC, anomaly detection, manual override)

  "score_combined": 0.68,
  "p_primary": 0.72,
  "p_meta": 0.85,
  "direction": "SELL",
  "sl_ticks": 20,
  "tp_ticks": 36,
  "size_contracts": 1,            // [NEW v1.1] sizing cote V2CLEAN (Kelly)
  "risk_budget_usd": 50.00,       // [NEW v1.1] budget max pour ce trade
  "max_hold_bars": 30,            // [NEW v1.1] flatten si pas sorti apres N bars
  "entry_window_sec": 90,         // [NEW v1.1] signal valide X sec (remplace hardcode)
  "regime": "trend_up",           // [NEW v1.1] pour snapshot/audit (pas decision V2-bis)
  "features_hash": "a3f2b1c0",
  "model_version": "NQ_SELL_v4_20260615",
  "validator_version": "2.0",
  "validator_baseline_version": "2026-W24",  // [NEW v1.1]
  "v2clean_version": "0.5.0",
  "signal_id": "uuid-550e8400-..."
}
```

**Garanties V2CLEAN Python** :
- 1 ligne max par bar 1min (pas de spam)
- `score_combined` deja filtre par seuil (V2-bis ne refiltre pas)
- `direction` defini ∈ {BUY, SELL} (SKIP = pas d'ecriture)
- `signal_id` **monotonic, persistent, non-reusable** (V2CLEAN persiste dedup cote Python)
- `signal_kind == "flatten_all"` : V2-bis flatte toutes positions symbole, ignore sl/tp
- `signal_kind == "exit_manual"` : V2-bis ferme position specifique (signal_id d'origine referenced)

**Garanties V2-bis C++** :
- Ne modifie jamais le fichier (read-only)
- Ne traite pas 2x le meme signal_id (dedup cross-restart via V2_BIS_STATE/signal_dedup.json)
- Si fichier absent : log warning EventJournal, attend
- Si ligne malformee : log erreur EventJournal, continue
- Si `ts` > `entry_window_sec` : log `signal_stale`, reject

### 5.2 Dedup cross-restart (v1.1, dimensionne v1.3)

**Probleme** : si V2-bis memorise les `signal_id` vus en RAM uniquement, un restart SC re-traite les anciens signaux.

**Protocol** :
- `V2_JSONLBridge` maintient un ring buffer des **300 derniers** `signal_id` traites
- Chaque update persiste via `V2_StatePersistence` dans `V2_BIS_STATE/signal_dedup.json` (atomic)
- Au demarrage V2-bis, restore le ring buffer depuis disque
- Avant traitement d'un signal : check `signal_id in ring_buffer` → skip si deja vu

**Dimensionnement 300 (corrige C4 v1.3)** :
- V2CLEAN garantit max 1 signal/bar 1min × 2 symboles = **2 signaux/min** pic
- Downtime SC restart worst case = 4h (reload charts + re-verification)
- 2 × 60 × 4 = 480 signaux possibles sur 4h
- Marge de securite 2x + buffer boot : **300 suffit avec ratio 0.625** (couvre 2.5h normal)
- Choix 300 vs 500 : compromis memoire (300 uuid × 37 bytes = 11 KB) vs latency restore (300 = <100ms)
- **v1.0 disait 100 = sous-dimensionne**, v1.2 justification disait 2h/120 signaux contradictoire

**Re-calibration possible P1** : si downtime > 4h observes, passer a 500.

### 5.3 V2CLEAN heartbeat (v1.1, zombie-detect v1.3)

**Chemin** : `C:/TRADING_SIERRA_CHART_AUTO/V2CLEAN_HEARTBEAT/hb.json`

**Ecrit par** : V2CLEAN Python toutes les 1s :
```json
{
  "ts_ms": 1776636123456,
  "process_status": "alive",
  "last_signal_emitted_ts_ms": 1776636060000,
  "version": "0.5.0"
}
```

**Lu par** : `V2_HealthCheck` toutes les **1s** (coherent avec frequence ecriture V2CLEAN).

**Logique V2-bis (v1.3 : crash detection + zombie detection)** :

**A. Crash detection (process mort)** :
- Si `(now - ts_ms) > 30s` → EventJournal `v2clean_stale_warning`
- Si `(now - ts_ms) > 120s` → V2-bis bloque le traitement signaux, log `v2clean_down`

**B. Zombie detection (process alive mais mute — correction C5 v1.3)** :
- Si `(now - last_signal_emitted_ts_ms) > 15 min` ET RTH active ET `bar_close_since_last > 5` bars
  → EventJournal `v2clean_zombie_warning`
- Si `(now - last_signal_emitted_ts_ms) > 30 min` en RTH
  → V2-bis bloque aussi signaux, log `v2clean_zombie_blocking`

**C. Positions ouvertes (dans les 2 cas)** :
- V2-bis continue de gerer SL/TP/trailing sur positions deja ouvertes meme si V2CLEAN down/zombie
- flatten_all manual disponible via V2_Config hot-reload (Jackson peut forcer flatten)

**Pourquoi critique** : V1 mort car "process mort non detecte". V2-bis doit detecter aussi **zombie**
(process alive, heartbeat OK, mais n'emet plus de signal — deadlock, queue bloquee, ML freeze).
`last_signal_emitted_ts_ms` etait champ mort v1.1/v1.2, **active en v1.3**.

### 5.4 V2-bis C++ → Sierra Chart (ACSIL)

**API utilisee** :
- `sc.BuyEntry` / `sc.SellEntry` : ordres parents
- `sc.AddOCOOrderSubmitExtendedResponse` : OCO attach child
- `sc.PositionData` : etat position temps reel
- `sc.GetPersistentInt` / `sc.SetPersistentInt` : state persistance SC (COMPLEMENTAIRE
  a V2_StatePersistence fichier, pas remplacement — cf Section 7.9 resolution)
- `sc.GetFlagFromChartPersistentVariableID` : config utilisateur

**Pas utilise** :
- DTC Protocol (V2CLEAN gere ca separement)
- Network sockets (V2-bis est in-process)
- File-based triggers externes

### 5.5 V2-bis C++ → Feedback loop ML (snapshot_trades.jsonl)

**Chemin** : `DATA/V2_BIS_SNAPSHOTS/snapshot_trades_YYYYMMDD.jsonl`

**Consommateur** : futur script Python `CORE/v2bis_feedback.py` (NON inclus P0, developpe quand V2-bis paper tourne depuis 2 semaines).

**Usage** : input pour V3 model retraining avec real fills + slippage reel.

---

## 6. Decisions techniques trancheees

| Decision | Choix | Justification |
|---|---|---|
| Langage | C++20 | ACSIL natif SC, performance |
| Build | SC Analysis Studio Build DLL | standard SC |
| ML inference | Python (V2CLEAN) | parite automatique, pas de treelite compile |
| Latence JSONL watch | 100-500ms tolerance | OK sur bars 1min |
| OCO | ACSIL natif (`sc.AddOCO*`) | Pas DTC OCOGroup1 (V1 reconnu broken) |
| Sessions | London + US (pause OPR) | Decision 19/04 confirmee |
| Sizing | 1 micro contrat (phase validation) | V2CLEAN identique |
| Trailing stop | Oui, active a 0.5*SL profit | V1 DNA validee |
| Break-even | Oui, a 0.3*TP profit | V1 DNA validee |
| Kill-switch | Hierarchie 4 niveaux | V2CLEAN port 1-to-1 |
| Tests | Catch2 (C++), **79 tests v1.3** unit + integration + statiques | Standard SC ACSIL |
| Deploy | Attached study sur chart NQ (puis ES) | In-process SC |
| Hot-reload | Analysis → Reload Custom Studies DLL | Pas restart SC |
| Config | **JSON principal (V2_Config) + SC persistent fallback** | Pas env vars |

---

## 7. Questions ouvertes (a trancher P0→P1)

### 7.1 Migration treelite

V2CLEAN Python tourne le ML. Potentiel futur : compiler LightGBM en C++ via treelite, integrer dans V2-bis.

**Arguments pour** : latence <10us, plus de dependance Python
**Arguments contre** : perdre parite automatique, complexe deploy
**Decision** : **reporter a Phase 5+** (apres V2-bis paper 100 trades clean GO)

### 7.2 Multi-instruments simultanes

Actuellement : 1 study attachee par chart = 1 instrument trade. 2 instances = 2 charts.

**Alternative** : 1 study multi-instruments via sc.ChartStudyData (complexe, pas V1-documentable)

**Decision** : **1 study par instrument**, simplifie + coherent V1 DNA (g_es_state vs g_nq_state)

### 7.3 DMP_Reader integration

V2-bis a-t-il besoin de lire les JSONL DMP directement ?

**Option A** : Non, lit juste ml_signal.jsonl de V2CLEAN (V2CLEAN lit DMP, calcule ML, ecrit signal)
**Option B** : Oui, lit DMP pour verifier parite features_hash cote V2-bis

**Decision** : **Option A seule au P1**. Option B audit parite peut etre ajoute en P4.

### 7.4 Gestion erreur SC

Si `sc.BuyEntry` retourne erreur, que faire ?

**Option A** : retry 1x apres 500ms
**Option B** : log + skip + alerte Discord
**Option C** : kill-switch automatique (stop trading jour)

**Recommandation** : **Option B + Option C si N erreurs consecutives > 3**. Details P1.

### 7.5 Format signal JSONL — RESOLU v1.1

`risk_budget_usd` + `regime` + `max_hold_bars` + `entry_window_sec` + `signal_kind` + `validator_baseline_version` sont **integres** dans schema 23 champs Section 5.1. `features_snapshot` reste a decider en P1 (taille vs debug utility).

### 7.6 Backpressure V2CLEAN → V2-bis [NEW v1.1]

Si V2CLEAN emet 10 signaux en 1s (burst), V2-bis poll toutes les 100ms. 10 signaux queued en memoire ?

**Option A** : FIFO queue interne, traiter dans l'ordre d'arrivee
**Option B** : drop anciens, garder seulement dernier signal par symbole
**Option C** : rejeter burst (V2CLEAN doit auto-limiter)

**Recommandation** : **Option B** (latest-wins par symbole). V2CLEAN genere 1 signal/bar normalement, burst = probable bug/restart V2CLEAN → prendre le plus recent est safe. A trancher P1.

### 7.7 Schema evolution JSONL [NEW v1.1]

V2CLEAN push nouveau champ (ex: `vol_regime_3state`). V2-bis v0.x ne le connait pas. Comportement ?

**Option A** : ignorer champ inconnu (forward-compatible)
**Option B** : rejeter signal (strict schema version check)
**Option C** : log warning + ignorer (defaut prudent)

**Recommandation** : **Option C**. `validator_baseline_version` et `v2clean_version` permettent tracking. V2-bis upgrade schema quand nouveau champ devient utile pour execution. A trancher P1.

### 7.8 flatten_all pendant kill-switch actif [NEW v1.1]

V2CLEAN envoie `signal_kind: flatten_all` pendant que V2-bis est deja kill-switched.

**Option A** : V2-bis ignore (kill-switch = silence absolu)
**Option B** : V2-bis execute flatten (flatten n'ouvre aucune nouvelle position, juste ferme)
**Option C** : V2-bis execute et reset kill-switch (acte de volonte V2CLEAN)

**Recommandation** : **Option B**. flatten_all = closing, pas opening. Kill-switch doit rester actif (pas de reset implicite). A trancher P1.

### 7.9 State sharing ES + NQ cross-instrument [NEW v1.1]

**Probleme** : `daily_pnl_usd` kill-switch est **shared** entre ES et NQ (compte unique AMP, DD $300 = tout). Qui tient l'etat ?

**Options et contradictions actuelles** :
- Section 4.6 : `V2_StatePersistence` atomic write fichier (cross-process safe)
- Section 11.2 : "named kernel mutex Windows" pour race ES vs NQ

**Resolution v1.2** : **Les deux sont necessaires ET complementaires** :
- Atomic file I/O pour **persistence** survivant restart SC
- Named kernel mutex pour **serialisation** des writes concurrents ES+NQ live
- Pattern : `mutex.lock()` → `V2_StatePersistence.write_json()` → `mutex.unlock()`

Section 11.2 clarifie que les deux mecanismes co-existent (appliquee v1.2).

### 7.10 flatten_all sans position ouverte [NEW v1.3]

Scenario : V2CLEAN emet `signal_kind: flatten_all` mais V2-bis n'a aucune position ouverte.

**Decision v1.3** : **no-op + log warning**.
- V2_OrderExec.flatten_all() detecte 0 position → return early
- V2_EventJournal.log("flatten_all_noop", {symbol, signal_id})
- Pas d'erreur (V2CLEAN peut emettre flatten prophylactique)

### 7.11 Meme ts + signal_id differents (double-write V2CLEAN) [NEW v1.3]

Scenario : bug V2CLEAN double-write emet 2 signaux meme `ts` mais `signal_id` differents.

**Decision v1.3** : **prendre le dernier, log anomalie**.
- V2_JSONLBridge detecte 2 signaux meme `ts` dans buffer lecture
- Garde seulement le dernier (max signal_id lexicographique, ou max scrape_time)
- V2_EventJournal.log("v2clean_double_write_anomaly", {ts, signal_ids: [...]})
- Aide diagnostic V2CLEAN cote Python

### 7.12 Rollover contrat pendant signal actif [NEW v1.3]

Scenario : V2CLEAN emet signal `contract: "NQM26-CME"` apres 3e vendredi trimestre (rollover NQM26 → NQU26).

**Decision v1.3** : **reject signal, log + alert**.
- V2-bis lit contrat courant via SC (`sc.Symbol`)
- Si `signal.contract != sc.Symbol` → reject signal_kind=entry (pas safe d'executer)
- V2_EventJournal.log("contract_mismatch", {signal.contract, sc_contract})
- Discord alert pour Jackson investigation
- V2CLEAN cote Python doit etre upgrade pour lire contract courant depuis DMP header

**Action P1** : ajouter champ `contract_version` au schema JSONL + logique rollover V2CLEAN.

### 7.13 exit_manual pendant kill-switch actif [NEW v1.3]

Scenario : position ouverte existe, V2CLEAN envoie `signal_kind: exit_manual` durant kill-switch.

**Decision v1.3** : **executer l'exit (closing, pas opening)**, coherent avec 7.8 flatten_all.
- Kill-switch bloque `signal_kind: entry` (nouvelle position)
- Kill-switch n'empeche PAS `signal_kind: exit_manual` (fermeture position)
- V2_OrderExec.close_position(signal.parent_signal_id, ...)
- V2_EventJournal.log("manual_exit_during_kill", {parent_signal_id})

**A trancher P1** : `parent_signal_id` field non present dans schema v1.3 (cf 7.7 schema evolution). Doit etre ajoute quand exit_manual implemente en P2.

---

## 8. Pattern 11 garde-fous (v1.1 : executoires, pas declaratifs)

### 8.1 Regles fondamentales (5)

**Regle 1** : V2-bis NE contient **AUCUNE** condition `if ml_signal AND my_filter`. Le signal V2CLEAN est **final**.

**Regle 2** : V2-bis NE recalcule **AUCUNE** feature. `features_hash` = audit-trail log-only (pas verification).

**Regle 3** : Toute logique metier hors OCO/Risk/Session/Snapshot est **interdite**. Si tentation "juste une petite verification" → retour V2CLEAN Python.

**Regle 4** : V2_SessionGuard est **pure time-based** (heures fixes). Pas de `MarketDataProvider` injecte. Jamais d'acces VIX/volume/spread/regime.

**Regle 5** : Code-reviewer obligatoire a chaque PR avec **criteres testables** (voir 8.2 ci-dessous).

### 8.2 Definition testable "logique trading" (4 criteres)

Une PR ajoute de la logique trading si elle :

1. **Ajoute une condition qui refuse un trade basee sur features ML**
   - Reference a : `score_*`, `p_primary`, `p_meta`, `features_hash`
   - Dans : n'importe quel module V2-bis
2. **Ajoute une condition qui refuse un trade basee sur market data**
   - Reference a : VIX, ATR regime, spread, volume, orderflow, bias
   - Dans : V2_SessionGuard, V2_RiskManager, V2_JSONLBridge, V2_OrderExec
3. **Ajoute un calcul qui produit un score de confiance interne**
   - Tout calcul qui combine > 1 input pour produire une sortie influencant `allow_trade()`
4. **Modifie `direction`, `sl_ticks`, `tp_ticks` apres reception du signal**
   - Sauf trailing stop (trailing = movement adaptation, pas decision trade)

Agent code-reviewer utilise ces 4 criteres comme checklist binaire.

### 8.3 Garde-fous structurels (compile-time)

**Le code ne peut pas faire ce qu'il n'a pas dans sa signature** :

1. **`V2_RiskManager.allow_trade(const RiskSignal&)`** — pas de `score_*` accessible.
   RiskSignal est un subset qui strippe tous les champs ML (voir section 4.4).

2. **`V2_SessionGuard.is_trading_window(SCDateTime)`** — pas d'argument market data.
   Tests verifient : `MockMarketDataProvider` n'est **pas** injecte dans V2_SessionGuard.

3. **`V2_JSONLBridge.poll() → Signal`** — retourne Signal opaque, V2-bis ne peut pas le modifier (const).

### 8.4 Tests statiques CI (pattern 11 grep automatique)

Dans `V2_Tests.cpp`, ajouter une suite de tests de **grep statique** sur le code source :

```cpp
TEST_CASE("Static: V2_RiskManager has no reference to ML scores") {
  auto src = read_file("V2_RiskManager.h");
  REQUIRE(not contains(src, "score_combined"));
  REQUIRE(not contains(src, "p_primary"));
  REQUIRE(not contains(src, "p_meta"));
  REQUIRE(not contains(src, "features_hash"));
}

TEST_CASE("Static: V2_SessionGuard has no MarketDataProvider") {
  auto src = read_file("V2_SessionGuard.h");
  REQUIRE(not contains(src, "IMarketDataProvider"));
  REQUIRE(not contains(src, "vix_level"));
  REQUIRE(not contains(src, "atr_ticks"));
}

TEST_CASE("Static: V2_OrderExec does not modify signal direction/SL/TP") {
  auto src = read_file("V2_OrderExec.h");
  REQUIRE(not contains(src, "signal.direction ="));
  REQUIRE(not contains(src, "signal.sl_ticks ="));
  REQUIRE(not contains(src, "signal.tp_ticks ="));
}

TEST_CASE("Static: no score branching outside explicit log-only zones") {
  auto src = read_dir_all_files("V2_BIS/");
  // V2_SnapshotWriter et V2_Main peuvent LIRE scores pour logging/passage,
  // mais aucun BRANCHING (if / while / switch) conditionnel autorise.
  std::set<std::string> log_only_files = {"V2_SnapshotWriter.h", "V2_Main.cpp"};
  for (auto [file, content] : src) {
    if (log_only_files.count(file)) {
      // Meme rigueur pour V2_Main ET V2_SnapshotWriter (correction M7 v1.3)
      REQUIRE(not contains_pattern(content, R"(if\s*\(\s*\w*\.score_combined)"));
      REQUIRE(not contains_pattern(content, R"(if\s*\(\s*\w*\.p_primary)"));
      REQUIRE(not contains_pattern(content, R"(if\s*\(\s*\w*\.p_meta)"));
      REQUIRE(not contains_pattern(content, R"(score_combined\s*[<>=])"));
      REQUIRE(not contains_pattern(content, R"(p_primary\s*[<>=])"));
      REQUIRE(not contains_pattern(content, R"(p_meta\s*[<>=])"));
      REQUIRE(not contains_pattern(content, R"(while\s*\(\s*\w*\.score)"));
      continue;
    }
    // Tous autres fichiers : aucune mention de score_*
    REQUIRE(not contains(content, "score_combined"));
    REQUIRE(not contains(content, "p_primary"));
    REQUIRE(not contains(content, "p_meta"));
  }
}

// Helpers (a implementer dans V2_Tests.cpp, ~30-50 LOC additionnels)
// - read_file(path) -> string
// - read_dir_all_files(dir) -> map<filename, content>
// - contains(str, substr) -> bool
// - contains_pattern(str, regex) -> bool (std::regex)
```

**Execution CI** : chaque PR qui fait echouer ces tests est bloquee **automatiquement**. Pas de merge possible.

### 8.5 Echec "lent et silencieux" (risque v1.1)

Insight review Plan agent : V1 = mort brutale (9 gates). V2-bis = **mort lente possible** si on laisse glisser :
- Config ad-hoc dans chaque module (→ V2_Config.h obligatoire)
- Pattern 11 qui glisse doucement via V2_SessionGuard "ameliorations"
- Debug impossible sans EventJournal (→ V2_EventJournal obligatoire)

Les 7 modifications bloquantes v1.1 existent **pour empecher ce mode d'echec**.

---

## 9. Plan execution P0→P5

| Phase | Duree | Livrable | Gate de passage |
|---|---|---|---|
| **P0** Design | 1 jour (fait) | Design doc v1.4 + 4 reviews Plan agent + audit final | V2CLEAN **shadow mode stable 7j** (decouple du paper GO) |
| **P1** Infrastructure | 1.5 sem | V2_Interfaces + V2_MockImpl + V2_Config + V2_StatePersistence + Catch2 setup | **~14 tests unit GREEN** (6 Config + 8 StatePersistence). Interfaces et MockImpl sont scaffolding (pas de tests propres, testes indirectement via modules P2). Les 79 tests totaux accumules sur P1+P2+P3 |
| **P2** Metier core | 3 sem | V2_Main + Bridge + OrderExec + Risk + Session + HealthCheck + EventJournal + SnapshotWriter | Tests E2E sur mocks GREEN (65 tests additionnels : 5 Main + 8 Bridge + 15 OrderExec + 12 Risk + 9 Session + 6 HealthCheck + 4 EventJournal + 6 SnapshotWriter, total 79 avec P1) + 4 grep CI statiques clean |
| **P3** Integration SC | 1 sem | Deploy VPS chart dedie, dry-run | Dry-run sur data 17/04+ 0 erreur |
| **P4** Paper Sim3 | 4-5 sem | Paper trading VPS Sim3 | **100 trades clean** (realiste : 3-5 trades/jour × 20-33 jours = 4-5 sem calendaires) + OCO 100% reliability |
| **P5** Live micro | ∞ | 1 contrat live AMP | V2CLEAN paper GO + V2-bis metriques prod OK |

**Total P1→P4 (avant live)** : **9.5-10.5 semaines** (sum exacte : 1.5 + 3 + 1 + 4-5 = 9.5-10.5).

**P4 etendu (v1.4)** : 2-3 sem v1.3 etait incoherent avec "100 trades clean" a max_trades=5/jour. Alignement a 4-5 sem rend le gate atteignable sans toucher aux regles risk.

### Gates separes (correction v1.1)

**Gate P0→P1** (debut juin cible) : V2CLEAN **shadow mode** stable 7j.
- Objectif : avoir des signaux testables pour developper V2-bis en parallele
- PAS "paper GO" (qui prendrait 10 jours de plus et retarderait inutilement V2-bis)

**Gate P4→P5** (juillet cible) : V2CLEAN **paper GO** + V2-bis **100 trades clean**.
- V2CLEAN paper GO = validation edge live (slippage reel)
- V2-bis 100 trades = detection bugs subtils (race ES/NQ, parity drift, OCO orphelin restart)

**Benefice separation** : V2-bis commence P1 fin mai au lieu d'attendre mi-juin. **3 semaines gagnees**.

---

## 10. Roadmap alignee V2CLEAN

| Sem | V2CLEAN Python (cerveau) | V2-bis C++ (bras) |
|---|---|---|
| S1 20-26/04 | Validator V2 + audit QA semaine | P0 design doc (ceci) + review Plan |
| S2 27/04-03/05 | Port 4 moteurs ctx live + parite | Rien (attente V2CLEAN) |
| S3 04-10/05 | Port 4 derniers moteurs live | Rien |
| S4 11-17/05 | Parity audit 2 instruments full | Rien |
| S5 18-24/05 | RiskManager intraday live verif | P1 pre-work (scaffolding Catch2, pas encore gate-crosse) |
| S6 25-31/05 | Shadow mode 7j V2CLEAN (**GATE P0→P1 debloque fin S6**) | **P1 infrastructure officielle demarre S6 apres gate** |
| S7 01-07/06 | Preparation paper | P1 fini + P2 debut |
| S8 08-14/06 | **Paper V2CLEAN 10j debut** | P2 metier core |
| S9 15-21/06 | Paper V2CLEAN 10j GO/NOGO | P2 fini + P3 integration |
| S10-S12 (juin fin-juillet) | V2CLEAN paper stable | P4 Paper Sim3 V2-bis (4-5 sem) |
| S13+ (aout) | GO paper V2-bis | **GATE P4→P5** : V2CLEAN paper GO + V2-bis 100 trades clean → live micro |

**Principe (correction v1.4)** :
- Gate P0→P1 est **formel** : debloque fin S6 (31/05) quand shadow stable 7j atteint
- Jackson peut faire **pre-work P1 en S5** (setup Catch2, scaffolding) mais NE code PAS RiskManager/OrderExec avant gate
- Si V2CLEAN paper NOGO mi-juin → V2-bis P3/P4 repoussent, mais P1+P2 continuent (mock-based, pas depend du paper)

---

## 11. Risques et mitigation (15 risques identifies)

### 11.1 Risques originaux (v1.0)

| Risque | Impact | Mitigation |
|---|---|---|
| V2CLEAN paper NOGO | V2-bis sans signal fiable | Attendre, ne pas forcer paper V2-bis |
| Pattern 11 V1 reborn | Maladie historique Jackson | Garde-fous section 8 (5 regles + 4 criteres testables + 4 tests statiques CI) |
| Latency JSONL watch > 500ms | Trade rate | Monitoring P4, failback polling 200ms |
| Crash C++ in-process SC | SC freeze | Static analyzer clang-tidy + AddressSanitizer + try/catch cible + watchdog |
| SC restart pendant trade | Position orphelin | V2_StatePersistence restore au demarrage + flatten-on-restart-if-orphan |
| OCO ACSIL comportement different DTC | Bug OCO silent | P3 tests exhaustifs OCO avant P4 |
| Deploy VPS dependency | Jackson compile manuel | Script deploy + instructions claires V1 |

### 11.2 Risques ajoutes v1.1 (review Plan agent)

| Risque | Impact | Mitigation |
|---|---|---|
| **Crash DLL SC pendant trade** | Position orphelin live | Watchdog process externe Python + flatten-on-crash via DTC backup route |
| **CPU overload VPS** (V2-bis + SC + V2CLEAN + DMP) | Latence >> 1ms, OCO rate hors fenetre | Profiling P3 + alerte V2_HealthCheck si CPU > 70% + P4 load test |
| **Race condition ES vs NQ** | Position double, OCO mixed | State partage via `V2_StatePersistence` (atomic file I/O) + named kernel mutex Windows sequencant writes + tests Catch2 concurrent. Les 2 mecanismes co-existent : mutex pour serialiser ES+NQ live, fichier pour survivre restart SC. Cf Section 7.9. |
| **SC auto-update casse ACSIL** | Bot mort du jour au lendemain | Lock SC version dans config, disable auto-update, release notes monitoring hebdo |
| **Coupure reseau AMP broker** | Ordre envoye non execute | Timeout ordre 5s + retry 3x + alerte EventJournal + kill-switch si > 3 echecs |
| **Reset SC intraday** (bug connu SC) | Etat persistent perdu | State dans FICHIER externe (V2_StatePersistence), PAS `sc.SetPersistentInt` seul |
| **Clock drift VPS vs V2CLEAN** | `ts` V2CLEAN != SC time | NTP sync force + V2_HealthCheck alerte si drift > 500ms |
| **Fichier ml_signal.jsonl > 1GB** | I/O ralenti, parsing timeout | Rotation quotidienne + read tail only (derniere ligne) |

### 11.3 Mitigations "incantatoires" bannies v1.0

Supprimees de v1.0 :
- ~~"Try/catch exhaustif + kill-switch fail-safe"~~ → remplace par static analyzer + ASan + watchdog
- ~~"Code-reviewer verifie pattern 11"~~ → remplace par 4 criteres testables + 4 tests statiques CI
- ~~"V2_RiskManager restore state au demarrage"~~ → precise via V2_StatePersistence atomic + backup

---

## 12. Checklist P0 completion (v1.4)

- [x] Architecture globale documentee (section 3) — 13 modules ~3390 LOC
- [x] 13 modules specifies LOC + responsabilite + interface (section 4, numerotation lineaire 4.1→4.13)
- [x] Chain of gates V2_Main documentee explicitement (section 4.1.1)
- [x] Contrats interface V2CLEAN↔V2-bis + V2-bis↔SC (section 5) — 23 champs JSONL + heartbeat + dedup 300
- [x] Decisions techniques trancheees (section 6)
- [x] Questions ouvertes listees (section 7) — 5 v1.0 + 4 v1.1 + scenarios v1.3
- [x] Pattern 11 garde-fous executoires (section 8) — 5 regles + 4 criteres testables + 4 tests statiques CI
- [x] Roadmap P0→P5 chiffree (section 9-10) — gates separes P0→P1 et P4→P5, 9.5-10.5 sem total (P4 etendu a 4-5 sem v1.4)
- [x] Risques identifies + mitigation (section 11) — 15 risques concrets
- [x] Review Plan agent v1.0 (20/04 matin, GO-AVEC-MODIFICATIONS)
- [x] 7 modifications bloquantes v1.1 appliquees
- [x] Re-review Plan agent v1.1 (20/04 apres-midi, GO-AVEC-RESERVES 11 items)
- [x] 11 reserves editoriales v1.2 appliquees
- [x] Re-re-review Plan agent v1.2 (20/04 soir, GO-AVEC-RESERVES 21 items)
- [x] 21 reserves v1.3 appliquees (6 critiques + 7 majeures + 8 mineures + 4 scenarios)
- [x] 4e review Plan agent v1.3 (20/04 soir-tard, GO-AVEC-RESERVES MINEURES 10 items)
- [x] 10 reserves editoriales v1.4 appliquees (ring buffer, tests 79, LOC 716, P4 4-5 sem, refs historiques, math, renum Section 5)
- [ ] Re-audit final Plan agent v1.4 (prochaine etape — viser GO SANS RESERVE)
- [ ] Review code-reviewer architecture (optionnel P0, obligatoire P1)
- [ ] Valide par Jackson

---

## 13. Prochaine etape (apres P0)

**Agent Plan** review ce doc et challenge :
- Architecture coherente ?
- Modules bien bornes ?
- Contrats interface complets ?
- Pattern 11 garde-fous suffisants ?
- Roadmap realiste ?
- Risques sous-estimes ?

**Agent code-reviewer** review aspect pratique :
- LOC estimes realistes ?
- Tests Catch2 nombre suffisant ?
- Mocks pattern approprie ?
- DNA V1 correctement reutilisee ?

**Jackson** valide global + priorites.

**Puis** : attente gate V2CLEAN paper NQ_SELL GO (mi-juin cible) → debut P1.

---

## 14. Recommandations v1.0 reportees (traçabilite)

Review Plan agent v1.0 avait 7 bloquantes (appliquees v1.1) + 6 recommandees. Etat actuel :

| # | Recommandation | Statut v1.1 |
|---|---|---|
| R8 | Splitter `V2_KillSwitch.h` (~120 LOC) de `V2_RiskManager.h` (~300 LOC) | **REPORTEE P1** — refactor interne pendant implementation RiskManager |
| R9 | +8 risques section 11 + mitigation concrete (pas "try/catch exhaustif") | **APPLIQUEE v1.1** (section 11.2) |
| R10 | Roadmap : P2 = 3 semaines, P4 = "100 trades clean" au lieu de "10 jours" | **APPLIQUEE v1.1** (section 9) |
| R11 | Reporter trailing/BE a V2-bis v0.2 (gain -150 LOC P1) | **REPORTEE** — a trancher fin P1 selon avancement |
| R12 | Formaliser criteres "logique trading" en 4 points testables | **APPLIQUEE v1.1** (section 8.2) |
| R13 | Separer gate P0→P1 (V2CLEAN shadow) de P4→P5 (V2CLEAN paper GO) | **APPLIQUEE v1.1** (section 9) |

**Recommandations re-review v1.1 → v1.2** (traçabilite du rapport Plan agent 20/04 apres-midi) :

| # | Recommandation v1.1→v1.2 | Statut v1.2 |
|---|---|---|
| V1.2-1 | Fix LOC headers 4.1-4.9 alignes avec Section 3 | **APPLIQUEE** |
| V1.2-2 | Fix Section 5.2 dupliquee → 5.3 + 5.4 | **APPLIQUEE** |
| V1.2-3 | Section 4.7 v1.2 (devenue 4.11 en v1.3) consolidee 9 interfaces | **APPLIQUEE** |
| V1.2-4 | Section 4.9 v1.2 (devenue 4.13 en v1.3) breakdown 78 tests (79 en v1.3) | **APPLIQUEE** |
| V1.2-5 | Fix compte JSONL 23 champs (pas 24) | **APPLIQUEE** |
| V1.2-6 | Fix "60 LOC lignes 545-564" → 20 LOC reels | **APPLIQUEE** |
| V1.2-7 | 4 questions fondamentales Section 7 (backpressure, schema evolution, flatten+kill, cross-instrument) | **APPLIQUEE** (7.6-7.9) |
| V1.2-8 | Timeline 7-8 sem + gates separes | **APPLIQUEE** (section 9) |
| V1.2-9 | Recommandations reportees tracees | **APPLIQUEE** (cette section) |
| V1.2-10 | Test statique 8.4 #4 renforce (V2_Main branching check) | **APPLIQUEE** (section 8.4) |
| V1.2-11 | Cross-instrument mutex + fichier co-existent | **APPLIQUEE** (section 11.2 + 7.9) |

---

## Memory liee

- `project_v2_bis_cpp_design_20260419.md` : design initial (ce doc etend)
- `project_dual_v1_heritage.md` : V1 Python + V1 C++ heritage
- `project_data_clean_since_20260417.md` : fondation data propre
- `feedback_lightgbm_no_composite_indicators.md` : pattern 11 garde-fou
- `feedback_agent_review_mandatory.md` : protocole review critique
- `V3_REGIME_SWITCHING_DESIGN.md` : V3 futur (regime-switching ensemble)
