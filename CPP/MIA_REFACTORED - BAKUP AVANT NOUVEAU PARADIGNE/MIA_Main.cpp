// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// MIA_Main.cpp - SECTION 14: BOUCLE PRINCIPALE scsf_MIA_AutoTrader()
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// Fichier principal Ã  compiler - Inclut tous les modules
// Refactoring: 31/01/2026
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

#include "sierrachart.h"

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// INCLUDES MODULAIRES (ordre important!)
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#include "MIA_Config.h"
#include "MIA_Globals.h"
#include "MIA_StateManager.h"     // 🆕 31/01/2026: Thread-safe state access
// NOTE 28/02/2026: MIA_StudyConfig.h arrive via DataReader.h (ligne 10). JSON auto-chargé au 1er STUDY_ID(). Voir vérification SetDefaults.
#include "MIA_ExtensionTracker.h"
#include "MIA_SLTP.h"
#include "MIA_Utils.h"
#include "MIA_DataReader.h"
#include "MIA_Indicators.h"
#include "MIA_Layers.h"
#include "MIA_SLTP_Calc.h"
#include "MIA_Execution.h"
#include "MIA_Logging.h"
#include "MIA_DataDumper.h"       // ðŸ†• 31/01/2026: Data Dump pour backtesting

SCDLLName("MIA_AutoTrader_BN_v1_Refactored")

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// SECTION 14: BOUCLE PRINCIPALE
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

