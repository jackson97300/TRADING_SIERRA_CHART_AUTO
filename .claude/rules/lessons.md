# Lecons apprises (ne pas refaire ces erreurs)

## Claude Code / VS Code
- Hook `SessionStart` avec commandes reseau bloquantes (scp/ssh/curl) → MCP handshake timeout 30000ms → Claude Code injouable. Ne JAMAIS mettre de scp dans un hook SessionStart. Auto-sync VPS = `/sync` manuel ou tache planifiee Windows. Symptome : "failed to load servers (error: startup() initialize handshake timed out after 30000ms)". Fix : renommer le hook en `_SessionStart_DISABLED` dans `.claude/settings.json`. (12/04/2026, demi-journee perdue)
- Node.js 24 a un bug libuv (`Assertion failed: UV_HANDLE_CLOSING`) qui crashe Claude Code CLI. Garder Node 22 LTS.
- Shotgun debugging = perte de temps. Lire le message d'erreur d'abord (timeout 30000ms = chercher ce qui dure 30s), pas changer 8 trucs en parallele.

## DTC
- OrderStatus=2 n'est PAS Filled → le bot envoyait des brackets sur des ordres non-remplis
- Cancel sans ServerOrderID est IGNORE silencieusement par Sierra Chart
- Type 206, IsParentOrder, OCOGroup1 sont MORTS en mode SC serveur DTC
- pythonw.exe ou Task Scheduler pour process persistant — python.exe detache meurt

## Bot
- Position fantome : quand SL/TP fill via OCO, retirer la position du tracking
- JSONL : utiliser `max(st_mtime)` pas tri par nom (date session != date systeme)
- Gamma hardcode a 0.0 = gate MenthorQ jamais actif → lire depuis features mq_*
- DTC market data refuse par SC → fallback prix via derniere barre JSONL