SCSFExport scsf_MIA_AutoTrader_BN(SCStudyInterfaceRef sc) {
    // === INPUTS ===
    SCInputRef Input_Enabled = sc.Input[0];
    SCInputRef Input_ES_Enabled = sc.Input[1];
    SCInputRef Input_NQ_Enabled = sc.Input[2];
    SCInputRef Input_ES_Paused = sc.Input[3];
    SCInputRef Input_NQ_Paused = sc.Input[4];
    SCInputRef Input_ES_Footprint_Chart = sc.Input[5];
    SCInputRef Input_ES_Barres_Chart = sc.Input[6];
    SCInputRef Input_NQ_Footprint_Chart = sc.Input[7];
    SCInputRef Input_NQ_Barres_Chart = sc.Input[8];
    SCInputRef Input_ES_Main_Chart = sc.Input[9];
    SCInputRef Input_NQ_Main_Chart = sc.Input[10];

    // ðŸ†• Charts VIX et Daily ATR
    SCInputRef Input_VIX_Chart = sc.Input[11];
    SCInputRef Input_ES_Daily_Chart = sc.Input[12];
    SCInputRef Input_NQ_Daily_Chart = sc.Input[13];

    // ðŸ†• MODE TEST/PRODUCTION
    SCInputRef Input_Bot_Mode = sc.Input[14];

    // ðŸ†• MODE RECTANGLES (Scalp sur rectangles verts/rouges)
    SCInputRef Input_Rectangle_Trading = sc.Input[15];

    // ðŸ†• 31/01/2026: DATA DUMP pour backtesting
    SCInputRef Input_Data_Dump = sc.Input[16];

    // ðŸ†• 31/01/2026: Charts Volume Profile + Delta Divergence
    SCInputRef Input_ES_VolumeProfile_Chart = sc.Input[17];
    SCInputRef Input_NQ_VolumeProfile_Chart = sc.Input[18];
    
    // ðŸ†• 31/01/2026: Charts Swing Structure + Single Prints
    SCInputRef Input_ES_SwingStructure_Chart = sc.Input[19];
    SCInputRef Input_NQ_SwingStructure_Chart = sc.Input[20];
    
    // 🆕 01/02/2026: Charts COMPOSITE PROFILES (5 périodes: 1j, 20j, 50j, 100j, 200j)
    SCInputRef Input_ES_CompositeProfile_Chart = sc.Input[21];
    SCInputRef Input_NQ_CompositeProfile_Chart = sc.Input[22];

    // === SETUP ===
    if (sc.SetDefaults) {
        sc.GraphName = "MIA AutoTrader BN v2 [REFACTORED]";
        sc.AutoLoop = 0;  // Manual loop
        sc.GraphRegion = 0;
        sc.FreeDLL = 1;

        // Inputs
        Input_Enabled.Name = "Bot Enabled";
        Input_Enabled.SetYesNo(1);

        Input_ES_Enabled.Name = "Trade ES";
        Input_ES_Enabled.SetYesNo(1);

        Input_NQ_Enabled.Name = "Trade NQ";
        Input_NQ_Enabled.SetYesNo(1);

        Input_ES_Paused.Name = "ES Paused";
        Input_ES_Paused.SetYesNo(0);

        Input_NQ_Paused.Name = "NQ Paused";
        Input_NQ_Paused.SetYesNo(0);

        Input_ES_Footprint_Chart.Name = "ES Footprint Chart #";
        Input_ES_Footprint_Chart.SetInt(1);   // Chart 1 = ES Footprint (Bataille Navale)

        Input_ES_Barres_Chart.Name = "ES Barres Chart #";
        Input_ES_Barres_Chart.SetInt(25);     // ðŸ”§ CORRIGÃ‰: Chart 25 = ES 1min Barres

        Input_NQ_Footprint_Chart.Name = "NQ Footprint Chart #";
        Input_NQ_Footprint_Chart.SetInt(2);   // Chart 2 = NQ Footprint (Bataille Navale)

        Input_NQ_Barres_Chart.Name = "NQ Barres Chart #";
        Input_NQ_Barres_Chart.SetInt(23);     // ðŸ”§ CORRIGÃ‰: Chart 23 = NQ 1min Barres

        Input_ES_Main_Chart.Name = "ES Main Chart #";
        Input_ES_Main_Chart.SetInt(25);       // ðŸ”§ CORRIGÃ‰: Chart 25 = ES Main (MenthorQ)

        Input_NQ_Main_Chart.Name = "NQ Main Chart #";
        Input_NQ_Main_Chart.SetInt(23);       // ðŸ”§ CORRIGÃ‰: Chart 23 = NQ Main (MenthorQ)

        // ðŸ†• Charts VIX et Daily ATR
        Input_VIX_Chart.Name = "VIX Chart #";
        Input_VIX_Chart.SetInt(15);

        Input_ES_Daily_Chart.Name = "ES Daily Chart # (ATR)";
        Input_ES_Daily_Chart.SetInt(16);

        Input_NQ_Daily_Chart.Name = "NQ Daily Chart # (ATR)";
        Input_NQ_Daily_Chart.SetInt(17);

        // ðŸ†• MODE TEST/PRODUCTION
        Input_Bot_Mode.Name = "Mode (0=PRODUCTION, 1=TEST)";
        Input_Bot_Mode.SetInt(0);  // Par dÃ©faut: PRODUCTION
        Input_Bot_Mode.SetIntLimits(0, 1);

        // ðŸ†• MODE RECTANGLES (Scalp)
        Input_Rectangle_Trading.Name = "Trade Rectangles (Scalp)";
        Input_Rectangle_Trading.SetYesNo(1);  // ActivÃ© par dÃ©faut

        // ðŸ†• 31/01/2026: DATA DUMP pour backtesting
        Input_Data_Dump.Name = "Data Dump (Backtest Data)";
        Input_Data_Dump.Name = "Data Dump bot (tick-by-tick brut — DÉSACTIVÉ: remplacé par DMP_Main.cpp)";
        // 🔧 28/02/2026: DÉSACTIVÉ PAR DÉFAUT — DÉCISION ARCHITECTURE
        // ─────────────────────────────────────────────────────────────
        // DEUX DUMPERS EXISTAIENT EN PARALLÈLE :
        //   1. MIA_DataDumper.h (ce flag) : tick-by-tick, ~175 champs bruts trading
        //      Chemin: D:\MIA_IA_system\DATA_SIERRA_CHART\BOT_DATA\YYYY\MM\YYYYMMDD\
        //      Format: bot_data_ES_YYYYMMDD.jsonl (~30 000 lignes/jour)
        //      Rôle original: replay décisions bot, analyse post-session
        //
        //   2. DMP_Main.cpp (standalone, étude séparée) : barre-par-barre, 168 features ML
        //      Chemin: D:\TRADING_SIERRA_CHART_AUTO\DATA\ES\YYYYMMDD_ES.jsonl
        //      Format: 1 JSON/barre (~390 lignes/jour RTH)
        //      Rôle: entraînement modèles ML — features normalisées G1-G12
        //
        // DÉCISION (28/02/2026): DMP_Main.cpp est LE dumper ML officiel.
        //   → Ce flag passe à NO (désactivé) pour éviter la confusion.
        //   → MIA_DataDumper.h reste dans le code pour DumpBotSnapshot()
        //     (snapshots trade ORDER_SENT/REJECT toujours utiles pour debug).
        //   → Pour réactiver le dump tick-by-tick: passer à Yes dans les Inputs.
        Input_Data_Dump.SetYesNo(0);  // NO par défaut — ML alimenté par DMP_Main.cpp

        // ðŸ†• 31/01/2026: Charts Volume Profile + Delta Divergence
        Input_ES_VolumeProfile_Chart.Name = "ES Volume Profile Chart #";
        Input_ES_VolumeProfile_Chart.SetInt(26);  // Chart 26 = ES VP + Delta Div

        Input_NQ_VolumeProfile_Chart.Name = "NQ Volume Profile Chart #";
        Input_NQ_VolumeProfile_Chart.SetInt(27);  // Chart 27 = NQ VP + Delta Div
        
        // ðŸ†• 31/01/2026: Charts Swing Structure + Single Prints
        Input_ES_SwingStructure_Chart.Name = "ES Swing Structure Chart #";
        Input_ES_SwingStructure_Chart.SetInt(28);  // Chart 28 = ES Swing + Single Prints
        
        Input_NQ_SwingStructure_Chart.Name = "NQ Swing Structure Chart #";
        Input_NQ_SwingStructure_Chart.SetInt(29);  // Chart 29 = NQ Swing + Single Prints
        
        // 🆕 01/02/2026: COMPOSITE PROFILES (5 périodes)
        Input_ES_CompositeProfile_Chart.Name = "ES Composite Profile Chart #";
        Input_ES_CompositeProfile_Chart.SetInt(31);  // Chart 31 = ES avec 5 COMPOSITE PROFILES
        
        Input_NQ_CompositeProfile_Chart.Name = "NQ Composite Profile Chart #";
        Input_NQ_CompositeProfile_Chart.SetInt(30);  // Chart 30 = NQ avec 5 COMPOSITE PROFILES

        // Initialisation Ã©tats
        memset(&g_es_state, 0, sizeof(BotState));
        memset(&g_nq_state, 0, sizeof(BotState));
        g_es_state.enabled = true;
        g_nq_state.enabled = true;
        strcpy(g_es_state.waiting_for, "Signal");
        strcpy(g_nq_state.waiting_for, "Signal");

        // ═══════════════════════════════════════════════════════════════════════
        // 🔧 28/02/2026: VÉRIFICATION study_mapping.json AU DÉMARRAGE
        // ─────────────────────────────────────────────────────────────────────
        // StudyConfig charge le JSON paresseusement au 1er appel STUDY_ID().
        // On force ici pour détecter un fichier manquant AVANT que
        // CollectBN_Data() ne lise silencieusement 0 partout.
        //
        // Échec silencieux sans ce check :
        //   JSON absent → STUDY_ID() = -1 → GetStudyArrayFromChartUsingID(-1)
        //   → tableau vide → bn.edge_buy=0, bn.color_up=0... bot ne trade pas.
        // ═══════════════════════════════════════════════════════════════════════
        {
            const char* json_path =
                "D:\\TRADING_SIERRA_CHART_AUTO\\CPP\\MIA_REFACTORED\\study_mapping.json";
            bool json_ok = StudyConfig::Instance().LoadFromFile(json_path);
            if (json_ok) {
                int test_edge = StudyConfig::Instance().GetStudyID("ES_FOOTPRINT", "EDGE_BUY");
                int test_vwap = StudyConfig::Instance().GetStudyID("ES_BARRES", "VWAP");
                if (test_edge > 0 && test_vwap > 0) {
                    char ok_msg[256];
                    snprintf(ok_msg, sizeof(ok_msg),
                             "OK study_mapping.json: ES EDGE_BUY=%d VWAP=%d",
                             test_edge, test_vwap);
                    sc.AddMessageToLog(ok_msg, 0);
                } else {
                    char warn_msg[256];
                    snprintf(warn_msg, sizeof(warn_msg),
                             "WARN study_mapping.json: cles manquantes EDGE_BUY=%d VWAP=%d",
                             test_edge, test_vwap);
                    sc.AddMessageToLog(warn_msg, 1);
                }
            } else {
                sc.AddMessageToLog("ERREUR CRITIQUE: study_mapping.json introuvable!", 1);
                sc.AddMessageToLog(
                    "Chemin: D:\\TRADING_SIERRA_CHART_AUTO\\CPP\\MIA_REFACTORED\\study_mapping.json", 1);
                sc.AddMessageToLog("Sans ce fichier le bot lit 0 partout - AUCUN trade.", 1);
            }
        }

        return;
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 31/01/2026: ROTATION AUTOMATIQUE DES LOGS AU DÃ‰MARRAGE
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ExÃ©cutÃ© UNE FOIS au premier tick aprÃ¨s compilation
    static bool logs_rotated = false;
    if (!logs_rotated) {
        RotateLogsIfNeeded("D:\\LOGS\\MIA", 30);  // Logs > 30 jours
        RotateSnapshotsIfNeeded("D:\\MIA_IA_system\\TRADING_SIERRA_CHART_AUTO\\SNAPSHOTS", 90);  // Snapshots > 90 jours
        sc.AddMessageToLog("[LOG_ROTATION] Nettoyage automatique des vieux fichiers effectue", 0);
        logs_rotated = true;
    }

    // === MISE Ã€ JOUR Ã‰TATS DEPUIS INPUTS ===
    // ðŸ†• Migration StateManager: AccÃ¨s thread-safe
    g_dashboard.bot_running = Input_Enabled.GetYesNo();
    
    UPDATE_ES_STATE([&](BotState& state) {
        state.enabled = Input_ES_Enabled.GetYesNo();
        state.paused = Input_ES_Paused.GetYesNo();
    });
    
    UPDATE_NQ_STATE([&](BotState& state) {
        state.enabled = Input_NQ_Enabled.GetYesNo();
        state.paused = Input_NQ_Paused.GetYesNo();
    });

    // Heartbeat
    g_dashboard.last_heartbeat = sc.CurrentSystemDateTime;

    // ðŸ†• 31/01/2026: DASHBOARD JSON TEMPS RÃ‰EL (toutes les 5 sec)
    static SCDateTime last_dashboard_write = 0;
    double seconds_since_last_write = (sc.CurrentSystemDateTime.GetAsDouble() - last_dashboard_write.GetAsDouble()) * 86400.0;
    if (seconds_since_last_write >= 5.0 || last_dashboard_write.GetAsDouble() == 0) {
        WriteDashboardJSON(sc, g_es_state, g_nq_state, g_dashboard);
        last_dashboard_write = sc.CurrentSystemDateTime;
    }
    
    // ðŸ†• 01/02/2026: BOTTLENECK REPORT (toutes les 60 sec) - Debug 100% rejets
    static SCDateTime last_bottleneck_report = 0;
    double sec_since_bottleneck = (sc.CurrentSystemDateTime.GetAsDouble() - last_bottleneck_report.GetAsDouble()) * 86400.0;
    if (sec_since_bottleneck >= 60.0 || last_bottleneck_report.GetAsDouble() == 0) {
        GetBottleneckReport(sc, false);  // ES
        GetBottleneckReport(sc, true);   // NQ
        last_bottleneck_report = sc.CurrentSystemDateTime;
    }

    // ðŸ”§ FIX: RÃ‰INITIALISATION QUOTIDIENNE AMÃ‰LIORÃ‰E (avec persistance)
    int y, mo, d, h, mi, s;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(y, mo, d, h, mi, s);

    // Utiliser variable persistante au lieu de globale
    int& g_last_day_persistent = sc.GetPersistentInt(1);  // Index 1 pour g_last_day
    
    // ðŸ”§ 30/01/2026: FLAG SÃ‰PARÃ‰ pour initialisation PnL baseline (par chart!)
    // Index 2 = flag init pour ce chart spÃ©cifique
    int& pnl_baseline_initialized = sc.GetPersistentInt(2);
    
    // Reset si:
    // 1. Nouveau jour dÃ©tectÃ© (g_last_day != d)
    // 2. OU premier tick aprÃ¨s recompilation (g_last_day == 0 ou -1)
    bool need_reset = (g_last_day_persistent > 0 && g_last_day_persistent != d);  // Nouveau jour
    bool first_tick_today = (g_last_day_persistent <= 0);  // Premier tick aprÃ¨s recompilation

    // ðŸ”§ 30/01/2026: FIX BUG PnL FANTÃ”ME!
    // Toujours initialiser last_processed_pnl au dÃ©marrage du study sur ce chart
    // AVANT le reset des stats, pour Ã©viter de comptabiliser des trades anciens!
    if (pnl_baseline_initialized != d) {  // Pas encore init aujourd'hui sur ce chart
        s_SCPositionData init_posData;
        sc.GetTradePosition(init_posData);
        
        // DÃ©terminer le symbole du chart (dÃ©fini localement ici car pas encore dÃ©clarÃ©)
        bool is_es_chart_local = (strstr(sc.GetChartSymbol(sc.ChartNumber), "ES") != NULL);
        
        if (is_es_chart_local) {
            g_es_state.last_processed_pnl = init_posData.LastTradeProfitLoss;
            sc.AddMessageToLog("ðŸ”§ ES: PnL baseline initialisee (ignore anciens trades)", 0);
        } else {
            g_nq_state.last_processed_pnl = init_posData.LastTradeProfitLoss;
            sc.AddMessageToLog("ðŸ”§ NQ: PnL baseline initialisee (ignore anciens trades)", 0);
        }
        pnl_baseline_initialized = d;  // Marquer comme initialisÃ© aujourd'hui
    }

    if (need_reset || first_tick_today) {
        // ðŸ†• 31/01/2026: Reset thread-safe via StateManager
        RESET_DAILY_STATS();
        
        // ðŸ†• 01/02/2026: Reset des compteurs de goulot
        ResetBottleneckCounters();
        
        // ðŸ†• Reset trade WHY ID au dÃ©but de journÃ©e
        g_trade_why_id = 1;

        if (need_reset) {
            sc.AddMessageToLog("ðŸ”„ NOUVEAU JOUR - Stats reinitialisees", 0);
        } else {
            sc.AddMessageToLog("ðŸ”„ PREMIER TICK DU JOUR - Stats initialisees a 0", 0);
        }
    }
    g_last_day_persistent = d;  // Sauvegarder le jour actuel (PERSISTANT)

    // === INITIALISER RAISONS ===
    strcpy(g_dashboard.bot_action_es, "Scanning...");
    strcpy(g_dashboard.bot_action_nq, "Scanning...");
    strcpy(g_dashboard.no_trade_reason_es, "");
    strcpy(g_dashboard.no_trade_reason_nq, "");

    // === VÃ‰RIFICATIONS PRÃ‰LIMINAIRES ===
    if (!g_dashboard.bot_running) {
        strcpy(g_dashboard.global_status, "BOT DISABLED");
        strcpy(g_dashboard.bot_action_es, "STOPPED");
        strcpy(g_dashboard.bot_action_nq, "STOPPED");
        strcpy(g_dashboard.no_trade_reason_es, "Bot desactive par l'utilisateur");
        strcpy(g_dashboard.no_trade_reason_nq, "Bot desactive par l'utilisateur");
        SaveDashboard(sc);
        DrawDashboardOnChart(sc);  // ðŸ”§ FIX: Toujours dessiner le dashboard!
        return;
    }

    // ðŸ†• Lire le mode TEST/PRODUCTION
    int bot_mode = Input_Bot_Mode.GetInt();

    // VÃ©rifier session (selon le mode)
    if (!IsWithinTradingSession(sc, bot_mode)) {
        if (bot_mode == MODE_TEST) {
            strcpy(g_dashboard.global_status, "HORS SESSION [TEST]");
            strcpy(g_dashboard.no_trade_reason_es, "Mode TEST - Hors horaires (00h00-23h00 FR)");
            strcpy(g_dashboard.no_trade_reason_nq, "Mode TEST - Hors horaires (00h00-23h00 FR)");
        } else {
            strcpy(g_dashboard.global_status, "HORS SESSION [PROD]");
            strcpy(g_dashboard.no_trade_reason_es, "Mode PROD - Hors horaires (02h30-21h00 FR)");
            strcpy(g_dashboard.no_trade_reason_nq, "Mode PROD - Hors horaires (02h30-21h00 FR)");
        }
        strcpy(g_dashboard.current_session, GetCurrentSessionName(sc));
        strcpy(g_dashboard.bot_action_es, "WAITING");
        strcpy(g_dashboard.bot_action_nq, "WAITING");
        SaveDashboard(sc);
        DrawDashboardOnChart(sc);  // ðŸ”§ FIX: Toujours dessiner le dashboard!
        return;
    }

    // Afficher le mode actif dans le status
    if (bot_mode == MODE_TEST) {
        strcpy(g_dashboard.global_status, "ðŸ§ª RUNNING [TEST MODE]");
    } else {
        strcpy(g_dashboard.global_status, "ðŸš€ RUNNING [PRODUCTION]");
    }

    strcpy(g_dashboard.current_session, GetCurrentSessionName(sc));
    // Note: global_status dÃ©jÃ  dÃ©fini ci-dessus avec le mode

    // === DÃ‰TECTION ANNONCES (Spread Ã©cartÃ© / DOM vide) ===
    // ðŸ†• DÃ‰SACTIVÃ‰ en MODE TEST pour Ã©viter les faux positifs Ã  l'ouverture
    if (bot_mode == MODE_PRODUCTION) {
        bool news_es = IsSpreadAbnormal(sc, CONFIG_ES) || IsDOMEmpty(sc, CONFIG_ES);
        bool news_nq = IsSpreadAbnormal(sc, CONFIG_NQ) || IsDOMEmpty(sc, CONFIG_NQ);

        if (news_es || news_nq) {
            g_dashboard.news_detected = true;
            strcpy(g_dashboard.news_message, "Spread/DOM anormal - possible annonce");

            // Bloquer trading 30 min
            SCDateTime block_until = sc.CurrentSystemDateTime;
            block_until += SCDateTime::MINUTES(NEWS_BLOCK_MINUTES);

            if (news_es) {
                UPDATE_ES_STATE([&](BotState& state) { state.news_block_until = block_until; });
                strcpy(g_dashboard.bot_action_es, "NEWS BLOCK");
                strcpy(g_dashboard.no_trade_reason_es, "SPREAD ECARTE/DOM VIDE - Annonce detectee! Block 30 min");
            }
            if (news_nq) {
                UPDATE_NQ_STATE([&](BotState& state) { state.news_block_until = block_until; });
                strcpy(g_dashboard.bot_action_nq, "NEWS BLOCK");
                strcpy(g_dashboard.no_trade_reason_nq, "SPREAD ECARTE/DOM VIDE - Annonce detectee! Block 30 min");
            }
        } else {
            g_dashboard.news_detected = false;
            g_dashboard.news_message[0] = '\0';
        }
    } else {
        // MODE TEST: Pas de dÃ©tection d'annonces - on trade quand mÃªme
        g_dashboard.news_detected = false;
        g_dashboard.news_message[0] = '\0';
        // Reset les blocks s'ils existaient
        UPDATE_ES_STATE([](BotState& state) { state.news_block_until = SCDateTime(0); });
        UPDATE_NQ_STATE([](BotState& state) { state.news_block_until = SCDateTime(0); });
    }

    // === COLLECTER DONNÃ‰ES ===
    BN_Data bn_es, bn_nq;
    MenthorQ_Data mq_es, mq_nq;
    
    // 🆕 01/02/2026: COMPOSITE PROFILES multi-périodes (Charts 30/31)
    CompositeProfile_Data cp_es, cp_nq;

    CollectBN_Data(sc, Input_ES_Footprint_Chart.GetInt(), Input_ES_Barres_Chart.GetInt(), bn_es, false);
    CollectBN_Data(sc, Input_NQ_Footprint_Chart.GetInt(), Input_NQ_Barres_Chart.GetInt(), bn_nq, true);
    CollectMenthorQ_Data(sc, Input_ES_Main_Chart.GetInt(), mq_es, false);  // ES
    CollectMenthorQ_Data(sc, Input_NQ_Main_Chart.GetInt(), mq_nq, true);   // NQ

    // ðŸ†• 31/01/2026: COLLECTER DONNÃ‰ES VOLUME PROFILE + DELTA DIVERGENCE (Charts 26/27)
    // - Previous VAH/VAL/VPOC = niveaux clÃ©s de la veille
    // - Delta Divergence = signal de retournement
    CollectVolumeProfile_Data(sc, Input_ES_VolumeProfile_Chart.GetInt(), bn_es, mq_es, false);
    CollectVolumeProfile_Data(sc, Input_NQ_VolumeProfile_Chart.GetInt(), bn_nq, mq_nq, true);
    
    // ðŸ†• 31/01/2026: COLLECTER DONNÃ‰ES SWING STRUCTURE + SINGLE PRINTS (Charts 28/29)
    // - Swing High/Low = points pivots pour identifier tendance (HH, HL, LH, LL)
    // - Delta Bar = direction du flux d'ordres sur la barre actuelle
    // - Single Prints = zones de faiblesse (creux volume = traits bleus)
    // 🔧 FIX 01/03/2026: es_price et nq_price depuis les vrais charts (SC_LAST)
    // AVANT: nq_price = sc.Close[sc.ArraySize - 1] = prix ES (bug silencieux!)
    // APRÈS: chaque symbole lit son propre chart via GetChartBaseData
    SCGraphData es_price_sw_data;
    sc.GetChartBaseData(Input_ES_Main_Chart.GetInt(), es_price_sw_data);
    float es_price = (es_price_sw_data[SC_LAST].GetArraySize() > 0)
        ? es_price_sw_data[SC_LAST][es_price_sw_data[SC_LAST].GetArraySize() - 1]
        : sc.Close[sc.ArraySize - 1];  // Fallback chart actuel

    SCGraphData nq_price_sw_data;
    sc.GetChartBaseData(Input_NQ_Main_Chart.GetInt(), nq_price_sw_data);
    float nq_price = (nq_price_sw_data[SC_LAST].GetArraySize() > 0)
        ? nq_price_sw_data[SC_LAST][nq_price_sw_data[SC_LAST].GetArraySize() - 1]
        : sc.Close[sc.ArraySize - 1];  // Fallback chart actuel
    CollectSwingStructure_Data(sc, Input_ES_SwingStructure_Chart.GetInt(), bn_es, es_price, false);
    CollectSwingStructure_Data(sc, Input_NQ_SwingStructure_Chart.GetInt(), bn_nq, nq_price, true);
    
    // 🆕 01/02/2026: Log des Swing High/Low + Session (Dow Theory dynamique)
    static int swing_debug_counter = 0;
    if (++swing_debug_counter >= 60) {  // Log toutes les 60 barres (~1 minute)
        swing_debug_counter = 0;
        char swing_msg[512];
        snprintf(swing_msg, sizeof(swing_msg), 
                 "📈 ES: Swing[H=%.2f L=%.2f] Session[H=%.2f L=%.2f] VPOC=%.2f | "
                 "NQ: Swing[H=%.2f L=%.2f] Session[H=%.2f L=%.2f] VPOC=%.2f",
                 bn_es.swing_high, bn_es.swing_low, bn_es.session_high, bn_es.session_low, bn_es.session_vpoc,
                 bn_nq.swing_high, bn_nq.swing_low, bn_nq.session_high, bn_nq.session_low, bn_nq.session_vpoc);
        sc.AddMessageToLog(swing_msg, 0);
    }
    
    // 🆕 01/02/2026: COLLECTER COMPOSITE PROFILES MULTI-PÉRIODES (Charts 30/31)
    // - 5 périodes: 1j, 20j, 50j, 100j, 200j
    // - Niveaux: VPOC, VAH, VAL, VWAP, HVN, LVN
    // - Usage: LVN = cibles TP (prix traverse vite), HVN = protection SL (prix stable)
    float tick_size_es = CONFIG_ES.tick_size;  // 0.25
    float tick_size_nq = CONFIG_NQ.tick_size;  // 0.25
    CollectCompositeProfile_Data(sc, Input_ES_CompositeProfile_Chart.GetInt(), es_price, tick_size_es, cp_es);
    CollectCompositeProfile_Data(sc, Input_NQ_CompositeProfile_Chart.GetInt(), nq_price, tick_size_nq, cp_nq);
    
    // Debug log (une seule fois au démarrage ou toutes les 100 barres)
    static int cp_debug_counter = 0;
    if (++cp_debug_counter >= 100) {
        cp_debug_counter = 0;
        if (cp_es.p1d.valid) {
            char msg[256];
            snprintf(msg, sizeof(msg), 
                     "📊 ES CP: 1d VPOC=%.2f | LVN_above=%.2f (%dj, %.0ft) | LVN_below=%.2f (%dj, %.0ft)",
                     cp_es.p1d.vpoc, 
                     cp_es.nearest_lvn_above, cp_es.nearest_lvn_above_period, cp_es.dist_nearest_lvn_above_ticks,
                     cp_es.nearest_lvn_below, cp_es.nearest_lvn_below_period, cp_es.dist_nearest_lvn_below_ticks);
            sc.AddMessageToLog(msg, 0);
        }
        if (cp_nq.p1d.valid) {
            char msg[256];
            snprintf(msg, sizeof(msg), 
                     "📊 NQ CP: 1d VPOC=%.2f | LVN_above=%.2f (%dj, %.0ft) | LVN_below=%.2f (%dj, %.0ft)",
                     cp_nq.p1d.vpoc, 
                     cp_nq.nearest_lvn_above, cp_nq.nearest_lvn_above_period, cp_nq.dist_nearest_lvn_above_ticks,
                     cp_nq.nearest_lvn_below, cp_nq.nearest_lvn_below_period, cp_nq.dist_nearest_lvn_below_ticks);
            sc.AddMessageToLog(msg, 0);
        }
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 25/01/2026: METTRE Ã€ JOUR LES TRACKERS D'EXTENSION LINES PERSISTANTS
    // Les Extension Lines sont trackÃ©es entre les snapshots pour:
    // - DÃ©tecter quand le prix revient vers une ligne crÃ©Ã©e il y a longtemps
    // - Placer les SL/TP de maniÃ¨re intelligente
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    float current_price_for_tracker = sc.Close[sc.ArraySize - 1];
    SCDateTime current_ts_for_tracker = sc.CurrentSystemDateTime;
    
    UpdateExtensionLinesTracker(g_ext_tracker_es, bn_es, current_price_for_tracker, 
                                current_ts_for_tracker, CONFIG_ES.tick_size);
    UpdateExtensionLinesTracker(g_ext_tracker_nq, bn_nq, current_price_for_tracker, 
                                current_ts_for_tracker, CONFIG_NQ.tick_size);

    // ðŸ†• Collecter donnÃ©es marchÃ© LIVE (VIX, ATR Daily, VWAP Slope)
    CollectMarketLiveData(
        sc,
        Input_VIX_Chart.GetInt(),
        Input_ES_Daily_Chart.GetInt(),
        Input_NQ_Daily_Chart.GetInt(),
        Input_ES_Barres_Chart.GetInt(),
        Input_NQ_Barres_Chart.GetInt()
    );

    // ðŸ†• 27/01/2026: DIAGNOSTIC SNAPSHOT - Exporte toutes les donnÃ©es toutes les 5 secondes
    // Fichier: D:\MIA_IA_system\DIAGNOSTIC_SNAPSHOT.json
    float current_price_es = 0;
    float current_price_nq = 0;
    SCGraphData es_price_data;
    sc.GetChartBaseData(Input_ES_Main_Chart.GetInt(), es_price_data);
    if (es_price_data[SC_LAST].GetArraySize() > 0) {
        current_price_es = es_price_data[SC_LAST][es_price_data[SC_LAST].GetArraySize() - 1];
    }
    SCGraphData nq_price_data;
    sc.GetChartBaseData(Input_NQ_Main_Chart.GetInt(), nq_price_data);
    if (nq_price_data[SC_LAST].GetArraySize() > 0) {
        current_price_nq = nq_price_data[SC_LAST][nq_price_data[SC_LAST].GetArraySize() - 1];
    }
    CalculateNextWall(mq_es, current_price_es);
    CalculateNextWall(mq_nq, current_price_nq);

    static SCDateTime last_diagnostic_time = 0;
    if (sc.CurrentSystemDateTime - last_diagnostic_time >= SCDateTime::SECONDS(5)) {
        WriteDiagnosticSnapshot(sc, bn_es, bn_nq, mq_es, mq_nq, current_price_es, current_price_nq);
        last_diagnostic_time = sc.CurrentSystemDateTime;
    }

    // Utiliser donnÃ©es live
    float vix = g_market_live.vix;
    float atr_es = g_market_live.atr_es > 0 ? g_market_live.atr_es : 15.0f;  // Fallback 15 pts
    float atr_nq = g_market_live.atr_nq > 0 ? g_market_live.atr_nq : 300.0f; // Fallback 300 pts

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 31/01/2026: DATA DUMP CONTINU POUR BACKTESTING
    // Fichiers JSONL avec TOUTES les donnÃ©es vues par le bot
    // Chemin: D:\MIA_IA_system\DATA_SIERRA_CHART\BOT_DATA\YYYY\MM\YYYYMMDD\
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    if (Input_Data_Dump.GetYesNo()) {
        // Dump ES (toutes les DATA_DUMP_INTERVAL_MS millisecondes)
        DumpBotDataSimple(sc, false, bn_es, mq_es, g_es_state, current_price_es,
                          vix, g_market_live.vix_regime, atr_es, g_dashboard.current_session);
        
        // Dump NQ
        DumpBotDataSimple(sc, true, bn_nq, mq_nq, g_nq_state, current_price_nq,
                          vix, g_market_live.vix_regime, atr_nq, g_dashboard.current_session);
    }

    // === VERIFICATIONS ORDRES/POSITIONS ===
    // Determiner symbole du chart actuel
    bool is_es_chart = (strstr(sc.GetChartSymbol(sc.ChartNumber), "ES") != NULL);
    BotState& active_state = is_es_chart ? g_es_state : g_nq_state;
    const SymbolConfig& active_config = is_es_chart ? CONFIG_ES : CONFIG_NQ;

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // SYNCHRONISATION AUTOMATIQUE DES POSITIONS EXISTANTES
    // (detecte les positions ouvertes manuellement ou via SimpleBracket)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    s_SCPositionData posData;
    sc.GetTradePosition(posData);

    // ðŸ”§ 27/01/2026: Ne PAS sync si le bot a un ordre en attente (c'est notre propre trade!)
    // ðŸ†• Migration StateManager: AccÃ¨s thread-safe
    BotState es_state_copy = GET_ES_STATE();
    if (is_es_chart && !es_state_copy.in_position && posData.PositionQuantity != 0 
        && es_state_copy.parent_order_id == 0) {
        // Position ES detectee mais pas trackee par le bot (vraiment externe)
        int sync_direction = (posData.PositionQuantity > 0) ? 1 : -1;
        float sync_price = posData.AveragePrice;
        
        UPDATE_ES_STATE([&](BotState& state) {
            state.in_position = true;
            state.entry_price = sync_price;
            state.position_direction = sync_direction;
            state.direction = sync_direction;  // Alias
            state.trailing_activated = false;
            state.break_even_activated = false;
            state.trailing_sl = 0;
            state.entry_time = sc.CurrentSystemDateTime;
            snprintf(state.status_message, sizeof(state.status_message),
                     "[SYNC] Position ES detectee: %s @ %.2f",
                     sync_direction == 1 ? "LONG" : "SHORT", sync_price);
        });
        
        BotState es_updated = GET_ES_STATE();
        sc.AddMessageToLog(es_updated.status_message, 0);
        LogSyncPosition(sc, "ES", sync_direction, sync_price);
    }

    // ðŸ”§ 27/01/2026: Ne PAS sync si le bot a un ordre en attente (c'est notre propre trade!)
    // ðŸ†• Migration StateManager: AccÃ¨s thread-safe
    BotState nq_state_copy = GET_NQ_STATE();
    if (!is_es_chart && !nq_state_copy.in_position && posData.PositionQuantity != 0
        && nq_state_copy.parent_order_id == 0) {
        // Position NQ detectee mais pas trackee par le bot (vraiment externe)
        int sync_direction_nq = (posData.PositionQuantity > 0) ? 1 : -1;
        float sync_price_nq = posData.AveragePrice;
        
        UPDATE_NQ_STATE([&](BotState& state) {
            state.in_position = true;
            state.entry_price = sync_price_nq;
            state.position_direction = sync_direction_nq;
            state.direction = sync_direction_nq;  // Alias
            state.trailing_activated = false;
            state.break_even_activated = false;
            state.trailing_sl = 0;
            state.entry_time = sc.CurrentSystemDateTime;
            snprintf(state.status_message, sizeof(state.status_message),
                     "[SYNC] Position NQ detectee: %s @ %.2f",
                     sync_direction_nq == 1 ? "LONG" : "SHORT", sync_price_nq);
        });
        
        BotState nq_updated = GET_NQ_STATE();
        sc.AddMessageToLog(nq_updated.status_message, 0);
        LogSyncPosition(sc, "NQ", sync_direction_nq, sync_price_nq);
    }
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    // Verifier si ordre LIMIT execute
    CheckOrderFilled(sc, active_state, active_config);

    // VÃ©rifier timeout ordres LIMIT (60 sec)
    CheckOrderTimeout(sc, active_state);

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // VÃ‰RIFICATION FERMETURE POSITION (SIMPLIFIÃ‰ ET ROBUSTE)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // GetTradePosition() retourne la position du symbole du chart actuel
    // Donc on vÃ©rifie uniquement le symbole correspondant au chart actif
    
    // ðŸ”§ 28/01/2026: DÃ‰TECTER AUSSI LES TRADES MANUELS!
    // MÃªme si in_position == false, on surveiller LastTradeProfitLoss
    // pour comptabiliser les trades manuels dans le dashboard
    // Note: posData dÃ©jÃ  dÃ©clarÃ© ligne 7358 pour SYNC
    
    if (is_es_chart) {
        // ES: VÃ©rifier position bot
        // ðŸ†• Migration StateManager
        BotState es_check = GET_ES_STATE();
        if (es_check.in_position) {
            ProcessPositionClosed(sc, g_es_state, CONFIG_ES);  // TODO: Migrer ProcessPositionClosed
        } 
        // ðŸ†• ES: DÃ©tecter trades manuels
        else if (posData.PositionQuantity == 0 && 
                 fabs(posData.LastTradeProfitLoss) > 0.01f &&
                 fabs(posData.LastTradeProfitLoss - es_check.last_processed_pnl) > 0.01f) {
            // Trade manuel ES fermÃ© â†’ ajouter au PNL
            float manual_pnl = posData.LastTradeProfitLoss;
            float new_pnl_today = 0;
            
            UPDATE_ES_STATE([&](BotState& state) {
                state.pnl_today += manual_pnl;
                state.trades_today++;
                if (manual_pnl >= 0) {
                    state.wins_today++;
                    if (manual_pnl > state.best_trade) state.best_trade = manual_pnl;
                } else {
                    state.losses_today++;
                    if (manual_pnl < state.worst_trade) state.worst_trade = manual_pnl;
                }
                state.last_processed_pnl = manual_pnl;
                new_pnl_today = state.pnl_today;
            });
            
            char msg[128];
            snprintf(msg, sizeof(msg), "ES MANUEL: $%.2f -> PnL Today: $%.2f", 
                     manual_pnl, new_pnl_today);
            sc.AddMessageToLog(msg, 0);
        }
    }
    
    if (!is_es_chart) {
        // NQ: VÃ©rifier position bot
        // ðŸ†• Migration StateManager
        BotState nq_check = GET_NQ_STATE();
        if (nq_check.in_position) {
            ProcessPositionClosed(sc, g_nq_state, CONFIG_NQ);  // TODO: Migrer ProcessPositionClosed
        }
        // ðŸ†• NQ: DÃ©tecter trades manuels
        else if (posData.PositionQuantity == 0 && 
                 fabs(posData.LastTradeProfitLoss) > 0.01f &&
                 fabs(posData.LastTradeProfitLoss - nq_check.last_processed_pnl) > 0.01f) {
            // Trade manuel NQ fermÃ© â†’ ajouter au PNL
            float manual_pnl = posData.LastTradeProfitLoss;
            float new_pnl_today_nq = 0;
            
            UPDATE_NQ_STATE([&](BotState& state) {
                state.pnl_today += manual_pnl;
                state.trades_today++;
                if (manual_pnl >= 0) {
                    state.wins_today++;
                    if (manual_pnl > state.best_trade) state.best_trade = manual_pnl;
                } else {
                    state.losses_today++;
                    if (manual_pnl < state.worst_trade) state.worst_trade = manual_pnl;
                }
                state.last_processed_pnl = manual_pnl;
                new_pnl_today_nq = state.pnl_today;
            });
            
            char msg[128];
            snprintf(msg, sizeof(msg), "NQ MANUEL: $%.2f -> PnL Today: $%.2f", 
                     manual_pnl, new_pnl_today_nq);
            sc.AddMessageToLog(msg, 0);
        }
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 31/01/2026: CIRCUIT BREAKER - VÃ©rification max loss/jour
    // PRODUCTION: CIRCUIT_BREAKER_ENABLED = true â†’ limites actives
    // TEST: CIRCUIT_BREAKER_ENABLED = false â†’ aucune limite
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    BotState es_cb_check = GET_ES_STATE();
    BotState nq_cb_check = GET_NQ_STATE();
    float total_pnl = es_cb_check.pnl_today + nq_cb_check.pnl_today;
    
    // ðŸ”’ CIRCUIT BREAKER ACTIF SEULEMENT EN PRODUCTION
    if (CIRCUIT_BREAKER_ENABLED) {
    
    // VÃ©rifier si circuit breaker doit Ãªtre activÃ©
    bool es_circuit_triggered = false;
    bool nq_circuit_triggered = false;
    
    if (!es_cb_check.circuit_breaker_active) {
        if (es_cb_check.pnl_today <= MAX_DAILY_LOSS_ES) {
            es_circuit_triggered = true;
            UPDATE_ES_STATE([&](BotState& s) {
                s.circuit_breaker_active = true;
                s.circuit_breaker_until = sc.CurrentSystemDateTime;
                s.circuit_breaker_until += SCDateTime::HOURS(CIRCUIT_BREAKER_COOLDOWN_HOURS);
                snprintf(s.circuit_breaker_reason, sizeof(s.circuit_breaker_reason),
                         "Max loss ES: $%.2f <= $%.2f", es_cb_check.pnl_today, MAX_DAILY_LOSS_ES);
            });
            sc.AddMessageToLog("[CIRCUIT BREAKER] ES MAX LOSS ATTEINT - Trading stoppe!", 1);
        } else if (es_cb_check.consecutive_losses >= MAX_CONSECUTIVE_LOSSES) {
            es_circuit_triggered = true;
            UPDATE_ES_STATE([&](BotState& s) {
                s.circuit_breaker_active = true;
                s.circuit_breaker_until = sc.CurrentSystemDateTime;
                s.circuit_breaker_until += SCDateTime::HOURS(CIRCUIT_BREAKER_COOLDOWN_HOURS);
                snprintf(s.circuit_breaker_reason, sizeof(s.circuit_breaker_reason),
                         "Max pertes consecutives: %d", es_cb_check.consecutive_losses);
            });
            sc.AddMessageToLog("[CIRCUIT BREAKER] ES PERTES CONSECUTIVES - Trading stoppe!", 1);
        }
    } else if (sc.CurrentSystemDateTime >= es_cb_check.circuit_breaker_until) {
        // Expiration du circuit breaker ES
        UPDATE_ES_STATE([](BotState& s) {
            s.circuit_breaker_active = false;
            s.circuit_breaker_reason[0] = '\0';
        });
        sc.AddMessageToLog("[CIRCUIT BREAKER] ES Reset - Trading reprend", 0);
    }
    
    if (!nq_cb_check.circuit_breaker_active) {
        if (nq_cb_check.pnl_today <= MAX_DAILY_LOSS_NQ) {
            nq_circuit_triggered = true;
            UPDATE_NQ_STATE([&](BotState& s) {
                s.circuit_breaker_active = true;
                s.circuit_breaker_until = sc.CurrentSystemDateTime;
                s.circuit_breaker_until += SCDateTime::HOURS(CIRCUIT_BREAKER_COOLDOWN_HOURS);
                snprintf(s.circuit_breaker_reason, sizeof(s.circuit_breaker_reason),
                         "Max loss NQ: $%.2f <= $%.2f", nq_cb_check.pnl_today, MAX_DAILY_LOSS_NQ);
            });
            sc.AddMessageToLog("[CIRCUIT BREAKER] NQ MAX LOSS ATTEINT - Trading stoppe!", 1);
        } else if (nq_cb_check.consecutive_losses >= MAX_CONSECUTIVE_LOSSES) {
            nq_circuit_triggered = true;
            UPDATE_NQ_STATE([&](BotState& s) {
                s.circuit_breaker_active = true;
                s.circuit_breaker_until = sc.CurrentSystemDateTime;
                s.circuit_breaker_until += SCDateTime::HOURS(CIRCUIT_BREAKER_COOLDOWN_HOURS);
                snprintf(s.circuit_breaker_reason, sizeof(s.circuit_breaker_reason),
                         "Max pertes consecutives: %d", nq_cb_check.consecutive_losses);
            });
            sc.AddMessageToLog("[CIRCUIT BREAKER] NQ PERTES CONSECUTIVES - Trading stoppe!", 1);
        }
    } else if (sc.CurrentSystemDateTime >= nq_cb_check.circuit_breaker_until) {
        // Expiration du circuit breaker NQ
        UPDATE_NQ_STATE([](BotState& s) {
            s.circuit_breaker_active = false;
            s.circuit_breaker_reason[0] = '\0';
        });
        sc.AddMessageToLog("[CIRCUIT BREAKER] NQ Reset - Trading reprend", 0);
    }
    
    // VÃ©rifier perte totale combinÃ©e
    if (total_pnl <= MAX_DAILY_LOSS_TOTAL && (!es_cb_check.circuit_breaker_active || !nq_cb_check.circuit_breaker_active)) {
        UPDATE_ES_STATE([&](BotState& s) {
            if (!s.circuit_breaker_active) {
                s.circuit_breaker_active = true;
                s.circuit_breaker_until = sc.CurrentSystemDateTime;
                s.circuit_breaker_until += SCDateTime::HOURS(CIRCUIT_BREAKER_COOLDOWN_HOURS);
                snprintf(s.circuit_breaker_reason, sizeof(s.circuit_breaker_reason),
                         "Max loss TOTAL: $%.2f <= $%.2f", total_pnl, MAX_DAILY_LOSS_TOTAL);
            }
        });
        UPDATE_NQ_STATE([&](BotState& s) {
            if (!s.circuit_breaker_active) {
                s.circuit_breaker_active = true;
                s.circuit_breaker_until = sc.CurrentSystemDateTime;
                s.circuit_breaker_until += SCDateTime::HOURS(CIRCUIT_BREAKER_COOLDOWN_HOURS);
                snprintf(s.circuit_breaker_reason, sizeof(s.circuit_breaker_reason),
                         "Max loss TOTAL: $%.2f <= $%.2f", total_pnl, MAX_DAILY_LOSS_TOTAL);
            }
        });
        sc.AddMessageToLog("[CIRCUIT BREAKER] MAX LOSS TOTAL ATTEINT - TOUT trading stoppe!", 1);
    }
    } // Fin if (CIRCUIT_BREAKER_ENABLED)
    
    // Refresh local state aprÃ¨s circuit breaker check
    es_cb_check = GET_ES_STATE();
    nq_cb_check = GET_NQ_STATE();

    // === TRAITEMENT ES ===
    // ðŸ†• Migration StateManager: Copie locale pour lectures
    BotState es_state_local = GET_ES_STATE();
    if (es_state_local.circuit_breaker_active) {
        strcpy(g_dashboard.bot_action_es, "CIRCUIT BREAKER");
        snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                 "STOP: %s", es_state_local.circuit_breaker_reason);
    } else if (!es_state_local.enabled) {
        strcpy(g_dashboard.bot_action_es, "DISABLED");
        strcpy(g_dashboard.no_trade_reason_es, "ES desactive dans les inputs");
    } else if (es_state_local.paused) {
        strcpy(g_dashboard.bot_action_es, "PAUSED");
        strcpy(g_dashboard.no_trade_reason_es, "ES en pause manuelle");
    } else if (es_state_local.in_position) {
        strcpy(g_dashboard.bot_action_es, "IN POSITION");
        snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                 "Position ouverte: %s @ %.2f",
                 es_state_local.position_direction == 1 ? "LONG" : "SHORT",
                 es_state_local.entry_price);
        UpdateTrailingStop(sc, g_es_state, CONFIG_ES, current_price_es);  // Garde g_es_state pour modification
    } else {
        // VÃ©rifier cooldowns
        bool can_trade = true;

        // ðŸ†• Migration StateManager: Lectures via copie locale
        BotState es_status = GET_ES_STATE();
        if (sc.CurrentSystemDateTime < es_status.cooldown_until) {
            can_trade = false;
            UPDATE_ES_STATE([](BotState& s) { strcpy(s.waiting_for, "Cooldown"); });
            strcpy(g_dashboard.bot_action_es, "COOLDOWN");
            strcpy(g_dashboard.no_trade_reason_es, "En cooldown apres trade precedent");
        }
        if (sc.CurrentSystemDateTime < es_status.news_block_until) {
            can_trade = false;
            UPDATE_ES_STATE([](BotState& s) { strcpy(s.waiting_for, "News block"); });
            strcpy(g_dashboard.bot_action_es, "NEWS BLOCK");
            strcpy(g_dashboard.no_trade_reason_es, "SPREAD ECARTE - Bloque 30 min suite annonce");
        }

        if (can_trade) {
            strcpy(g_dashboard.bot_action_es, "SCANNING");
            strcpy(g_dashboard.no_trade_reason_es, "En attente d'opportunite...");

            // === VETO FLAT: slope < seuil = NO TRADE (sauf exception desequilibre) ===
            // ðŸ”§ 27/01/2026: Seuil adaptatif par session
            // - Asia: 0.005 (plus permissif, volume faible = slope naturellement bas)
            // - London/US: 0.01 (standard)
            float vwap_slope_es = g_market_live.vwap_slope_es;
            bool is_asia_es = (strcmp(g_dashboard.current_session, "Asia") == 0);
            float flat_threshold_es = is_asia_es ? 0.005f : 0.01f;
            bool is_flat_es = (fabs(vwap_slope_es) < flat_threshold_es);

            if (is_flat_es) {
                // Exception DESEQUILIBRE: FLAT mais d_vwap > 15 ticks = OK
                float d_vwap_es = fabs(current_price_es - mq_es.vwap);
                float d_vwap_ticks_es = d_vwap_es / CONFIG_ES.tick_size;

                if (d_vwap_ticks_es <= 15.0f) {
                    // VETO - FLAT sans desequilibre
                    strcpy(g_dashboard.bot_action_es, "FLAT VETO");
                    snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                             "VWAP FLAT (slope=%.4f < %.3f) - d_vwap=%.0ft <= 15t", vwap_slope_es, flat_threshold_es, d_vwap_ticks_es);
                    can_trade = false;
                }
                // Si d_vwap > 15t â†’ on laisse passer (desequilibre = retour VWAP probable)
            }

            if (!can_trade) {
                // Skip to next iteration (FLAT VETO applied)
            } else {
            // ðŸ†• 01/02/2026: Compteur total d'Ã©valuations ES
            g_dashboard.total_evals_es++;
            
            // === LAYER 1 (MenthorQ) ===
            Layer1Result l1 = ValidateLayer1(sc, mq_es, current_price_es, CONFIG_ES, bn_es.momentum_score, &bn_es, true);

            // === LAYER 1B (Rectangles) - Alternative si L1 Ã©choue ===
            RectangleSignal rect_signal = {false, 0, 0, 0, 0, ""};
            bool rectangle_trading_enabled = Input_Rectangle_Trading.GetYesNo();
            if (!l1.passed && rectangle_trading_enabled) {
                rect_signal = DetectRectangleConfluence(sc, bn_es, mq_es, current_price_es, CONFIG_ES, false);
                if (rect_signal.has_signal) {
                    // Convertir en Layer1Result pour compatibilitÃ©
                    l1.passed = true;
                    l1.direction = rect_signal.direction;
                    l1.confidence = rect_signal.confidence;
                    l1.level_price = rect_signal.rectangle_price;
                    l1.distance_ticks = 0;  // Rectangle = contact direct
                    strncpy(l1.level_name, rect_signal.reason, sizeof(l1.level_name) - 1);
                }
            }

            if (!l1.passed) {
                // Message dÃ©taillÃ©: MenthorQ + Rectangles
                if (rectangle_trading_enabled) {
                    snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                        "L1: MQ=NON, RECT=NON (ColorUp=%.0f ColorDn=%.0f LongDnUp=%.0f)",
                        bn_es.color_up, bn_es.color_down, bn_es.long_down_up);
                } else {
                    strcpy(g_dashboard.no_trade_reason_es, "L1: Pas de niveau MenthorQ proche (RECT desactive)");
                }
                // ðŸ†• 31/01/2026: DUMP SNAPSHOT POUR ANALYSE 100% REJETS
                DumpBotSnapshot(sc, false, bn_es, bn_nq, mq_es, mq_nq, g_es_state, "L1_REJECT", g_dashboard.no_trade_reason_es);
                g_dashboard.signals_rejected_es++;
                g_dashboard.l1_reject_es++;  // ðŸ†• Compteur L1
                
                // ðŸ†• 01/02/2026: Log rejet L1
                TradeDecisionLog tdlog_rej = CreateDecisionLog(sc, false, 0, current_price_es);
                tdlog_rej.l1_passed = false;
                strncpy(tdlog_rej.l1_reason, g_dashboard.no_trade_reason_es, sizeof(tdlog_rej.l1_reason) - 1);
                tdlog_rej.trade_taken = false;
                snprintf(tdlog_rej.final_reason, sizeof(tdlog_rej.final_reason), "REJECT_L1: %s", g_dashboard.no_trade_reason_es);
                LogTradeDecision(sc, tdlog_rej);
            } else {
                int direction = l1.direction;

                // === LAYER 2 === ðŸ”§ OPTIMISÃ‰ 25/01/2026
                // Calculer depth_imbalance depuis DOM
                float depth_imbalance_es = 0.0f;
                s_MarketDepthEntry bid_entry, ask_entry;
                sc.GetBidMarketDepthEntryAtLevel(bid_entry, 0);
                sc.GetAskMarketDepthEntryAtLevel(ask_entry, 0);
                int total_dom = bid_entry.Quantity + ask_entry.Quantity;
                if (total_dom > 0) {
                    depth_imbalance_es = (float)(bid_entry.Quantity - ask_entry.Quantity) / total_dom;
                }
                
                // ðŸ”§ 30/01/2026: Utiliser FPBS (Order Flow rÃ©el) NORMALISÃ‰
                // Note: fpbs_bid_pct/ask_pct de Sierra ne sont PAS normalisÃ©s Ã  1.0
                // On doit normaliser: buy_pct = fpbs_bid / (fpbs_bid + fpbs_ask)
                float buy_pct_es, sell_pct_es;
                float fpbs_total_es = bn_es.fpbs_bid_pct + bn_es.fpbs_ask_pct;
                if (fpbs_total_es > 0.001f) {
                    // Normaliser les donnÃ©es FPBS pour obtenir de vrais pourcentages
                    buy_pct_es = bn_es.fpbs_bid_pct / fpbs_total_es;
                    sell_pct_es = bn_es.fpbs_ask_pct / fpbs_total_es;
                } else {
                    // Fallback sur color_up/down si FPBS indisponible
                    buy_pct_es = (bn_es.color_up > 0) ? 
                        bn_es.color_up / (bn_es.color_up + bn_es.color_down + 0.001f) : 0.5f;
                    sell_pct_es = 1.0f - buy_pct_es;
                }
                
                // VWAP slope
                float vwap_slope_es = g_market_live.vwap_slope_es;
                
                Layer2Result l2 = ValidateLayer2_OrderFlowTrend(direction, bn_es, bn_nq, vix,
                                                  0, buy_pct_es, CONFIG_ES, false,
                                                  depth_imbalance_es, sell_pct_es, vwap_slope_es);

                if (!l2.passed) {
                    snprintf(g_dashboard.last_rejected_es, sizeof(g_dashboard.last_rejected_es),
                             "L2: %s", l2.reason);
                    snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                             "L2 REJETE: BN=%.2f %s", l2.bn_score, l2.reason);
                    g_dashboard.signals_rejected_es++;
                    g_dashboard.l2_reject_es++;  // ðŸ†• Compteur L2
                    // ðŸ†• LOG REJET POUR ANALYSE
                    LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L2",
                                     l2.reason, current_price_es, l1.level_price, l1.distance_ticks,
                                     vix, l2.bn_score);
                    // ðŸ†• 31/01/2026: DUMP SNAPSHOT COMPLET
                    DumpBotSnapshot(sc, false, bn_es, bn_nq, mq_es, mq_nq, g_es_state, "L2_REJECT", l2.reason);
                } else {
                    // === LAYER 3 ===
                    Layer3Result l3 = ValidateLayer3(direction, bn_es, current_price_es,
                                                      mq_es, vix, atr_es,
                                                      g_dashboard.current_session, false);  // ES

                    if (l3.veto) {
                        snprintf(g_dashboard.last_rejected_es, sizeof(g_dashboard.last_rejected_es),
                                 "L3 VETO: %s", l3.veto_reason);
                        snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                 "L3 VETO: %s", l3.veto_reason);
                        g_dashboard.signals_rejected_es++;
                        g_dashboard.l3_veto_es++;  // ðŸ†• Compteur L3 VETO
                        // ðŸ†• LOG REJET POUR ANALYSE
                        LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L3_VETO",
                                         l3.veto_reason, current_price_es, l1.level_price, l1.distance_ticks,
                                         vix, bn_es.score);
                        // ðŸ†• 31/01/2026: DUMP SNAPSHOT COMPLET
                        DumpBotSnapshot(sc, false, bn_es, bn_nq, mq_es, mq_nq, g_es_state, "L3_VETO", l3.veto_reason);
                    } else if (!l3.passed) {
                        snprintf(g_dashboard.last_rejected_es, sizeof(g_dashboard.last_rejected_es),
                                 "L3: Context=%.2f trop bas", l3.confidence);
                        snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                 "L3 REJETE: Contexte defavorable %s", l3.context);
                        g_dashboard.signals_rejected_es++;
                        g_dashboard.l3_reject_es++;  // ðŸ†• Compteur L3 reject
                        // ðŸ†• LOG REJET POUR ANALYSE
                        LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L3",
                                         l3.context, current_price_es, l1.level_price, l1.distance_ticks,
                                         vix, bn_es.score);
                        // ðŸ†• 31/01/2026: DUMP SNAPSHOT COMPLET
                        DumpBotSnapshot(sc, false, bn_es, bn_nq, mq_es, mq_nq, g_es_state, "L3_REJECT", l3.context);
                    } else {
                        // === LAYER 4 (V54: 2 REGLES BACKTEST, 1/2 REQUIS) ===
                        // ðŸ”§ 25/01/2026: Nouvelles rÃ¨gles validÃ©es par backtest rigoureux
                        
                        // ðŸ”§ 01/02/2026: RenommÃ© bn_buy_pct pour Ã©viter confusion avec buy_pct FPBS (ligne ~833)
                        // Cette version utilise les signaux BN (comptage), pas le volume FPBS
                        float buyer_signals_es = bn_es.color_up + bn_es.rotation_up + bn_es.edge_buy + bn_es.absorb_bid;
                        float seller_signals_es = bn_es.color_down + bn_es.rotation_down + bn_es.edge_sell + bn_es.absorb_ask;
                        float total_signals_es = buyer_signals_es + seller_signals_es;
                        float bn_buy_pct_es = (total_signals_es > 0) ? (buyer_signals_es / total_signals_es) : 0.5f;
                        float bn_sell_pct_es = 1.0f - bn_buy_pct_es;

                        // Edge Buy/Sell pour Edge Dominant
                        float edge_buy_es = bn_es.edge_buy + bn_es.bar_edge_buy;
                        float edge_sell_es = bn_es.edge_sell + bn_es.bar_edge_sell;

                        // Calcul cum_delta proxy depuis rotation (momentum)
                        float cum_delta_proxy_es = bn_es.rotation_up - bn_es.rotation_down;

                        // ðŸ†• 01/02/2026: Passer les vrais paramÃ¨tres pour Score QualitÃ©
                        int trend_bias_es = GetTrendBias(bn_es.swing_high, bn_es.swing_low, current_price_es);
                        Layer4Result l4 = ValidateLayer4(direction, bn_buy_pct_es, bn_sell_pct_es, 
                                                         edge_buy_es, edge_sell_es,
                                                         cum_delta_proxy_es, bn_es.score,
                                                         g_market_live.vwap_slope_es, CONFIG_ES,
                                                         // ðŸ†• Nouveaux paramÃ¨tres Score QualitÃ©:
                                                         (float)l1.importance_score,  // L1 importance (1-3)
                                                         l1.confidence,               // L1 confiance
                                                         l2.confidence,               // L2 confiance
                                                         l3.confidence,               // L3 confiance
                                                         l2.visual_count,             // Signaux visuels BN
                                                         vix,                         // VIX actuel
                                                         trend_bias_es);              // Trend bias

                        if (!l4.passed) {
                            // ðŸ”§ 01/02/2026: Messages mis Ã  jour pour Score QualitÃ©
                            snprintf(g_dashboard.last_rejected_es, sizeof(g_dashboard.last_rejected_es),
                                     "L4: Grade=%c Score=%.0f<55", l4.grade, l4.quality_score);
                            snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                     "L4 REJETE: Grade %c (Score %.0f/100, combo=%d)",
                                     l4.grade, l4.quality_score, l4.combo_aligned);
                            g_dashboard.signals_rejected_es++;
                            g_dashboard.l4_reject_es++;  // ðŸ†• Compteur L4
                            char l4_reason[64];
                            snprintf(l4_reason, sizeof(l4_reason), "Grade %c Score %.0f<55", l4.grade, l4.quality_score);
                            LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L4",
                                            l4_reason, current_price_es, l1.level_price, l1.distance_ticks,
                                            vix, bn_es.score);
                            // ðŸ†• 31/01/2026: DUMP SNAPSHOT COMPLET
                            DumpBotSnapshot(sc, false, bn_es, bn_nq, mq_es, mq_nq, g_es_state, "L4_REJECT", l4_reason);
                            
                            // ðŸ†• 01/02/2026: Log rejet L4 avec contexte complet
                            TradeDecisionLog tdlog_l4 = CreateDecisionLog(sc, false, direction, current_price_es);
                            tdlog_l4.l1_passed = l1.passed;
                            tdlog_l4.l1_confidence = l1.confidence;
                            snprintf(tdlog_l4.l1_reason, sizeof(tdlog_l4.l1_reason), "%s", l1.level_name);
                            tdlog_l4.l2_passed = l2.passed;
                            tdlog_l4.l2_confidence = l2.confidence;
                            tdlog_l4.l3_passed = l3.passed;
                            tdlog_l4.l3_confidence = l3.confidence;
                            tdlog_l4.l4_passed = false;
                            tdlog_l4.l4_grade = l4.grade;
                            tdlog_l4.l4_quality = l4.quality_score;
                            snprintf(tdlog_l4.l4_reason, sizeof(tdlog_l4.l4_reason), "Score %.0f<55 combo=%d", l4.quality_score, l4.combo_aligned ? 1 : 0);
                            tdlog_l4.trade_taken = false;
                            snprintf(tdlog_l4.final_reason, sizeof(tdlog_l4.final_reason), 
                                     "REJECT_L4: Grade=%c Score=%.0f", l4.grade, l4.quality_score);
                            LogTradeDecision(sc, tdlog_l4);
                        } else {
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸŽ¯ 26/01/2026: QUICK WIN #1 - SEUILS MINIMUM "SWEET SPOT"
                            // Rejeter les 20% signaux les plus faibles (basÃ© sur analyse rÃ©elle)
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ”§ 27/01/2026: FILTRES RENFORCÃ‰S - "MEILLEURS SETUPS ONLY"
                            // ProblÃ¨me identifiÃ©: trades Ã  13% L3 et 41% L2 = MAUVAIS!
                            // Nouveau: exiger des signaux de QUALITÃ‰ pas juste "passables"
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ”§ 27/01/2026 16h: SEUILS Ã‰QUILIBRÃ‰S (ni trop strict ni trop lax)
                            // Analyse des rejets: L2=40% et L3=12% rejetÃ©s = trop strict!
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            float min_l1_conf_es = 0.35f;  // ES: 35% minimum (Ã©tait 38%)
                            float min_l2_conf_es = 0.38f;  // ES: 38% minimum (Ã©tait 45% = trop strict!)
                            // ðŸ”§ 01/02/2026: HarmonisÃ© avec seuil L3 (0.15 dans MIA_Layers.h)
                            float min_l3_conf_es = 0.15f;  // ES: 15% minimum (alignÃ© sur seuil L3)
                            float min_confluence_es = 0.42f;  // Confluence globale: 42% min (Ã©tait 50%)
                            
                            // Calcul confluence globale
                            float overall_conf_es = (l1.confidence + l2.confidence + l3.confidence + bn_es.score) / 4.0f;
                            
                            if (l1.confidence < min_l1_conf_es) {
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "L1 REJET: Conf=%.1f%% < %.0f%% (signal trop faible)", 
                                         l1.confidence * 100, min_l1_conf_es * 100);
                                g_dashboard.signals_rejected_es++;
                                g_dashboard.min_reject_es++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L1_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price, 
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else if (l2.confidence < min_l2_conf_es) {
                                // ðŸ†• 27/01/2026: Nouveau filtre L2!
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "L2 REJET: Conf=%.1f%% < %.0f%% (BN/corrÃ©lation trop faible)", 
                                         l2.confidence * 100, min_l2_conf_es * 100);
                                g_dashboard.signals_rejected_es++;
                                g_dashboard.min_reject_es++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L2_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price,
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else if (l3.confidence < min_l3_conf_es) {
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "L3 REJET: Conf=%.1f%% < %.0f%% (contexte trop faible)", 
                                         l3.confidence * 100, min_l3_conf_es * 100);
                                g_dashboard.signals_rejected_es++;
                                g_dashboard.min_reject_es++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L3_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price,
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else if (bn_es.score < 0.40f) {  // BN: 40% minimum
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "BN REJET: Score=%.1f%% < 40%% (BN trop faible)", bn_es.score * 100);
                                g_dashboard.signals_rejected_es++;
                                g_dashboard.min_reject_es++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "BN_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price,
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else if (overall_conf_es < min_confluence_es) {
                                // ðŸ†• 27/01/2026: Nouveau filtre confluence globale!
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "CONF REJET: Global=%.1f%% < %.0f%% (L1=%.0f L2=%.0f L3=%.0f BN=%.0f)", 
                                         overall_conf_es * 100, min_confluence_es * 100,
                                         l1.confidence * 100, l2.confidence * 100, 
                                         l3.confidence * 100, bn_es.score * 100);
                                g_dashboard.signals_rejected_es++;
                                g_dashboard.min_reject_es++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "CONF_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price,
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else {
                            // ðŸŽ¯ 26/01/2026: QUICK WIN #2 - RECTANGLE BONUS +5%
                            // Rectangles ont 70% WR vs 50% boules (analyse trades rÃ©els)
                            float l1_confidence_bonus = l1.confidence;
                            bool has_rectangle_es = (direction == 1) ? 
                                (bn_es.price_in_edge_rect_buy || bn_es.num_edge_rect_buy > 0) :
                                (bn_es.price_in_edge_rect_sell || bn_es.num_edge_rect_sell > 0);
                            
                            if (has_rectangle_es) {
                                l1_confidence_bonus *= 1.05f;  // +5% bonus zones institutionnelles
                            }
                            
                            // === SIGNAL VALIDÃ‰ - VERIFIER R:R ===
                            // ðŸ†• 25/01/2026: Passer le tracker persistant pour SL/TP intelligent
                            SLTPResult sltp = CalculateProtectedSLTP(direction, current_price_es, mq_es, bn_es, CONFIG_ES, &g_ext_tracker_es, &cp_es);

                            // ðŸ†• VETO si obstacle bloque le R:R
                            if (!sltp.is_valid) {
                                strcpy(g_dashboard.bot_action_es, "VETO_RR");
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "ES: %s", sltp.tp_based_on);
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT",
                                                  "SLTP", sltp.tp_based_on, current_price_es, 0, 0, vix, bn_es.score);
                            } else {

                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ”§ 28/01/2026: HARD LIMIT SL/TP - TOUJOURS APPLIQUER!
                            // Bug: SL/TP trop loin sans limiter!
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            float tick_size_es = CONFIG_ES.tick_size;
                            float max_sl_dist_es = CONFIG_ES.sl_max_ticks * tick_size_es;
                            float max_tp_dist_es = CONFIG_ES.tp_max_ticks * tick_size_es;
                            float current_sl_dist_es = fabs(sltp.sl_price - current_price_es);
                            float current_tp_dist_es = fabs(sltp.tp_price - current_price_es);
                            
                            // FORCER SL max
                            if (current_sl_dist_es > max_sl_dist_es) {
                                if (direction == 1) {
                                    sltp.sl_price = current_price_es - max_sl_dist_es;
                                } else {
                                    sltp.sl_price = current_price_es + max_sl_dist_es;
                                }
                                sltp.sl_ticks = CONFIG_ES.sl_max_ticks;
                                strncpy(sltp.sl_based_on, "MAX_HARD_LIMIT", sizeof(sltp.sl_based_on));
                            }
                            
                            // FORCER TP max
                            if (current_tp_dist_es > max_tp_dist_es) {
                                if (direction == 1) {
                                    sltp.tp_price = current_price_es + max_tp_dist_es;
                                } else {
                                    sltp.tp_price = current_price_es - max_tp_dist_es;
                                }
                                sltp.tp_ticks = CONFIG_ES.tp_max_ticks;
                                strncpy(sltp.tp_based_on, "MAX_HARD_LIMIT", sizeof(sltp.tp_based_on));
                            }

                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ†• 01/02/2026: RÃ‰GIME MARCHÃ‰ MULTI-FACTEURS PRO
                            // Calcul avant les ajustements TP pour l'utiliser
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            RegimeResult regime_es = CalculateMarketRegime(
                                g_market_live.vwap_slope_es,
                                atr_es,
                                atr_es * 0.85f, // ATR avg approximation
                                g_market_live.vix_regime,
                                bn_es.cvd_slope,
                                bn_es.swing_high,
                                bn_es.swing_low,
                                current_price_es,
                                false  // ðŸ†• is_nq = false (ES)
                            );
                            
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ†• 01/02/2026: APPLIQUER L4 + RÃ‰GIME TP MULTIPLIER
                            // âš ï¸ SEULEMENT si TP n'est PAS basÃ© sur un obstacle!
                            // Si TP basÃ© sur obstacle â†’ NE PAS Ã©tendre (sinon TP aprÃ¨s le mur!)
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            float tp_distance = fabs(sltp.tp_price - current_price_es);
                            float tp_mult_total_es = 1.0f;
                            
                            // VÃ©rifier si TP est basÃ© sur un obstacle (contient "BEFORE_" ou "OBSTACLE")
                            bool tp_based_on_obstacle_es = (strstr(sltp.tp_based_on, "BEFORE_") != nullptr ||
                                                            strstr(sltp.tp_based_on, "OBSTACLE") != nullptr ||
                                                            strstr(sltp.tp_based_on, "RECT_") != nullptr ||
                                                            strstr(sltp.tp_based_on, "GAMMA") != nullptr ||
                                                            strstr(sltp.tp_based_on, "CALL") != nullptr ||
                                                            strstr(sltp.tp_based_on, "PUT") != nullptr);
                            
                            if (!tp_based_on_obstacle_es) {
                                // TP LIBRE (FIXED ou MAX_LIMIT) â†’ On peut ajuster
                                if (l4.tp_multiplier > 1.0f) {
                                    tp_mult_total_es = l4.tp_multiplier;
                                }
                                tp_mult_total_es *= regime_es.tp_multiplier;
                                
                                // LIMITE: Max +50%, Min -30%
                                if (tp_mult_total_es > 1.50f) tp_mult_total_es = 1.50f;
                                if (tp_mult_total_es < 0.70f) tp_mult_total_es = 0.70f;
                                
                                tp_distance *= tp_mult_total_es;
                                
                                // Respecter le hard limit
                                float max_tp_dist = CONFIG_ES.tp_max_ticks * tick_size_es;
                                if (tp_distance > max_tp_dist) tp_distance = max_tp_dist;
                                
                                if (direction == 1) {
                                    sltp.tp_price = current_price_es + tp_distance;
                                } else {
                                    sltp.tp_price = current_price_es - tp_distance;
                                }
                                sltp.tp_ticks = (int)(tp_distance / tick_size_es);
                            }
                            // Si obstacle: garder le TP original (dÃ©jÃ  placÃ© avant le mur)
                            
                            // Log L4 + RÃ©gime
                            char regime_note[128];
                            snprintf(regime_note, sizeof(regime_note), 
                                     "ðŸŽ¯ ES L4=%c + %s â†’ TPx%.2f %s", 
                                     l4.grade, GetRegimeName(regime_es.regime),
                                     tp_mult_total_es, tp_based_on_obstacle_es ? "(obstacle=kept)" : "(applied)");
                            sc.AddMessageToLog(regime_note, 0);
                            
                            // ðŸ†• Propager le flag trailing au state (pour UpdateTrailingStop)
                            g_es_state.trailing_allowed = regime_es.trailing_enabled;

                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // DÃ‰TECTION TRADE HAUTE QUALITÃ‰ LEGACY (risque augmentÃ©)
                            // Note: Peut se cumuler avec L4 pour trades A+HQ
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // 01/03/2026: Flag VETO si HQ casse le R:R
                            bool es_hq_rr_veto = false;

                            int visual_count_es = 0;
                            if (bn_es.edge_buy > 0 || bn_es.edge_sell > 0) visual_count_es++;
                            if (bn_es.color_up > 10 || bn_es.color_down > 10) visual_count_es++;
                            if (bn_es.long_down_up > 0 || bn_es.long_up_down > 0) visual_count_es++;
                            if (bn_es.num_edge_rect_buy > 0 || bn_es.num_edge_rect_sell > 0) visual_count_es++;
                            if (bn_es.absorb_bid > 0 || bn_es.absorb_ask > 0) visual_count_es++;

                            HighQualityResult hq_es = DetectHighQualityTrade(
                                direction, bn_es, l1.importance_score,
                                visual_count_es, !sltp.is_valid
                            );

                            // ðŸ”§ 01/02/2026: HQ ne modifie plus le TP (dÃ©jÃ  gÃ©rÃ© par L4+RÃ©gime avec cap!)
                            // HQ modifie SEULEMENT le SL (lÃ©gÃ¨rement plus large pour Ã©viter stop prÃ©maturÃ©)
                            if (hq_es.is_high_quality) {
                                // SL lÃ©gÃ¨rement plus large pour trades haute qualitÃ©
                                float sl_distance = fabs(sltp.sl_price - current_price_es);
                                sl_distance *= hq_es.sl_multiplier;
                                if (direction == 1) {
                                    sltp.sl_price = current_price_es - sl_distance;
                                } else {
                                    sltp.sl_price = current_price_es + sl_distance;
                                }

                                // Limiter SL max
                                if (fabs(sltp.sl_price - current_price_es) > CONFIG_ES.sl_max_ticks * tick_size_es) {
                                    if (direction == 1) {
                                        sltp.sl_price = current_price_es - CONFIG_ES.sl_max_ticks * tick_size_es;
                                    } else {
                                        sltp.sl_price = current_price_es + CONFIG_ES.sl_max_ticks * tick_size_es;
                                    }
                                }

                                // Recalculer SL ticks
                                sltp.sl_ticks = (int)(fabs(sltp.sl_price - current_price_es) / tick_size_es);

                                // 01/03/2026: REVALIDATION R:R APRES AJUSTEMENT HQ
                                if (sltp.sl_ticks > 0) {
                                    sltp.rr_ratio = (float)sltp.tp_ticks / (float)sltp.sl_ticks;
                                    if (sltp.rr_ratio < CONFIG_ES.min_rr_ratio) {
                                        char rr_msg[128];
                                        snprintf(rr_msg, sizeof(rr_msg),
                                                 "HQ R:R VETO ES: %.2f < %.2f (SL=%d TP=%d apres HQ x%.2f)",
                                                 sltp.rr_ratio, CONFIG_ES.min_rr_ratio,
                                                 sltp.sl_ticks, sltp.tp_ticks, hq_es.sl_multiplier);
                                        sc.AddMessageToLog(rr_msg, 0);
                                        g_dashboard.sltp_reject_es++;
                                        es_hq_rr_veto = true;
                                    }
                                }

                                // Log HQ (sans modification TP)
                                char hq_log[128];
                                snprintf(hq_log, sizeof(hq_log), "â­ HQ: %s (SL Ã©largi x%.2f)", 
                                         hq_es.reason, hq_es.sl_multiplier);
                                sc.AddMessageToLog(hq_log, 0);
                            }

                            // ðŸ†• Calculer ancre BN avant d'entrer
                            float bn_anchor_es = CalculateBNAnchor(direction, current_price_es, bn_es, CONFIG_ES.tick_size);

                            // ðŸ†• Stocker donnÃ©es Discord pour notification (Migration StateManager)
                            UPDATE_ES_STATE([&](BotState& state) {
                                state.discord_bn_score = bn_es.score;
                                state.discord_l1_conf = l1.confidence;
                                state.discord_l2_conf = l2.confidence;
                                state.discord_l3_conf = l3.confidence;
                                state.discord_l4_combo = l4.combo_aligned;
                                state.discord_vwap_slope = g_market_live.vwap_slope_es;
                                state.discord_is_rectangle = rect_signal.has_signal;
                            });

                            // ðŸ†• TRADE WHY JOURNAL - Log avant envoi ordre
                            TradeWhy why = {0};
                            why.trade_id = g_trade_why_id++;
                            why.timestamp = sc.CurrentSystemDateTime;
                            strncpy(why.symbol, "ES", sizeof(why.symbol) - 1);
                            strncpy(why.side, direction == 1 ? "LONG" : "SHORT", sizeof(why.side) - 1);
                            strncpy(why.execution_mode, "PENDING", sizeof(why.execution_mode) - 1);  // Sera mis Ã  jour aprÃ¨s SendBracketOrder

                            // Trigger level
                            if (rect_signal.has_signal) {
                                strncpy(why.trigger_level_type, "RECT", sizeof(why.trigger_level_type) - 1);
                                why.trigger_level_price = rect_signal.rectangle_price;
                            } else {
                                strncpy(why.trigger_level_type, l1.level_name, sizeof(why.trigger_level_type) - 1);
                                why.trigger_level_price = l1.level_price;
                            }

                            // Anchor
                            why.anchor_final = bn_anchor_es > 0 ? bn_anchor_es : current_price_es;
                            why.anchor_ext = (bn_es.num_ext_support > 0 || bn_es.num_ext_resist > 0) ? why.anchor_final : 0;
                            why.anchor_color = 0;  // TODO: extraire depuis extension lines si besoin
                            why.dist_ticks_to_anchor = fabs(current_price_es - why.anchor_final) / CONFIG_ES.tick_size;

                            // Trade info
                            why.entry_price = current_price_es;
                            why.sl_price = sltp.sl_price;
                            why.tp_price = sltp.tp_price;
                            
                            // ðŸ†• 01/02/2026: POSITION SIZING DYNAMIQUE + RÃ‰GIME MARCHÃ‰
                            // Calcul drawdown approximatif (PnL nÃ©gatif / capital estimÃ©)
                            float dd_pct_es = 0.0f;
                            if (g_es_state.pnl_today < 0) {
                                dd_pct_es = fabs(g_es_state.pnl_today) / ACCOUNT_CAPITAL_BASE;  // 01/03/2026: Externalisé dans MIA_Config.h
                            }
                            
                            // Position size = Base Ã— RÃ©gime multiplier (rÃ©gime_es calculÃ© plus haut)
                            int base_qty = CalculatePositionSize(false, l4.grade, g_market_live.vix_regime, dd_pct_es);
                            why.qty = (int)(base_qty * regime_es.size_multiplier);
                            if (why.qty < 1) why.qty = 1;

                            // Layers
                            why.l1_ok = l1.passed ? 1 : 0;
                            why.l2_ok = l2.passed ? 1 : 0;
                            why.l3_ok = l3.passed ? 1 : 0;
                            why.l4_ok = l4.passed ? 1 : 0;
                            why.l1_confidence = l1.confidence;
                            why.l2_confidence = l2.confidence;
                            why.l3_confidence = l3.confidence;
                            why.l4_combo = l4.combo_aligned;
                            why.bn_score = bn_es.score;
                            why.confluence_score = l2.confidence;  // Approximatif
                            why.is_rectangle = rect_signal.has_signal;

                            // Contexte marchÃ©
                            why.vwap_slope = g_market_live.vwap_slope_es;
                            why.vwap_dist_ticks = fabs(current_price_es - mq_es.vwap) / CONFIG_ES.tick_size;
                            why.vix_value = vix;
                            strncpy(why.vix_regime, GetVIXRegimeName(g_market_live.vix_regime), sizeof(why.vix_regime) - 1);
                            why.dom_healthy = 1;  // TODO: vÃ©rifier DOM health
                            why.spread_ticks = 1.0f;  // TODO: rÃ©cupÃ©rer spread rÃ©el

                            // Veto
                            why.veto_triggered = 0;
                            why.veto_reason[0] = '\0';
                            why.layer_reject_reason[0] = '\0';

                            // Notes - ðŸ”§ 01/02/2026: Afficher Grade L4
                            snprintf(why.notes, sizeof(why.notes), "L1:%s Grade:%c Score:%.0f", 
                                     l1.level_name, l4.grade, l4.quality_score);

                            // Log avant envoi (execution_mode sera mis Ã  jour aprÃ¨s)
                            LogTradeWhy(sc, why, CONFIG_ES);

                            strcpy(g_dashboard.bot_action_es, "ENTERING");
                            strcpy(g_dashboard.no_trade_reason_es, "SIGNAL VALIDE - Entree en cours!");

                            // 01/03/2026: GUARD - Si HQ a casse le R:R, ne pas trader
                            if (es_hq_rr_veto) {
                                strcpy(g_dashboard.bot_action_es, "VETO_HQ_RR");
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "ES HQ R:R %.2f < %.2f apres SL elargi", sltp.rr_ratio, CONFIG_ES.min_rr_ratio);
                                sc.AddMessageToLog("ES SKIP: R:R invalide apres HQ SL expansion", 0);
                            } else {

                            // Envoyer ordre (va dÃ©terminer execution_mode)
                            // ðŸ†• 01/02/2026: Passer la quantitÃ© dynamique
                            bool order_sent = SendBracketOrder(sc, direction, current_price_es,
                                           sltp.sl_price, sltp.tp_price, g_es_state, bn_anchor_es, why.qty);

                            // ðŸ†• Mettre Ã  jour execution_mode dans TradeWhy (Migration StateManager)
                            if (order_sent) {
                                // DÃ©terminer mode depuis l'Ã©tat (pending_limit_order indique LIMIT)
                                BotState es_exec = GET_ES_STATE();
                                if (es_exec.pending_limit_order) {
                                    strncpy(why.execution_mode, "PENDING_LIMIT", sizeof(why.execution_mode) - 1);
                                } else {
                                    strncpy(why.execution_mode, "IMMEDIATE", sizeof(why.execution_mode) - 1);
                                }
                            } else {
                                strncpy(why.execution_mode, "SKIP_TOO_FAR", sizeof(why.execution_mode) - 1);
                            }

                            // Log final avec le bon mode
                            if (order_sent) {
                                LogTradeWhy(sc, why, CONFIG_ES);
                                // ðŸ†• 31/01/2026: DUMP SNAPSHOT QUAND TRADE ACCEPTÃ‰
                                DumpBotSnapshot(sc, false, bn_es, bn_nq, mq_es, mq_nq, g_es_state, "ORDER_SENT", "");
                                
                                // ðŸ†• 01/02/2026: JOURNAL DE TRADE COMPLET
                                TradeDecisionLog tdlog = CreateDecisionLog(sc, false, direction, current_price_es);
                                tdlog.l1_passed = l1.passed;
                                tdlog.l1_confidence = l1.confidence;
                                snprintf(tdlog.l1_reason, sizeof(tdlog.l1_reason), "%s@%.2f", l1.level_name, l1.level_price);
                                tdlog.l2_passed = l2.passed;
                                tdlog.l2_confidence = l2.confidence;
                                snprintf(tdlog.l2_reason, sizeof(tdlog.l2_reason), "OFTrend:%.2f", l2.confidence);
                                tdlog.l3_passed = l3.passed;
                                tdlog.l3_veto = false;
                                tdlog.l3_confidence = l3.confidence;
                                strncpy(tdlog.l3_reason, l3.veto_reason, sizeof(tdlog.l3_reason) - 1);
                                tdlog.l4_passed = l4.passed;
                                tdlog.l4_grade = l4.grade;
                                tdlog.l4_quality = l4.quality_score;
                                snprintf(tdlog.l4_reason, sizeof(tdlog.l4_reason), "combo=%d", l4.combo_aligned ? 1 : 0);
                                strncpy(tdlog.regime, GetRegimeName(regime_es.regime), sizeof(tdlog.regime) - 1);
                                tdlog.regime_score = regime_es.score;
                                tdlog.size_mult = regime_es.size_multiplier;
                                tdlog.tp_mult = tp_mult_total_es;
                                tdlog.trailing_allowed = regime_es.trailing_enabled;
                                tdlog.sl_price = sltp.sl_price;
                                tdlog.tp_price = sltp.tp_price;
                                tdlog.sl_ticks = sltp.sl_ticks;
                                tdlog.tp_ticks = sltp.tp_ticks;
                                strncpy(tdlog.tp_based_on, sltp.tp_based_on, sizeof(tdlog.tp_based_on) - 1);
                                tdlog.trade_taken = true;
                                snprintf(tdlog.final_reason, sizeof(tdlog.final_reason), 
                                         "TRADE_TAKEN: L4=%c Regime=%s Qty=%d", l4.grade, GetRegimeName(regime_es.regime), why.qty);
                                tdlog.qty = why.qty;
                                LogTradeDecision(sc, tdlog);
                            }

                            // ðŸ†• Mettre Ã  jour execution_mode dans le log si ordre envoyÃ©
                            if (order_sent) {
                                // Le mode sera dÃ©terminÃ© dans SendBracketOrder (MARKET/LIMIT/SKIP)
                                // On pourrait relogger avec le bon mode, mais pour l'instant on garde "PENDING"
                            }
                            }  // 01/03/2026: Fin else es_hq_rr_veto guard
                            }  // Fin else SLTP valid
                            }  // Fin else (L1/L3/BN ok) - Quick Wins
                        }  // Fin else L4.passed
                    }  // Fin else L3 chain (veto/passed/else)
                }  // Fin else L2.passed
            }  // Fin else L1.passed
            }  // Fin else FLAT VETO
        }
        CheckOrderTimeout(sc, g_es_state);
    }

    // === TRAITEMENT NQ ===
    // ðŸ†• Migration StateManager: Copie locale pour lectures
    BotState nq_state_local = GET_NQ_STATE();
    if (nq_state_local.circuit_breaker_active) {
        strcpy(g_dashboard.bot_action_nq, "CIRCUIT BREAKER");
        snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                 "STOP: %s", nq_state_local.circuit_breaker_reason);
    } else if (!nq_state_local.enabled) {
        strcpy(g_dashboard.bot_action_nq, "DISABLED");
        strcpy(g_dashboard.no_trade_reason_nq, "NQ desactive dans les inputs");
    } else if (nq_state_local.paused) {
        strcpy(g_dashboard.bot_action_nq, "PAUSED");
        strcpy(g_dashboard.no_trade_reason_nq, "NQ en pause manuelle");
    } else if (nq_state_local.in_position) {
        strcpy(g_dashboard.bot_action_nq, "IN POSITION");
        snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                 "Position ouverte: %s @ %.2f",
                 nq_state_local.position_direction == 1 ? "LONG" : "SHORT",
                 nq_state_local.entry_price);
        UpdateTrailingStop(sc, g_nq_state, CONFIG_NQ, current_price_nq);  // Garde g_nq_state pour modification
    } else {
        bool can_trade_nq = true;

        // ðŸ†• Migration StateManager: Lectures via copie locale
        BotState nq_status = GET_NQ_STATE();
        if (sc.CurrentSystemDateTime < nq_status.cooldown_until) {
            can_trade_nq = false;
            UPDATE_NQ_STATE([](BotState& s) { strcpy(s.waiting_for, "Cooldown"); });
            strcpy(g_dashboard.bot_action_nq, "COOLDOWN");
            strcpy(g_dashboard.no_trade_reason_nq, "En cooldown apres trade precedent");
        }
        if (sc.CurrentSystemDateTime < nq_status.news_block_until) {
            can_trade_nq = false;
            UPDATE_NQ_STATE([](BotState& s) { strcpy(s.waiting_for, "News block"); });
            strcpy(g_dashboard.bot_action_nq, "NEWS BLOCK");
            strcpy(g_dashboard.no_trade_reason_nq, "SPREAD ECARTE - Bloque 30 min suite annonce");
        }

        if (can_trade_nq) {
            strcpy(g_dashboard.bot_action_nq, "SCANNING");
            strcpy(g_dashboard.no_trade_reason_nq, "En attente d'opportunite...");

            // === VETO FLAT NQ: slope < seuil = NO TRADE (sauf exception desequilibre) ===
            // ðŸ”§ 27/01/2026: Seuil adaptatif par session
            // - Asia: 0.005 (plus permissif, volume faible = slope naturellement bas)
            // - London/US: 0.01 (standard)
            float vwap_slope_nq = g_market_live.vwap_slope_nq;
            bool is_asia_nq = (strcmp(g_dashboard.current_session, "Asia") == 0);
            float flat_threshold_nq = is_asia_nq ? 0.005f : 0.01f;
            bool is_flat_nq = (fabs(vwap_slope_nq) < flat_threshold_nq);

            if (is_flat_nq) {
                // Exception DESEQUILIBRE: FLAT mais d_vwap > 60 ticks NQ = OK
                float d_vwap_nq = fabs(current_price_nq - mq_nq.vwap);
                float d_vwap_ticks_nq = d_vwap_nq / CONFIG_NQ.tick_size;

                if (d_vwap_ticks_nq <= 60.0f) {
                    // VETO - FLAT sans desequilibre
                    strcpy(g_dashboard.bot_action_nq, "FLAT VETO");
                    snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                             "VWAP FLAT (slope=%.4f < %.3f) - d_vwap=%.0ft <= 60t", vwap_slope_nq, flat_threshold_nq, d_vwap_ticks_nq);
                    can_trade_nq = false;
                }
                // Si d_vwap > 60t â†’ on laisse passer (desequilibre = retour VWAP probable)
            }

            if (!can_trade_nq) {
                // Skip (FLAT VETO applied)
            } else {
            // ðŸ†• 01/02/2026: Compteur total d'Ã©valuations NQ
            g_dashboard.total_evals_nq++;
            
            // === LAYER 1 (MenthorQ) ===
            Layer1Result l1_nq = ValidateLayer1(sc, mq_nq, current_price_nq, CONFIG_NQ, bn_nq.momentum_score, &bn_nq, false);

            // === LAYER 1B (Rectangles) - Alternative si L1 Ã©choue ===
            RectangleSignal rect_signal_nq = {false, 0, 0, 0, 0, ""};
            bool rectangle_trading_enabled_nq = Input_Rectangle_Trading.GetYesNo();
            if (!l1_nq.passed && rectangle_trading_enabled_nq) {
                rect_signal_nq = DetectRectangleConfluence(sc, bn_nq, mq_nq, current_price_nq, CONFIG_NQ, true);
                if (rect_signal_nq.has_signal) {
                    // Convertir en Layer1Result pour compatibilitÃ©
                    l1_nq.passed = true;
                    l1_nq.direction = rect_signal_nq.direction;
                    l1_nq.confidence = rect_signal_nq.confidence;
                    l1_nq.level_price = rect_signal_nq.rectangle_price;
                    l1_nq.distance_ticks = 0;  // Rectangle = contact direct
                    strncpy(l1_nq.level_name, rect_signal_nq.reason, sizeof(l1_nq.level_name) - 1);
                }
            }

            if (!l1_nq.passed) {
                // Message dÃ©taillÃ©: MenthorQ + Rectangles
                if (rectangle_trading_enabled_nq) {
                    snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                        "L1: MQ=NON, RECT=NON (ColorUp=%.0f ColorDn=%.0f LongDnUp=%.0f)",
                        bn_nq.color_up, bn_nq.color_down, bn_nq.long_down_up);
                } else {
                    strcpy(g_dashboard.no_trade_reason_nq, "L1: Pas de niveau MenthorQ proche (RECT desactive)");
                }
                // ðŸ†• 31/01/2026: DUMP SNAPSHOT POUR ANALYSE 100% REJETS
                DumpBotSnapshot(sc, true, bn_nq, bn_es, mq_nq, mq_es, g_nq_state, "L1_REJECT", g_dashboard.no_trade_reason_nq);
                g_dashboard.l1_reject_nq++;  // ðŸ†• Compteur L1
            } else {
                int direction_nq = l1_nq.direction;

                // ðŸ”§ OPTIMISÃ‰ 25/01/2026: Calculer depth_imbalance et buy/sell % pour NQ
                float depth_imbalance_nq = 0.0f;
                s_MarketDepthEntry bid_entry_nq, ask_entry_nq;
                sc.GetBidMarketDepthEntryAtLevel(bid_entry_nq, 0);
                sc.GetAskMarketDepthEntryAtLevel(ask_entry_nq, 0);
                int total_dom_nq = bid_entry_nq.Quantity + ask_entry_nq.Quantity;
                if (total_dom_nq > 0) {
                    depth_imbalance_nq = (float)(bid_entry_nq.Quantity - ask_entry_nq.Quantity) / total_dom_nq;
                }
                
                // ðŸ”§ 30/01/2026: Utiliser FPBS (Order Flow rÃ©el) NORMALISÃ‰
                float buy_pct_nq, sell_pct_nq;
                float fpbs_total_nq = bn_nq.fpbs_bid_pct + bn_nq.fpbs_ask_pct;
                if (fpbs_total_nq > 0.001f) {
                    // Normaliser les donnÃ©es FPBS pour obtenir de vrais pourcentages
                    buy_pct_nq = bn_nq.fpbs_bid_pct / fpbs_total_nq;
                    sell_pct_nq = bn_nq.fpbs_ask_pct / fpbs_total_nq;
                } else {
                    // Fallback sur color_up/down si FPBS indisponible
                    buy_pct_nq = (bn_nq.color_up > 0) ? 
                        bn_nq.color_up / (bn_nq.color_up + bn_nq.color_down + 0.001f) : 0.5f;
                    sell_pct_nq = 1.0f - buy_pct_nq;
                }
                
                float vwap_slope_nq = g_market_live.vwap_slope_nq;
                
                Layer2Result l2_nq = ValidateLayer2_OrderFlowTrend(direction_nq, bn_nq, bn_es, vix,
                                                     0, buy_pct_nq, CONFIG_NQ, true,
                                                     depth_imbalance_nq, sell_pct_nq, vwap_slope_nq);

                if (!l2_nq.passed) {
                    snprintf(g_dashboard.last_rejected_nq, sizeof(g_dashboard.last_rejected_nq),
                             "L2: %s", l2_nq.reason);
                    snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                             "L2 REJETE: BN=%.2f %s", l2_nq.bn_score, l2_nq.reason);
                    g_dashboard.signals_rejected_nq++;
                    g_dashboard.l2_reject_nq++;  // ðŸ†• Compteur L2
                    // ðŸ†• LOG REJET POUR ANALYSE
                    LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L2",
                                     l2_nq.reason, current_price_nq, l1_nq.level_price, l1_nq.distance_ticks,
                                     vix, l2_nq.bn_score);
                    // ðŸ†• 31/01/2026: DUMP SNAPSHOT COMPLET
                    DumpBotSnapshot(sc, true, bn_nq, bn_es, mq_nq, mq_es, g_nq_state, "L2_REJECT", l2_nq.reason);
                } else {
                    Layer3Result l3_nq = ValidateLayer3(direction_nq, bn_nq, current_price_nq,
                                                         mq_nq, vix, atr_nq,
                                                         g_dashboard.current_session, true);  // NQ

                    if (l3_nq.veto) {
                        snprintf(g_dashboard.last_rejected_nq, sizeof(g_dashboard.last_rejected_nq),
                                 "L3 VETO: %s", l3_nq.veto_reason);
                        snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                 "L3 VETO: %s", l3_nq.veto_reason);
                        g_dashboard.signals_rejected_nq++;
                        g_dashboard.l3_veto_nq++;  // ðŸ†• Compteur L3 VETO
                        // ðŸ†• LOG REJET POUR ANALYSE
                        LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L3_VETO",
                                         l3_nq.veto_reason, current_price_nq, l1_nq.level_price, l1_nq.distance_ticks,
                                         vix, bn_nq.score);
                        // ðŸ†• 31/01/2026: DUMP SNAPSHOT COMPLET
                        DumpBotSnapshot(sc, true, bn_nq, bn_es, mq_nq, mq_es, g_nq_state, "L3_VETO", l3_nq.veto_reason);
                    } else if (!l3_nq.passed) {
                        snprintf(g_dashboard.last_rejected_nq, sizeof(g_dashboard.last_rejected_nq),
                                 "L3: Context=%.2f trop bas", l3_nq.confidence);
                        snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                 "L3 REJETE: Contexte defavorable %s", l3_nq.context);
                        g_dashboard.signals_rejected_nq++;
                        g_dashboard.l3_reject_nq++;  // ðŸ†• Compteur L3 reject
                        // ðŸ†• LOG REJET POUR ANALYSE
                        LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L3",
                                         l3_nq.context, current_price_nq, l1_nq.level_price, l1_nq.distance_ticks,
                                         vix, bn_nq.score);
                        // ðŸ†• 31/01/2026: DUMP SNAPSHOT COMPLET
                        DumpBotSnapshot(sc, true, bn_nq, bn_es, mq_nq, mq_es, g_nq_state, "L3_REJECT", l3_nq.context);
                    } else {
                        // === LAYER 4 NQ (V54: 2 REGLES BACKTEST, 1/2 REQUIS) ===
                        // ðŸ”§ 25/01/2026: Nouvelles rÃ¨gles validÃ©es par backtest rigoureux
                        
                        // ðŸ”§ 01/02/2026: RenommÃ© bn_buy_pct pour Ã©viter confusion avec buy_pct FPBS
                        float buyer_signals_nq = bn_nq.color_up + bn_nq.rotation_up + bn_nq.edge_buy + bn_nq.absorb_bid;
                        float seller_signals_nq = bn_nq.color_down + bn_nq.rotation_down + bn_nq.edge_sell + bn_nq.absorb_ask;
                        float total_signals_nq = buyer_signals_nq + seller_signals_nq;
                        float bn_buy_pct_nq = (total_signals_nq > 0) ? (buyer_signals_nq / total_signals_nq) : 0.5f;
                        float bn_sell_pct_nq = 1.0f - bn_buy_pct_nq;

                        // Edge Buy/Sell pour Edge Dominant
                        float edge_buy_nq = bn_nq.edge_buy + bn_nq.bar_edge_buy;
                        float edge_sell_nq = bn_nq.edge_sell + bn_nq.bar_edge_sell;

                        // Calcul cum_delta proxy depuis rotation (momentum)
                        float cum_delta_proxy_nq = bn_nq.rotation_up - bn_nq.rotation_down;

                        // ðŸ†• 01/02/2026: Passer les vrais paramÃ¨tres pour Score QualitÃ©
                        int trend_bias_nq = GetTrendBias(bn_nq.swing_high, bn_nq.swing_low, current_price_nq);
                        Layer4Result l4_nq = ValidateLayer4(direction_nq, bn_buy_pct_nq, bn_sell_pct_nq,
                                                            edge_buy_nq, edge_sell_nq,
                                                            cum_delta_proxy_nq, bn_nq.score,
                                                            g_market_live.vwap_slope_nq, CONFIG_NQ,
                                                            // ðŸ†• Nouveaux paramÃ¨tres Score QualitÃ©:
                                                            (float)l1_nq.importance_score,  // L1 importance (1-3)
                                                            l1_nq.confidence,               // L1 confiance
                                                            l2_nq.confidence,               // L2 confiance
                                                            l3_nq.confidence,               // L3 confiance
                                                            l2_nq.visual_count,             // Signaux visuels BN
                                                            vix,                            // VIX actuel
                                                            trend_bias_nq);                 // Trend bias

                        if (!l4_nq.passed) {
                            // ðŸ”§ 01/02/2026: Messages mis Ã  jour pour Score QualitÃ©
                            snprintf(g_dashboard.last_rejected_nq, sizeof(g_dashboard.last_rejected_nq),
                                     "L4: Grade=%c Score=%.0f<55", l4_nq.grade, l4_nq.quality_score);
                            snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                     "L4 REJETE: Grade %c (Score %.0f/100, combo=%d)",
                                     l4_nq.grade, l4_nq.quality_score, l4_nq.combo_aligned);
                            g_dashboard.signals_rejected_nq++;
                            g_dashboard.l4_reject_nq++;  // ðŸ†• Compteur L4
                            char l4_nq_reason[64];
                            snprintf(l4_nq_reason, sizeof(l4_nq_reason), "Grade %c Score %.0f<55", l4_nq.grade, l4_nq.quality_score);
                            LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L4",
                                             l4_nq_reason, current_price_nq, l1_nq.level_price, l1_nq.distance_ticks,
                                             vix, bn_nq.score);
                            // ðŸ†• 31/01/2026: DUMP SNAPSHOT COMPLET
                            DumpBotSnapshot(sc, true, bn_nq, bn_es, mq_nq, mq_es, g_nq_state, "L4_REJECT", l4_nq_reason);
                        } else {
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ”§ 27/01/2026: FILTRES RENFORCÃ‰S NQ - "MEILLEURS SETUPS ONLY"
                            // ProblÃ¨me identifiÃ©: trades Ã  13% L3 et 41% L2 = MAUVAIS!
                            // Nouveau: exiger des signaux de QUALITÃ‰ pas juste "passables"
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ”§ 27/01/2026 16h: SEUILS Ã‰QUILIBRÃ‰S NQ
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            float min_l1_conf_nq = 0.30f;  // NQ: 30% minimum (Ã©tait 32%)
                            float min_l2_conf_nq = 0.38f;  // NQ: 38% minimum (Ã©tait 45% = trop strict!)
                            // ðŸ”§ 01/02/2026: HarmonisÃ© avec seuil L3 (0.15 dans MIA_Layers.h)
                            float min_l3_conf_nq = 0.15f;  // NQ: 15% minimum (alignÃ© sur seuil L3)
                            float min_confluence_nq = 0.40f;  // Confluence globale: 40% min (Ã©tait 48%)
                            
                            // Calcul confluence globale
                            float overall_conf_nq = (l1_nq.confidence + l2_nq.confidence + l3_nq.confidence + bn_nq.score) / 4.0f;
                            
                            if (l1_nq.confidence < min_l1_conf_nq) {
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "L1 REJET: Conf=%.1f%% < %.0f%% (signal trop faible)", 
                                         l1_nq.confidence * 100, min_l1_conf_nq * 100);
                                g_dashboard.signals_rejected_nq++;
                                g_dashboard.min_reject_nq++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L1_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else if (l2_nq.confidence < min_l2_conf_nq) {
                                // ðŸ†• 27/01/2026: Nouveau filtre L2!
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "L2 REJET: Conf=%.1f%% < %.0f%% (BN/corrÃ©lation trop faible)", 
                                         l2_nq.confidence * 100, min_l2_conf_nq * 100);
                                g_dashboard.signals_rejected_nq++;
                                g_dashboard.min_reject_nq++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L2_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else if (l3_nq.confidence < min_l3_conf_nq) {
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "L3 REJET: Conf=%.1f%% < %.0f%% (contexte trop faible)", 
                                         l3_nq.confidence * 100, min_l3_conf_nq * 100);
                                g_dashboard.signals_rejected_nq++;
                                g_dashboard.min_reject_nq++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L3_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else if (bn_nq.score < 0.40f) {  // BN: 40% minimum
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "BN REJET: Score=%.1f%% < 40%% (BN trop faible)", bn_nq.score * 100);
                                g_dashboard.signals_rejected_nq++;
                                g_dashboard.min_reject_nq++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "BN_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else if (overall_conf_nq < min_confluence_nq) {
                                // ðŸ†• 27/01/2026: Nouveau filtre confluence globale!
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "CONF REJET: Global=%.1f%% < %.0f%% (L1=%.0f L2=%.0f L3=%.0f BN=%.0f)", 
                                         overall_conf_nq * 100, min_confluence_nq * 100,
                                         l1_nq.confidence * 100, l2_nq.confidence * 100, 
                                         l3_nq.confidence * 100, bn_nq.score * 100);
                                g_dashboard.signals_rejected_nq++;
                                g_dashboard.min_reject_nq++;  // ðŸ†• Compteur MIN
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "CONF_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else {
                            // ðŸŽ¯ 26/01/2026: QUICK WIN #2 - RECTANGLE BONUS +5% NQ
                            float l1_confidence_bonus_nq = l1_nq.confidence;
                            bool has_rectangle_nq = (direction_nq == 1) ?
                                (bn_nq.price_in_edge_rect_buy || bn_nq.num_edge_rect_buy > 0) :
                                (bn_nq.price_in_edge_rect_sell || bn_nq.num_edge_rect_sell > 0);
                            
                            if (has_rectangle_nq) {
                                l1_confidence_bonus_nq *= 1.05f;  // +5% bonus
                            }
                            
                            // === SIGNAL VALIDÃ‰ - VERIFIER R:R ===
                            // ðŸ†• 25/01/2026: Passer le tracker persistant pour SL/TP intelligent
                            SLTPResult sltp_nq = CalculateProtectedSLTP(direction_nq, current_price_nq, mq_nq, bn_nq, CONFIG_NQ, &g_ext_tracker_nq, &cp_nq);

                            // ðŸ†• VETO si obstacle bloque le R:R
                            if (!sltp_nq.is_valid) {
                                strcpy(g_dashboard.bot_action_nq, "VETO_RR");
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "NQ: %s", sltp_nq.tp_based_on);
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT",
                                                  "SLTP", sltp_nq.tp_based_on, current_price_nq, 0, 0, vix, bn_nq.score);
                            } else {

                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ”§ 28/01/2026: HARD LIMIT SL/TP - TOUJOURS APPLIQUER!
                            // Bug: SL de 158 ticks au lieu de max 40!
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            float tick_size_nq = CONFIG_NQ.tick_size;
                            float max_sl_dist_nq = CONFIG_NQ.sl_max_ticks * tick_size_nq;
                            float max_tp_dist_nq = CONFIG_NQ.tp_max_ticks * tick_size_nq;
                            float current_sl_dist_nq = fabs(sltp_nq.sl_price - current_price_nq);
                            float current_tp_dist_nq = fabs(sltp_nq.tp_price - current_price_nq);
                            
                            // FORCER SL max
                            if (current_sl_dist_nq > max_sl_dist_nq) {
                                if (direction_nq == 1) {
                                    sltp_nq.sl_price = current_price_nq - max_sl_dist_nq;
                                } else {
                                    sltp_nq.sl_price = current_price_nq + max_sl_dist_nq;
                                }
                                sltp_nq.sl_ticks = CONFIG_NQ.sl_max_ticks;
                                strncpy(sltp_nq.sl_based_on, "MAX_HARD_LIMIT", sizeof(sltp_nq.sl_based_on));
                            }
                            
                            // FORCER TP max
                            if (current_tp_dist_nq > max_tp_dist_nq) {
                                if (direction_nq == 1) {
                                    sltp_nq.tp_price = current_price_nq + max_tp_dist_nq;
                                } else {
                                    sltp_nq.tp_price = current_price_nq - max_tp_dist_nq;
                                }
                                sltp_nq.tp_ticks = CONFIG_NQ.tp_max_ticks;
                                strncpy(sltp_nq.tp_based_on, "MAX_HARD_LIMIT", sizeof(sltp_nq.tp_based_on));
                            }

                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ†• 01/02/2026: RÃ‰GIME MARCHÃ‰ MULTI-FACTEURS PRO (NQ)
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            RegimeResult regime_nq = CalculateMarketRegime(
                                g_market_live.vwap_slope_nq,
                                atr_nq,
                                atr_nq * 0.85f, // ATR avg approximation
                                g_market_live.vix_regime,
                                bn_nq.cvd_slope,
                                bn_nq.swing_high,
                                bn_nq.swing_low,
                                current_price_nq,
                                true   // ðŸ†• is_nq = true (NQ)
                            );
                            
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // ðŸ†• 01/02/2026: APPLIQUER L4 + RÃ‰GIME TP MULTIPLIER (NQ)
                            // âš ï¸ SEULEMENT si TP n'est PAS basÃ© sur un obstacle!
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            float tp_distance_nq = fabs(sltp_nq.tp_price - current_price_nq);
                            float tp_mult_total_nq = 1.0f;
                            
                            // VÃ©rifier si TP est basÃ© sur un obstacle
                            bool tp_based_on_obstacle_nq = (strstr(sltp_nq.tp_based_on, "BEFORE_") != nullptr ||
                                                            strstr(sltp_nq.tp_based_on, "OBSTACLE") != nullptr ||
                                                            strstr(sltp_nq.tp_based_on, "RECT_") != nullptr ||
                                                            strstr(sltp_nq.tp_based_on, "GAMMA") != nullptr ||
                                                            strstr(sltp_nq.tp_based_on, "CALL") != nullptr ||
                                                            strstr(sltp_nq.tp_based_on, "PUT") != nullptr);
                            
                            if (!tp_based_on_obstacle_nq) {
                                // TP LIBRE â†’ On peut ajuster
                                if (l4_nq.tp_multiplier > 1.0f) {
                                    tp_mult_total_nq = l4_nq.tp_multiplier;
                                }
                                tp_mult_total_nq *= regime_nq.tp_multiplier;
                                
                                // LIMITE: Max +50%, Min -30%
                                if (tp_mult_total_nq > 1.50f) tp_mult_total_nq = 1.50f;
                                if (tp_mult_total_nq < 0.70f) tp_mult_total_nq = 0.70f;
                                
                                tp_distance_nq *= tp_mult_total_nq;
                                
                                // Respecter le hard limit
                                max_tp_dist_nq = CONFIG_NQ.tp_max_ticks * tick_size_nq;
                                if (tp_distance_nq > max_tp_dist_nq) tp_distance_nq = max_tp_dist_nq;
                                
                                if (direction_nq == 1) {
                                    sltp_nq.tp_price = current_price_nq + tp_distance_nq;
                                } else {
                                    sltp_nq.tp_price = current_price_nq - tp_distance_nq;
                                }
                                sltp_nq.tp_ticks = (int)(tp_distance_nq / tick_size_nq);
                            }
                            // Si obstacle: garder le TP original
                            
                            // Log L4 + RÃ©gime
                            char regime_note_nq[128];
                            snprintf(regime_note_nq, sizeof(regime_note_nq), 
                                     "ðŸŽ¯ NQ L4=%c + %s â†’ TPx%.2f %s", 
                                     l4_nq.grade, GetRegimeName(regime_nq.regime),
                                     tp_mult_total_nq, tp_based_on_obstacle_nq ? "(obstacle=kept)" : "(applied)");
                            sc.AddMessageToLog(regime_note_nq, 0);
                            
                            // ðŸ†• Propager le flag trailing au state (pour UpdateTrailingStop)
                            g_nq_state.trailing_allowed = regime_nq.trailing_enabled;

                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // DÃ‰TECTION TRADE HAUTE QUALITÃ‰ NQ LEGACY (risque augmentÃ©)
                            // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                            // 01/03/2026: Flag VETO si HQ casse le R:R
                            bool nq_hq_rr_veto = false;

                            int visual_count_nq = 0;
                            if (bn_nq.edge_buy > 0 || bn_nq.edge_sell > 0) visual_count_nq++;
                            if (bn_nq.color_up > 10 || bn_nq.color_down > 10) visual_count_nq++;
                            if (bn_nq.long_down_up > 0 || bn_nq.long_up_down > 0) visual_count_nq++;
                            if (bn_nq.num_edge_rect_buy > 0 || bn_nq.num_edge_rect_sell > 0) visual_count_nq++;
                            if (bn_nq.absorb_bid > 0 || bn_nq.absorb_ask > 0) visual_count_nq++;

                            HighQualityResult hq_nq = DetectHighQualityTrade(
                                direction_nq, bn_nq, l1_nq.importance_score,
                                visual_count_nq, !sltp_nq.is_valid
                            );

                            // ðŸ”§ 01/02/2026: HQ ne modifie plus le TP (dÃ©jÃ  gÃ©rÃ© par L4+RÃ©gime avec cap!)
                            // HQ modifie SEULEMENT le SL
                            if (hq_nq.is_high_quality) {
                                // SL lÃ©gÃ¨rement plus large pour trades haute qualitÃ©
                                float sl_distance_nq = fabs(sltp_nq.sl_price - current_price_nq);
                                sl_distance_nq *= hq_nq.sl_multiplier;
                                if (direction_nq == 1) {
                                    sltp_nq.sl_price = current_price_nq - sl_distance_nq;
                                } else {
                                    sltp_nq.sl_price = current_price_nq + sl_distance_nq;
                                }

                                // Limiter SL max
                                if (fabs(sltp_nq.sl_price - current_price_nq) > CONFIG_NQ.sl_max_ticks * tick_size_nq) {
                                    if (direction_nq == 1) {
                                        sltp_nq.sl_price = current_price_nq - CONFIG_NQ.sl_max_ticks * tick_size_nq;
                                    } else {
                                        sltp_nq.sl_price = current_price_nq + CONFIG_NQ.sl_max_ticks * tick_size_nq;
                                    }
                                }

                                // Recalculer SL ticks
                                sltp_nq.sl_ticks = (int)(fabs(sltp_nq.sl_price - current_price_nq) / tick_size_nq);

                                // 01/03/2026: REVALIDATION R:R APRES AJUSTEMENT HQ NQ
                                if (sltp_nq.sl_ticks > 0) {
                                    sltp_nq.rr_ratio = (float)sltp_nq.tp_ticks / (float)sltp_nq.sl_ticks;
                                    if (sltp_nq.rr_ratio < CONFIG_NQ.min_rr_ratio) {
                                        char rr_msg_nq[128];
                                        snprintf(rr_msg_nq, sizeof(rr_msg_nq),
                                                 "HQ R:R VETO NQ: %.2f < %.2f (SL=%d TP=%d apres HQ x%.2f)",
                                                 sltp_nq.rr_ratio, CONFIG_NQ.min_rr_ratio,
                                                 sltp_nq.sl_ticks, sltp_nq.tp_ticks, hq_nq.sl_multiplier);
                                        sc.AddMessageToLog(rr_msg_nq, 0);
                                        g_dashboard.sltp_reject_nq++;
                                        nq_hq_rr_veto = true;
                                    }
                                }

                                // Log HQ (sans modification TP)
                                char hq_log_nq[128];
                                snprintf(hq_log_nq, sizeof(hq_log_nq), "â­ NQ HQ: %s (SL Ã©largi x%.2f)", 
                                         hq_nq.reason, hq_nq.sl_multiplier);
                                sc.AddMessageToLog(hq_log_nq, 0);
                            }

                            // ðŸ†• Calculer ancre BN avant d'entrer
                            float bn_anchor_nq = CalculateBNAnchor(direction_nq, current_price_nq, bn_nq, CONFIG_NQ.tick_size);

                            // ðŸ†• Stocker donnÃ©es Discord pour notification (Migration StateManager)
                            UPDATE_NQ_STATE([&](BotState& state) {
                                state.discord_bn_score = bn_nq.score;
                                state.discord_l1_conf = l1_nq.confidence;
                                state.discord_l2_conf = l2_nq.confidence;
                                state.discord_l3_conf = l3_nq.confidence;
                                state.discord_l4_combo = l4_nq.combo_aligned;
                                state.discord_vwap_slope = g_market_live.vwap_slope_nq;
                                state.discord_is_rectangle = rect_signal_nq.has_signal;
                            });

                            // ðŸ†• TRADE WHY JOURNAL - Log avant envoi ordre NQ
                            TradeWhy why_nq = BuildTradeWhy(sc, "NQ", direction_nq, current_price_nq,
                                                           l1_nq, l2_nq, l3_nq, l4_nq, bn_nq, mq_nq,
                                                           vix, bn_anchor_nq, rect_signal_nq.has_signal,
                                                           rect_signal_nq, CONFIG_NQ, "PENDING");
                            why_nq.sl_price = sltp_nq.sl_price;
                            why_nq.tp_price = sltp_nq.tp_price;
                            
                            // ðŸ†• 01/02/2026: POSITION SIZING DYNAMIQUE NQ + RÃ‰GIME
                            float dd_pct_nq = 0.0f;
                            if (g_nq_state.pnl_today < 0) {
                                dd_pct_nq = fabs(g_nq_state.pnl_today) / ACCOUNT_CAPITAL_BASE;  // 01/03/2026: Externalisé
                            }
                            int base_qty_nq = CalculatePositionSize(true, l4_nq.grade, g_market_live.vix_regime, dd_pct_nq);
                            why_nq.qty = (int)(base_qty_nq * regime_nq.size_multiplier);
                            if (why_nq.qty < 1) why_nq.qty = 1;
                            
                            LogTradeWhy(sc, why_nq, CONFIG_NQ);

                            strcpy(g_dashboard.bot_action_nq, "ENTERING");
                            strcpy(g_dashboard.no_trade_reason_nq, "SIGNAL VALIDE - Entree en cours!");


                            // 01/03/2026: GUARD - Si HQ a casse le R:R, ne pas trader
                            if (nq_hq_rr_veto) {
                                strcpy(g_dashboard.bot_action_nq, "VETO_HQ_RR");
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "NQ HQ R:R %.2f < %.2f apres SL elargi", sltp_nq.rr_ratio, CONFIG_NQ.min_rr_ratio);
                                sc.AddMessageToLog("NQ SKIP: R:R invalide apres HQ SL expansion", 0);
                            } else {
                            // Envoyer ordre (va dÃ©terminer execution_mode)
                            // ðŸ†• 01/02/2026: Passer la quantitÃ© dynamique
                            bool order_sent_nq = SendBracketOrder(sc, direction_nq, current_price_nq,
                                           sltp_nq.sl_price, sltp_nq.tp_price, g_nq_state, bn_anchor_nq, why_nq.qty);

                            // ðŸ†• Mettre Ã  jour execution_mode dans TradeWhy NQ (Migration StateManager)
                            if (order_sent_nq) {
                                BotState nq_exec = GET_NQ_STATE();
                                if (nq_exec.pending_limit_order) {
                                    strncpy(why_nq.execution_mode, "PENDING_LIMIT", sizeof(why_nq.execution_mode) - 1);
                                } else {
                                    strncpy(why_nq.execution_mode, "IMMEDIATE", sizeof(why_nq.execution_mode) - 1);
                                }
                                LogTradeWhy(sc, why_nq, CONFIG_NQ);
                                // ðŸ†• 31/01/2026: DUMP SNAPSHOT QUAND TRADE ACCEPTÃ‰
                                DumpBotSnapshot(sc, true, bn_nq, bn_es, mq_nq, mq_es, g_nq_state, "ORDER_SENT", "");
                                
                                // ðŸ†• 01/02/2026: JOURNAL DE TRADE COMPLET NQ
                                TradeDecisionLog tdlog_nq = CreateDecisionLog(sc, true, direction_nq, current_price_nq);
                                tdlog_nq.l1_passed = l1_nq.passed;
                                tdlog_nq.l1_confidence = l1_nq.confidence;
                                snprintf(tdlog_nq.l1_reason, sizeof(tdlog_nq.l1_reason), "%s@%.2f", l1_nq.level_name, l1_nq.level_price);
                                tdlog_nq.l2_passed = l2_nq.passed;
                                tdlog_nq.l2_confidence = l2_nq.confidence;
                                snprintf(tdlog_nq.l2_reason, sizeof(tdlog_nq.l2_reason), "OFTrend:%.2f", l2_nq.confidence);
                                tdlog_nq.l3_passed = l3_nq.passed;
                                tdlog_nq.l3_veto = false;
                                tdlog_nq.l3_confidence = l3_nq.confidence;
                                strncpy(tdlog_nq.l3_reason, l3_nq.veto_reason, sizeof(tdlog_nq.l3_reason) - 1);
                                tdlog_nq.l4_passed = l4_nq.passed;
                                tdlog_nq.l4_grade = l4_nq.grade;
                                tdlog_nq.l4_quality = l4_nq.quality_score;
                                snprintf(tdlog_nq.l4_reason, sizeof(tdlog_nq.l4_reason), "combo=%d", l4_nq.combo_aligned ? 1 : 0);
                                strncpy(tdlog_nq.regime, GetRegimeName(regime_nq.regime), sizeof(tdlog_nq.regime) - 1);
                                tdlog_nq.regime_score = regime_nq.score;
                                tdlog_nq.size_mult = regime_nq.size_multiplier;
                                tdlog_nq.tp_mult = tp_mult_total_nq;
                                tdlog_nq.trailing_allowed = regime_nq.trailing_enabled;
                                tdlog_nq.sl_price = sltp_nq.sl_price;
                                tdlog_nq.tp_price = sltp_nq.tp_price;
                                tdlog_nq.sl_ticks = sltp_nq.sl_ticks;
                                tdlog_nq.tp_ticks = sltp_nq.tp_ticks;
                                strncpy(tdlog_nq.tp_based_on, sltp_nq.tp_based_on, sizeof(tdlog_nq.tp_based_on) - 1);
                                tdlog_nq.trade_taken = true;
                                snprintf(tdlog_nq.final_reason, sizeof(tdlog_nq.final_reason), 
                                         "TRADE_TAKEN: L4=%c Regime=%s Qty=%d", l4_nq.grade, GetRegimeName(regime_nq.regime), why_nq.qty);
                                tdlog_nq.qty = why_nq.qty;
                                LogTradeDecision(sc, tdlog_nq);
                            }
                            }  // 01/03/2026: Fin else nq_hq_rr_veto guard
                            }  // Fin else SLTP valid NQ
                            }  // Fin else (L1/L3/BN ok) - Quick Wins NQ
                        }  // Fin else L4.passed NQ
                    }  // Fin else L3 chain NQ (veto/passed/else)
                }  // Fin else L2.passed NQ
            }  // Fin else L1.passed NQ
            }  // Fin else FLAT VETO NQ
        }
        CheckOrderTimeout(sc, g_nq_state);
    }

    // === SAUVEGARDER DASHBOARD ===
    SaveDashboard(sc);

    // ðŸ†• AFFICHER DASHBOARD SUR LE GRAPHIQUE
    DrawDashboardOnChart(sc);
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// FIN DU FICHIER
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