## RuleEngine
- IF/ELSE ne capture pas la complexite du marche → attendre le ML
- VA basse en trend baissier != BUY (c'est un breakdown)
- BN color up=1 ET dn=1 = neutre, pas confirmation
- HVN a 10t au-dessus = MUR, ne pas acheter
- Momentum filter obligatoire : bloquer BUY si slope < -0.3 ET delta < -10K

## ML
- 3 jours de donnees = insuffisant pour des regles fiables
- 90-100% WR sur 15 trades = pas significatif statistiquement
- Rolling retraining hebdomadaire = technique #1 des fonds quant
- Overfitting sur backtest = risque #1

## DMP C++
- delta_divergence toujours 0 : DMP_ReadBN_Trigger(sg0) = pulse 1 barre, rate 99% des signaux
  Fix v3 : activer Extension Lines dans SC + lire via DMP_ReadExtensionLineCount (07/04/2026)
- Extension Lines = persistent jusqu'a intersection prix → ExtensionLineCount = bon compteur
- Trigger(sg0) = per-bar ephemere → bon uniquement pour signaux instantanes (volume spike)
- big_ask/bid_cluster_* : BUG RACINE different de delta_divergence. DMP_ReadBigOrderThreshold
  scannait sg0-46 de l'etude "Volume At Price Threshold Alert V2" mais les subgraphs ne
  contenaient PAS les prix des triggers. Tentative 1 (Extension Lines) a ECHOUE — cette
  famille d'etude n'utilise PAS AddLineUntilFutureIntersection.
  VRAIE CAUSE : les big orders sont des cellules VAP COLORIEES dans le footprint (rose)
  quand AskVolume/BidVolume depasse un seuil. Il faut les lire directement via
  sc.VolumeAtPriceForBars->GetVAPElementAtIndex, sans passer par l'etude.
  Fix 13/04/2026 (tentative 2 SUCCESS) : DMP_ReadBigOrdersFromVAP scanne les 60 dernieres
  barres VAP, filtre par `v->AskVolume >= threshold`, collecte les prix. Seuils hardcodes :
  ES=100/150/400/1000, NQ=10/30/100. Bug present depuis le debut du projet V2, 16 features
  mortes pendant 26 jours. Prerequis : `sc.MaintainVolumeAtPriceData = 1` dans SetDefaults
  (deja present ligne 114 de DMP_Main.cpp pour G11/G12).
- REGLE GENERALE : distinguer 2 familles d'etudes Sierra Chart selon le mecanisme de drawing :
  * Famille A "AddLineUntilFutureIntersection" (COLOR_UP/DN, LONG_UP/DN, EDGE_BUY/SELL,
    ABSORB_*, DOUBLE_*, TRIPLE_*) → lire via GetNumLinesUntilFutureIntersection +
    GetStudyLineUntilFutureIntersectionByIndex. Prerequis : option "Draw Extension Lines
    until End of Chart = Yes". Reference delta_divergence (07/04).
  * Famille B "Colorization cellules VAP" (Volume At Price Threshold Alert V2 toutes
    versions) → lire directement sc.VolumeAtPriceForBars, reproduire la logique de
    filtrage en C++. Pas de dependance a l'etude. Reference big_orders (13/04).
  Si une feature derivee d'une etude SC est constante a 0 malgre un visuel qui fonctionne,
  d'abord identifier la famille A ou B avant de choisir le fix.

## Pipeline
- Le bench necessite `DATA/ES DATA/NQ` en 2 arguments (pas 1 dossier DATA)
- Le scraper MenthorQ MidDay doit forcer --today (sinon prend la veille)
- CTA et Vol Models MenthorQ : API 403, endpoints non disponibles via AJAX
- MAPPING SYMBOLE PYTHON ↔ DOSSIER FILESYSTEM (10/05/2026, Chantier 5/7) :
  `MGC` (symbole Python) → `GC` (dossier filesystem). MenthorQ ne distingue
  pas Micro (MGC) vs Standard (GC) pour les niveaux options-driven, le
  scsf_MIA_MQ_Lite_GC dump dans `mq_levels/GC/...`. SOURCE UNIQUE :
  `CORE/constants.py:SYMBOL_TO_FS_DIR` + helper `get_fs_dir(symbol)`.
  Anti-pattern : mapper inline `if symbol == "MGC"` dans plusieurs fichiers =
  duplication garantie (cf TICK_SIZE duplique 5x V1).
- BACKFILL DATABENTO + LIVE INGESTION CONFLIT (10/05/2026) : si periode
  backfill chevauche activation live (ex: avril 2026 quand live MGC demarre
  09/05), le live ecrase les parquets backfill avec fichiers vides. Check :
  taille parquet (~20KB pour 1380 bars/1m). Si <1KB = corrompu, re-telecharger.

## Audits 09/04/2026 (34 fixes appliques)
- briefing.py : get_user_tier local = bypass auth → toujours importer depuis auth.py
- briefing archive : valider date_str avec regex avant os.path.join (path traversal)
- JWT secret : persister dans fichier .jwt_secret (pas os.urandom par instance)
- app.py : dashboard DOIT tourner en --workers 1 (etat global non-thread-safe)
- Frontend : reg peut etre null dans renderOverview → toujours `reg = reg || {}`
- Frontend : data.banner[sym].price sans guard → TypeError possible
- CVD_day_dir et delta_pct == 0 = NEUTRE, pas BEARISH
- Climax acheteur = exces bull = signal bearish (reversal), badge orange pas vert
- profile_shape : (1,2) directionnel, (0,3) range (pas 1,4 / 2,3)
- Bot : cycle de vie du trade casse sans journal.log_trade + risk.on_trade_close
- Bot : DTC reconnexion obligatoire — _recv_loop doit retry connect
- Bot : _last_heartbeat = time.time() au connect (sinon is_alive=False au start)
- Bot : attendre fill parent (threading.Event, status=7) avant TP/SL
- Bot : check fraicheur barre DMP < 90s avant chaque trade
- Bot : gamma fail-closed — rejeter si mq_gamma_condition absent
- Features collineaires ML : ask_pct == buy_sell_ratio, delta_pct == ask_bid_imbalance == delta_bar_vol_norm
- C++ : ib_complete doit checker is_rth_session (sinon true en Asia/London)
- C++ : total_fields=262 pas 168 dans DMP_Main.cpp (quality filter inactif)
- C++ : thread_local char s_json_buf (sinon race ES/NQ)
- C++ : DMP_WR_IsInvalid doit checker std::isfinite (NaN/Inf → "nan" dans JSONL)
- TICK_SIZE centralise dans CORE/constants.py (etait duplique 5x)
- ATR dans JSONL est en TICKS (verifie sur donnees live 09/04)
- Bot utilisait atr_14 qui n'existe pas → fallback 20 ticks permanent
