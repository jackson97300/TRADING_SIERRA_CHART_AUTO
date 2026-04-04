#pragma once
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// MIA_DataReader.h - SECTIONS 5-6.4: COLLECTE DONNÃ‰ES BATAILLE NAVALE ET MENTHORQ
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 1261-2606)
// Refactoring: 31/01/2026
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

#include "MIA_Utils.h"
#include "MIA_StudyConfig.h"  // ðŸ†• 31/01/2026: Study IDs depuis JSON

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// SECTION 5: COLLECTE DONNÃ‰ES BATAILLE NAVALE
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

inline void CollectBN_Data(SCStudyInterfaceRef sc, int chart_footprint, int chart_barres, BN_Data& bn, bool is_nq) {
    // ðŸ”§ FIX CVD SLOPE: Sauvegarder prev_cvd AVANT le memset (utilise persistent vars)
    // Index 100 pour ES, 101 pour NQ
    int cvd_persist_idx = is_nq ? 101 : 100;
    float saved_prev_cvd = sc.GetPersistentFloat(cvd_persist_idx);

    // Reset
    memset(&bn, 0, sizeof(BN_Data));

    // ðŸ”§ FIX CVD SLOPE: Restaurer prev_cvd APRÃˆS le memset
    bn.prev_cvd = saved_prev_cvd;

    SCGraphData footprint_data;
    SCGraphData barres_data;

    // Collecter depuis Footprint
    sc.GetChartBaseData(chart_footprint, footprint_data);

    // Collecter depuis Barres
    sc.GetChartBaseData(chart_barres, barres_data);

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 31/01/2026: STUDY IDs DEPUIS JSON (study_mapping.json)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    const char* fp_key = is_nq ? "NQ_FOOTPRINT" : "ES_FOOTPRINT";
    const char* bar_key = is_nq ? "NQ_BARRES" : "ES_BARRES";

    // --- ALIASES pour compatibilitÃ© avec le code existant ---
    int STUDY_EDGE_BUY = STUDY_ID(fp_key, "EDGE_BUY");
    int STUDY_EDGE_SELL = STUDY_ID(fp_key, "EDGE_SELL");
    int STUDY_COLOR_UP = STUDY_ID(fp_key, "COLOR_UP");
    int STUDY_COLOR_DOWN = STUDY_ID(fp_key, "COLOR_DOWN");
    int STUDY_ABSORB_ASK = STUDY_ID(fp_key, "ABSORB_ASK");
    int STUDY_ABSORB_BID = STUDY_ID(fp_key, "ABSORB_BID");
    int STUDY_ROTATION_UP = STUDY_ID(fp_key, "ROTATION_UP");
    int STUDY_ROTATION_DOWN = STUDY_ID(fp_key, "ROTATION_DOWN");
    int STUDY_LONG_DOWN_UP = STUDY_ID(bar_key, "LONG_DOWN_UP");
    int STUDY_LONG_UP_DOWN = STUDY_ID(bar_key, "LONG_UP_DOWN");

    // IDs spÃ©cifiques selon symbole
    int STUDY_DOUBLE_ASK = -1, STUDY_DOUBLE_BID = -1;
    int STUDY_TRIPLE_ASK = -1, STUDY_TRIPLE_BID = -1;
    int STUDY_VOLUME_UP = -1, STUDY_VOLUME_DOWN = -1;

    if (is_nq) {
        STUDY_TRIPLE_ASK = STUDY_ID(fp_key, "TRIPLE_ASK");
        STUDY_TRIPLE_BID = STUDY_ID(fp_key, "TRIPLE_BID");
    } else {
        STUDY_DOUBLE_ASK = STUDY_ID(fp_key, "DOUBLE_ASK");
        STUDY_DOUBLE_BID = STUDY_ID(fp_key, "DOUBLE_BID");
    }

    // Autres IDs depuis JSON
    int FP_FPBS = STUDY_ID(fp_key, "FPBS");
    int FP_ASK_100 = STUDY_ID(fp_key, "ASK_100");
    int FP_BID_100 = STUDY_ID(fp_key, "BID_100");
    int FP_ASK_400 = STUDY_ID(fp_key, "ASK_400");
    int FP_BID_400 = STUDY_ID(fp_key, "BID_400");
    int FP_ASK_1000 = STUDY_ID(fp_key, "ASK_1000");
    int FP_BID_1000 = STUDY_ID(fp_key, "BID_1000");

    int BAR_EDGE_BUY = STUDY_ID(bar_key, "EDGE_BUY");
    int BAR_EDGE_SELL = STUDY_ID(bar_key, "EDGE_SELL");
    int BAR_VWAP = STUDY_ID(bar_key, "VWAP");
    int BAR_COLOR_UP = STUDY_ID(bar_key, "COLOR_UP");
    int BAR_COLOR_DOWN = STUDY_ID(bar_key, "COLOR_DOWN");

    // IDs spÃ©cifiques selon symbole pour volumes/ordres
    int FP_VOLUME_UP = -1, FP_VOLUME_DOWN = -1;
    int FP_ASK_10 = -1, FP_BID_10 = -1, FP_ASK_30 = -1, FP_BID_30 = -1;
    int FP_ASK_150 = -1, FP_BID_150 = -1;
    int FP_CLUSTER_VOL = -1;

    // IDs pour rectangles tradables (LONG_UP_BAR, LONG_DOWN_BAR)
    int BAR_LONG_UP_BAR = STUDY_ID(bar_key, "LONG_UP_BAR");
    int BAR_LONG_DOWN_BAR = STUDY_ID(bar_key, "LONG_DOWN_BAR");

    if (is_nq) {
        FP_VOLUME_UP = STUDY_ID(fp_key, "VOLUME_UP");
        FP_VOLUME_DOWN = STUDY_ID(fp_key, "VOLUME_DOWN");
        FP_ASK_10 = STUDY_ID(fp_key, "ASK_10");
        FP_BID_10 = STUDY_ID(fp_key, "BID_10");
        FP_ASK_30 = STUDY_ID(fp_key, "ASK_30");
        FP_BID_30 = STUDY_ID(fp_key, "BID_30");
        FP_CLUSTER_VOL = STUDY_ID(fp_key, "CLUSTER_VOL");
    } else {
        FP_ASK_150 = STUDY_ID(fp_key, "ASK_150");
        FP_BID_150 = STUDY_ID(fp_key, "BID_150");
        FP_CLUSTER_VOL = STUDY_ID(fp_key, "CLUSTER_VOL");
    }

    // Subgraphs FPBS (identiques ES et NQ)
    const int FPBS_SG_DELTA = 0;
    const int FPBS_SG_DELTA_DAY = 9;
    const int FPBS_SG_CVD = 18;
    const int FPBS_SG_POC_VOL = 19;
    const int FPBS_SG_POC_PRICE = 41;
    const int FPBS_SG_ASK_PCT = 16;
    const int FPBS_SG_BID_PCT = 17;


    // Lecture Footprint (dernier index)
    int last_idx = footprint_data[0].GetArraySize() - 1;
    if (last_idx < 0) return;

    // Edge Buy/Sell - Subgraph 0 = "Trigger 0" (PRIX du premier niveau edge actif)
    // ðŸ”§ 30/01/2026: IMPORTANT - EDGE ZONES n'ont PAS de subgraph "Count"!
    // - sg0-46 = Triggers = PRIX des niveaux edge actifs
    // - sg48-57 = Rectangles (bottom/top pairs)
    // - Il n'y a PAS de sg58 "Count of Alerts" pour EDGE ZONES
    // DONC: edge_buy/edge_sell stockent le PRIX du niveau (utile pour SL/TP)
    //       Pour le COUNT, utiliser num_edge_rect_buy/sell calculÃ© plus bas
    bn.edge_buy = ReadStudyValue(sc, chart_footprint, STUDY_EDGE_BUY, 0);   // Trigger 0 = prix niveau
    bn.edge_sell = ReadStudyValue(sc, chart_footprint, STUDY_EDGE_SELL, 0); // Trigger 0 = prix niveau

    // Color Up/Down
    // Color Up/Down - Subgraph 2 = "Sum of Alerts" (COUNT)
    bn.color_up = ReadStudyValue(sc, chart_footprint, STUDY_COLOR_UP, 2);
    bn.color_down = ReadStudyValue(sc, chart_footprint, STUDY_COLOR_DOWN, 2);

    // Absorb - Subgraph 2 = "Sum of Alerts" (COUNT)
    bn.absorb_ask = ReadStudyValue(sc, chart_footprint, STUDY_ABSORB_ASK, 2);
    bn.absorb_bid = ReadStudyValue(sc, chart_footprint, STUDY_ABSORB_BID, 2);

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // NOTE: Pour NQ, TRIPLE/VOLUME/ROTATION sont sur FOOTPRINT (Chart 2)
    //       Pour ES, DOUBLE/ROTATION sont sur FOOTPRINT (Chart 1)
    //       Les patterns V/^ (LONG_DOWN_UP, LONG_UP_DOWN) sont sur les BARRES
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    if (is_nq) {
        // === NQ FOOTPRINT (Chart 39) ===
        // ðŸ”§ 27/01/2026: FIX - Subgraph 2 = COUNT (utilisÃ© dans buyer/seller_strength)
        bn.triple_ask = ReadStudyValue(sc, chart_footprint, STUDY_TRIPLE_ASK, 2);
        bn.triple_bid = ReadStudyValue(sc, chart_footprint, STUDY_TRIPLE_BID, 2);
        bn.volume_up = ReadStudyValue(sc, chart_footprint, FP_VOLUME_UP, 2);  // ðŸ”§ FIX: subgraph 2 = Sum of Alerts (pas 0 = Color Bar/prix)
        bn.volume_down = ReadStudyValue(sc, chart_footprint, FP_VOLUME_DOWN, 2);
        bn.rotation_up = ReadStudyValue(sc, chart_footprint, STUDY_ROTATION_UP, 2);  // ðŸ”§ FIX: subgraph 2 = Sum of Alerts
        bn.rotation_down = ReadStudyValue(sc, chart_footprint, STUDY_ROTATION_DOWN, 2);

        // ðŸ†• NQ: Ordres granulaires (+10, +30, +100)
        bn.ask_10 = ReadStudyValue(sc, chart_footprint, FP_ASK_10, 0);
        bn.bid_10 = ReadStudyValue(sc, chart_footprint, FP_BID_10, 0);
        bn.ask_30 = ReadStudyValue(sc, chart_footprint, FP_ASK_30, 0);
        bn.bid_30 = ReadStudyValue(sc, chart_footprint, FP_BID_30, 0);
        bn.ask_100 = ReadStudyValue(sc, chart_footprint, FP_ASK_100, 0);
        bn.bid_100 = ReadStudyValue(sc, chart_footprint, FP_BID_100, 0);
        bn.cluster_vol = ReadStudyValue(sc, chart_footprint, FP_CLUSTER_VOL, 0);

        // NQ: FPBS basique (subgraph 16=Ask%, 17=Bid%)
        bn.fpbs_ask_pct = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_ASK_PCT);
        bn.fpbs_bid_pct = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_BID_PCT);

        // ðŸ†• NQ: FPBS avancÃ© (Delta, CVD, POC)
        bn.fpbs_delta = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_DELTA);
        bn.fpbs_delta_day = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_DELTA_DAY);
        bn.fpbs_cvd = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_CVD);
        bn.fpbs_poc = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_POC_PRICE);  // ðŸ”§ CORRIGÃ‰: POC PRICE, pas VOLUME!

        // === NQ BARRES (Chart 23) ===
        // ðŸ”§ 30/01/2026: FIX - sg2 = "Sum of Alerts" (COUNT), pas sg0 = prix!
        bn.long_down_up = ReadStudyValue(sc, chart_barres, STUDY_LONG_DOWN_UP, 2);  // COUNT of patterns
        bn.long_up_down = ReadStudyValue(sc, chart_barres, STUDY_LONG_UP_DOWN, 2);  // COUNT of patterns
        // ðŸ”§ 30/01/2026: FIX - Subgraphs corrigÃ©s depuis study_inventory
        // [AV] COLOR = sg2 ("Sum of Alerts")
        // EDGE ZONES = sg58 ("Count of Alerts") - PAS sg2!
        bn.bar_color_up = ReadStudyValue(sc, chart_barres, BAR_COLOR_UP, 2);
        bn.bar_color_down = ReadStudyValue(sc, chart_barres, BAR_COLOR_DOWN, 2);
        bn.bar_edge_buy = ReadStudyValue(sc, chart_barres, BAR_EDGE_BUY, 58);   // ðŸ”§ FIX: sg58!
        bn.bar_edge_sell = ReadStudyValue(sc, chart_barres, BAR_EDGE_SELL, 58); // ðŸ”§ FIX: sg58!

    } else {
        // === ES FOOTPRINT (Chart 28) ===
        // ðŸ”§ 27/01/2026: FIX - Subgraph 2 = COUNT (utilisÃ© dans buyer/seller_strength)
        bn.double_ask = ReadStudyValue(sc, chart_footprint, STUDY_DOUBLE_ASK, 2);
        bn.double_bid = ReadStudyValue(sc, chart_footprint, STUDY_DOUBLE_BID, 2);
        bn.rotation_up = ReadStudyValue(sc, chart_footprint, STUDY_ROTATION_UP, 2);  // ðŸ”§ FIX: subgraph 2 = Sum of Alerts
        bn.rotation_down = ReadStudyValue(sc, chart_footprint, STUDY_ROTATION_DOWN, 2);

        // ES: Gros ordres (seuils institutionnels)
        bn.ask_100 = ReadStudyValue(sc, chart_footprint, FP_ASK_100, 0);
        bn.bid_100 = ReadStudyValue(sc, chart_footprint, FP_BID_100, 0);
        bn.ask_150 = ReadStudyValue(sc, chart_footprint, FP_ASK_150, 0);
        bn.bid_150 = ReadStudyValue(sc, chart_footprint, FP_BID_150, 0);
        bn.ask_400 = ReadStudyValue(sc, chart_footprint, FP_ASK_400, 0);
        bn.bid_400 = ReadStudyValue(sc, chart_footprint, FP_BID_400, 0);
        bn.ask_1000 = ReadStudyValue(sc, chart_footprint, FP_ASK_1000, 0);
        bn.bid_1000 = ReadStudyValue(sc, chart_footprint, FP_BID_1000, 0);
        bn.cluster_vol = ReadStudyValue(sc, chart_footprint, FP_CLUSTER_VOL, 0);

        // ES: Pas de +10/+30 (seulement NQ a ces niveaux granulaires)
        bn.ask_10 = 0;
        bn.bid_10 = 0;
        bn.ask_30 = 0;
        bn.bid_30 = 0;

        // ES: FPBS basique (subgraph 16=Ask%, 17=Bid%)
        bn.fpbs_ask_pct = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_ASK_PCT);
        bn.fpbs_bid_pct = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_BID_PCT);

        // ðŸ†• ES: FPBS avancÃ© (Delta, CVD, POC)
        bn.fpbs_delta = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_DELTA);
        bn.fpbs_delta_day = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_DELTA_DAY);
        bn.fpbs_cvd = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_CVD);
        bn.fpbs_poc = ReadStudyValue(sc, chart_footprint, FP_FPBS, FPBS_SG_POC_PRICE);  // ðŸ”§ CORRIGÃ‰: POC PRICE, pas VOLUME!

        // === ES BARRES (Chart 25) ===
        // ðŸ”§ 30/01/2026: FIX - sg2 = "Sum of Alerts" (COUNT), pas sg0 = prix!
        bn.long_down_up = ReadStudyValue(sc, chart_barres, STUDY_LONG_DOWN_UP, 2);  // COUNT of patterns
        bn.long_up_down = ReadStudyValue(sc, chart_barres, STUDY_LONG_UP_DOWN, 2);  // COUNT of patterns
        // ðŸ”§ 30/01/2026: FIX - Subgraphs corrigÃ©s depuis study_inventory
        // [AV] COLOR = sg2 ("Sum of Alerts")
        // EDGE ZONES = sg58 ("Count of Alerts") - PAS sg2!
        bn.bar_color_up = ReadStudyValue(sc, chart_barres, BAR_COLOR_UP, 2);
        bn.bar_color_down = ReadStudyValue(sc, chart_barres, BAR_COLOR_DOWN, 2);
        bn.bar_edge_buy = ReadStudyValue(sc, chart_barres, BAR_EDGE_BUY, 58);   // ðŸ”§ FIX: sg58!
        bn.bar_edge_sell = ReadStudyValue(sc, chart_barres, BAR_EDGE_SELL, 58); // ðŸ”§ FIX: sg58!
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // COLLECTER EXTENSION LINES (Zones de rÃ©action des gros)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // Subgraph 1 = Extension Lines pour:
    //   - COLOR UP/DOWN (boules vertes/rouges)
    //   - LONG DOWN UP / LONG UP DOWN BAR (rectangles verts/rouges = reversals)
    // On scanne les derniÃ¨res 50 barres pour trouver les extensions actives

    bn.num_ext_support = 0;
    bn.num_ext_resist = 0;
    bn.nearest_ext_support = 0;
    bn.nearest_ext_resist = 0;

    // === ðŸ†• INITIALISER RECTANGLES TRADABLES (LONG UP/DOWN BAR) ===
    bn.num_long_up_bar = 0;
    bn.num_long_down_bar = 0;
    bn.nearest_long_up_bar = 0;
    bn.nearest_long_down_bar = 0;
    bn.has_tradable_support = false;
    bn.has_tradable_resist = false;
    for (int i = 0; i < 10; i++) {
        bn.long_up_bar_ext[i] = 0;
        bn.long_down_bar_ext[i] = 0;
    }

    float current_price = footprint_data[SC_LAST][last_idx];
    int scan_bars = 50;  // Scanner les derniÃ¨res 50 barres
    int start_bar = (last_idx > scan_bars) ? (last_idx - scan_bars) : 0;

    // --- Study IDs pour Extension Lines des reversals (LONG UP/DOWN BAR) ---
    // ðŸ”§ 30/01/2026: CORRIGÃ‰ - Utilise les constantes depuis JSON
    // Chart 25 (ES Barres): LONG_DOWN_UP=38, LONG_UP_DOWN=39
    // Chart 23 (NQ Barres): LONG_DOWN_UP=23, LONG_UP_DOWN=24
    int STUDY_REVERSAL_SUPPORT = STUDY_LONG_DOWN_UP;  // LONG DOWN UP BAR (reversal V = Support)
    int STUDY_REVERSAL_RESIST = STUDY_LONG_UP_DOWN;   // LONG UP DOWN BAR (reversal ^ = Resist)

    // --- ðŸ†• Study IDs pour RECTANGLES TRADABLES (LONG UP/DOWN BAR) ---
    // Ces sont les VRAIS rectangles verts/rouges - NIVEAUX TRADABLES!
    // ðŸ”§ 31/01/2026: UTILISE LES VARIABLES DEPUIS JSON (dÃ©jÃ  chargÃ©es en haut)
    // Chart 25 (ES Barres): LONG_UP_BAR=18, LONG_DOWN_BAR=17
    // Chart 23 (NQ Barres): LONG_UP_BAR=18, LONG_DOWN_BAR=17
    int STUDY_LONG_UP_BAR = BAR_LONG_UP_BAR;      // Rectangle vert = SUPPORT TRADABLE
    int STUDY_LONG_DOWN_BAR = BAR_LONG_DOWN_BAR; // Rectangle rouge = RESISTANCE TRADABLE

    // --- Study IDs pour EDGE ZONES IMBALANCE (Extension Lines depuis Footprint) ---
    // ðŸ”§ 31/01/2026: UTILISE LES VARIABLES DEPUIS JSON (dÃ©jÃ  chargÃ©es en haut)
    // ES Footprint (Chart 1): BUY=32, SELL=35
    // NQ Footprint (Chart 2): BUY=55, SELL=56
    int STUDY_EDGE_IMBALANCE_BUY = STUDY_EDGE_BUY;     // EDGE ZONES BUY = Support
    int STUDY_EDGE_IMBALANCE_SELL = STUDY_EDGE_SELL;  // EDGE ZONES SELL = RÃ©sistance

    // Helper lambda pour ajouter une extension sans doublon
    auto add_ext_support = [&](float ext_val) {
        if (ext_val > 0 && ext_val < current_price && bn.num_ext_support < 10) {
            bool duplicate = false;
            for (int j = 0; j < bn.num_ext_support; j++) {
                if (fabs(bn.ext_lines_support[j] - ext_val) < 0.5f) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                bn.ext_lines_support[bn.num_ext_support++] = ext_val;
            }
        }
    };

    auto add_ext_resist = [&](float ext_val) {
        if (ext_val > 0 && ext_val > current_price && bn.num_ext_resist < 10) {
            bool duplicate = false;
            for (int j = 0; j < bn.num_ext_resist; j++) {
                if (fabs(bn.ext_lines_resist[j] - ext_val) < 0.5f) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                bn.ext_lines_resist[bn.num_ext_resist++] = ext_val;
            }
        }
    };

    // ðŸ†• HELPERS pour RECTANGLES TRADABLES (sÃ©parÃ©s des boules/confluence)
    auto add_tradable_support = [&](float ext_val) {
        if (ext_val > 0 && ext_val < current_price && bn.num_long_up_bar < 10) {
            bool duplicate = false;
            for (int j = 0; j < bn.num_long_up_bar; j++) {
                if (fabs(bn.long_up_bar_ext[j] - ext_val) < 0.5f) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                bn.long_up_bar_ext[bn.num_long_up_bar++] = ext_val;
                // AUSSI ajouter aux extensions gÃ©nÃ©rales (rÃ©trocompatibilitÃ©)
                add_ext_support(ext_val);
            }
        }
    };

    auto add_tradable_resist = [&](float ext_val) {
        if (ext_val > 0 && ext_val > current_price && bn.num_long_down_bar < 10) {
            bool duplicate = false;
            for (int j = 0; j < bn.num_long_down_bar; j++) {
                if (fabs(bn.long_down_bar_ext[j] - ext_val) < 0.5f) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                bn.long_down_bar_ext[bn.num_long_down_bar++] = ext_val;
                // AUSSI ajouter aux extensions gÃ©nÃ©rales (rÃ©trocompatibilitÃ©)
                add_ext_resist(ext_val);
            }
        }
    };

    // Array pour lire les Extension Lines
    SCFloatArray study_array;

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 30/01/2026: Initialiser les arrays de boules pour rÃ¨gle subtile
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    bn.num_color_up_prices = 0;
    bn.num_color_down_prices = 0;
    bn.green_base_price = 0;
    bn.red_base_price = 0;
    bn.bn_subtile_long_valid = true;
    bn.bn_subtile_short_valid = true;
    bn.subtile_long_reason[0] = '\0';
    bn.subtile_short_reason[0] = '\0';

    // Initialiser RANGE
    bn.is_range = false;
    bn.range_support = 0;
    bn.range_resistance = 0;
    bn.range_midpoint = 0;
    bn.range_size_pts = 0;
    bn.price_position_pct = 50.0f;
    bn.price_position = 1;  // MIDDLE par dÃ©faut

    // === 1. COLOR UP (boules vertes) = SUPPORT ===
    // ðŸ†• 30/01/2026: Stocker TOUTES les boules pour rÃ¨gle subtile (pas de filtre prix)
    sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_COLOR_UP, 1, study_array);
    if (study_array.GetArraySize() > 0) {
        for (int i = start_bar; i <= last_idx && i < study_array.GetArraySize(); i++) {
            float price = study_array[i];
            if (price > 0) {
                // Stocker dans array dÃ©diÃ© pour rÃ¨gle subtile (TOUTES les boules)
                if (bn.num_color_up_prices < 20) {
                    bool dup = false;
                    for (int j = 0; j < bn.num_color_up_prices; j++) {
                        if (fabs(bn.color_up_prices[j] - price) < 0.5f) { dup = true; break; }
                    }
                    if (!dup) bn.color_up_prices[bn.num_color_up_prices++] = price;
                }
                // AUSSI ajouter aux ext_lines (rÃ©trocompatibilitÃ©)
                add_ext_support(price);
            }
        }
    }

    // === 2. COLOR DOWN (boules rouges) = RÃ‰SISTANCE ===
    // ðŸ†• 30/01/2026: Stocker TOUTES les boules pour rÃ¨gle subtile (pas de filtre prix)
    sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_COLOR_DOWN, 1, study_array);
    if (study_array.GetArraySize() > 0) {
        for (int i = start_bar; i <= last_idx && i < study_array.GetArraySize(); i++) {
            float price = study_array[i];
            if (price > 0) {
                // Stocker dans array dÃ©diÃ© pour rÃ¨gle subtile (TOUTES les boules)
                if (bn.num_color_down_prices < 20) {
                    bool dup = false;
                    for (int j = 0; j < bn.num_color_down_prices; j++) {
                        if (fabs(bn.color_down_prices[j] - price) < 0.5f) { dup = true; break; }
                    }
                    if (!dup) bn.color_down_prices[bn.num_color_down_prices++] = price;
                }
                // AUSSI ajouter aux ext_lines (rÃ©trocompatibilitÃ©)
                add_ext_resist(price);
            }
        }
    }

    // === 3. LONG DOWN UP BAR (rectangles verts = reversal haussier) = SUPPORT ===
    int barres_last_idx_ext = barres_data[0].GetArraySize() - 1;
    int barres_start = (barres_last_idx_ext > scan_bars) ? (barres_last_idx_ext - scan_bars) : 0;

    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_REVERSAL_SUPPORT, 1, study_array);
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            add_ext_support(study_array[i]);
        }
    }

    // === 4. LONG UP DOWN BAR (rectangles rouges = reversal baissier) = RÃ‰SISTANCE ===
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_REVERSAL_RESIST, 1, study_array);
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            add_ext_resist(study_array[i]);
        }
    }

    // === 5. EDGE ZONES IMBALANCE BUY (imbalance 800% = TRÃˆS FORT) = SUPPORT ===
    // Les Edge Zones utilisent des "Triggers" (subgraph 0-9) pour stocker les niveaux
    for (int trigger = 0; trigger < 10; trigger++) {
        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_BUY, trigger, study_array);
        if (study_array.GetArraySize() > 0) {
            for (int i = start_bar; i <= last_idx && i < study_array.GetArraySize(); i++) {
                float edge_val = study_array[i];
                if (edge_val > 0) {
                    add_ext_support(edge_val);  // EDGE BUY = Support (acheteurs agressifs)
                }
            }
        }
    }

    // === 6. EDGE ZONES IMBALANCE SELL (imbalance 800% = TRÃˆS FORT) = RÃ‰SISTANCE ===
    for (int trigger = 0; trigger < 10; trigger++) {
        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_SELL, trigger, study_array);
        if (study_array.GetArraySize() > 0) {
            for (int i = start_bar; i <= last_idx && i < study_array.GetArraySize(); i++) {
                float edge_val = study_array[i];
                if (edge_val > 0) {
                    add_ext_resist(edge_val);  // EDGE SELL = RÃ©sistance (vendeurs agressifs)
                }
            }
        }
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 7. LONG UP BAR - RECTANGLES VERTS TRADABLES (depuis Chart Barres)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // Ces sont les VRAIS rectangles verts - NIVEAUX TRADABLES Ã  prioriser!
    // ðŸ”§ 30/01/2026: Essayer SG1 (Extension Lines) d'abord, puis SG0 (Color Bar) en fallback

    // Essai 1: SG1 = Extension Lines (niveaux prolongÃ©s)
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_LONG_UP_BAR, 1, study_array);  // SG1 = Extension Lines
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            float rect_val = study_array[i];
            if (rect_val > 0) {
                add_tradable_support(rect_val);  // Rectangle vert = SUPPORT TRADABLE
            }
        }
    }
    // Essai 2: SG0 = Color Bar (prix de la barre oÃ¹ le rectangle apparaÃ®t)
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_LONG_UP_BAR, 0, study_array);  // SG0 = Color Bar
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            float rect_val = study_array[i];
            if (rect_val > 0) {
                add_tradable_support(rect_val);  // Rectangle vert = SUPPORT TRADABLE (fallback)
            }
        }
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 8. LONG DOWN BAR - RECTANGLES ROUGES TRADABLES (depuis Chart Barres)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // Ces sont les VRAIS rectangles rouges - NIVEAUX TRADABLES Ã  prioriser!
    // ðŸ”§ 30/01/2026: Essayer SG1 (Extension Lines) d'abord, puis SG0 (Color Bar) en fallback

    // Essai 1: SG1 = Extension Lines (niveaux prolongÃ©s)
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_LONG_DOWN_BAR, 1, study_array);  // SG1 = Extension Lines
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            float rect_val = study_array[i];
            if (rect_val > 0) {
                add_tradable_resist(rect_val);  // Rectangle rouge = RESISTANCE TRADABLE
            }
        }
    }
    // Essai 2: SG0 = Color Bar (prix de la barre oÃ¹ le rectangle apparaÃ®t)
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_LONG_DOWN_BAR, 0, study_array);  // SG0 = Color Bar
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            float rect_val = study_array[i];
            if (rect_val > 0) {
                add_tradable_resist(rect_val);  // Rectangle rouge = RESISTANCE TRADABLE (fallback)
            }
        }
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• COLLECTER GROS RECTANGLES EDGE ZONE (Adjacent Alert Highlight)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // Subgraphs 48-57 contiennent les coordonnÃ©es des rectangles Ã©pais
    // 48,50,52,54,56 = Bottom | 49,51,53,55,57 = Top
    // Ces zones reprÃ©sentent des imbalances/absorptions massives

    bn.num_edge_rect_buy = 0;
    bn.num_edge_rect_sell = 0;
    bn.nearest_edge_rect_support = 0;
    bn.nearest_edge_rect_resist = 0;
    bn.price_in_edge_rect_buy = false;
    bn.price_in_edge_rect_sell = false;

    // Collecter rectangles BUY (support) - Subgraphs 48-56 (bottom/top pairs)
    for (int rect_idx = 0; rect_idx < 5 && bn.num_edge_rect_buy < 5; rect_idx++) {
        int sg_bottom = 48 + (rect_idx * 2);  // 48, 50, 52, 54, 56
        int sg_top = sg_bottom + 1;            // 49, 51, 53, 55, 57

        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_BUY, sg_bottom, study_array);
        float bottom = (study_array.GetArraySize() > last_idx) ? study_array[last_idx] : 0;

        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_BUY, sg_top, study_array);
        float top = (study_array.GetArraySize() > last_idx) ? study_array[last_idx] : 0;

        if (bottom > 0 && top > bottom) {  // Rectangle valide
            bn.edge_rect_buy_bottom[bn.num_edge_rect_buy] = bottom;
            bn.edge_rect_buy_top[bn.num_edge_rect_buy] = top;
            bn.num_edge_rect_buy++;

            // VÃ©rifier si prix dans ce rectangle
            if (current_price >= bottom && current_price <= top) {
                bn.price_in_edge_rect_buy = true;
            }

            // Trouver rectangle support le plus proche
            if (top < current_price) {  // Rectangle en dessous = support
                float dist = current_price - top;
                if (bn.nearest_edge_rect_support == 0 || dist < fabs(current_price - bn.nearest_edge_rect_support)) {
                    bn.nearest_edge_rect_support = top;
                }
            }
        }
    }

    // Collecter rectangles SELL (rÃ©sistance)
    for (int rect_idx = 0; rect_idx < 5 && bn.num_edge_rect_sell < 5; rect_idx++) {
        int sg_bottom = 48 + (rect_idx * 2);
        int sg_top = sg_bottom + 1;

        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_SELL, sg_bottom, study_array);
        float bottom = (study_array.GetArraySize() > last_idx) ? study_array[last_idx] : 0;

        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_SELL, sg_top, study_array);
        float top = (study_array.GetArraySize() > last_idx) ? study_array[last_idx] : 0;

        if (bottom > 0 && top > bottom) {  // Rectangle valide
            bn.edge_rect_sell_bottom[bn.num_edge_rect_sell] = bottom;
            bn.edge_rect_sell_top[bn.num_edge_rect_sell] = top;
            bn.num_edge_rect_sell++;

            // VÃ©rifier si prix dans ce rectangle
            if (current_price >= bottom && current_price <= top) {
                bn.price_in_edge_rect_sell = true;
            }

            // Trouver rectangle rÃ©sistance le plus proche
            if (bottom > current_price) {  // Rectangle au dessus = rÃ©sistance
                float dist = bottom - current_price;
                if (bn.nearest_edge_rect_resist == 0 || dist < fabs(bn.nearest_edge_rect_resist - current_price)) {
                    bn.nearest_edge_rect_resist = bottom;
                }
            }
        }
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• BATAILLE NAVALE AVANCÃ‰E - ANALYSE CONFIGURATION SPATIALE
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    // --- 1. Trouver les extrÃªmes des zones (plus bas BUY, plus haut SELL) ---
    bn.lowest_edge_buy = 999999.0f;
    bn.highest_edge_sell = 0.0f;

    for (int i = 0; i < bn.num_edge_rect_buy; i++) {
        if (bn.edge_rect_buy_bottom[i] < bn.lowest_edge_buy) {
            bn.lowest_edge_buy = bn.edge_rect_buy_bottom[i];
        }
    }
    for (int i = 0; i < bn.num_ext_support; i++) {
        if (bn.ext_lines_support[i] > 0 && bn.ext_lines_support[i] < bn.lowest_edge_buy) {
            bn.lowest_edge_buy = bn.ext_lines_support[i];
        }
    }
    if (bn.lowest_edge_buy > 900000.0f) bn.lowest_edge_buy = 0;

    for (int i = 0; i < bn.num_edge_rect_sell; i++) {
        if (bn.edge_rect_sell_top[i] > bn.highest_edge_sell) {
            bn.highest_edge_sell = bn.edge_rect_sell_top[i];
        }
    }
    for (int i = 0; i < bn.num_ext_resist; i++) {
        if (bn.ext_lines_resist[i] > bn.highest_edge_sell) {
            bn.highest_edge_sell = bn.ext_lines_resist[i];
        }
    }

    // --- 2. RÃ¨gle "Pas de boule opposÃ©e sous/dessus" ---
    // LONG valide = PAS de edge_sell SOUS le plus bas edge_buy
    bn.bn_attack_long_valid = true;
    if (bn.lowest_edge_buy > 0 && bn.num_edge_rect_buy > 0) {
        // VÃ©rifier s'il y a un rectangle SELL sous le plus bas BUY
        for (int i = 0; i < bn.num_edge_rect_sell; i++) {
            if (bn.edge_rect_sell_top[i] < bn.lowest_edge_buy) {
                bn.bn_attack_long_valid = false;  // âŒ Boule rouge sous le vert!
                break;
            }
        }
    }

    // SHORT valide = PAS de edge_buy AU-DESSUS du plus haut edge_sell
    bn.bn_attack_short_valid = true;
    if (bn.highest_edge_sell > 0 && bn.num_edge_rect_sell > 0) {
        for (int i = 0; i < bn.num_edge_rect_buy; i++) {
            if (bn.edge_rect_buy_bottom[i] > bn.highest_edge_sell) {
                bn.bn_attack_short_valid = false;  // âŒ Boule verte au-dessus du rouge!
                break;
            }
        }
    }

    // --- 3. Comptage de l'empilement (zones empilÃ©es = attaque coordonnÃ©e) ---
    bn.stacked_buy_zones = bn.num_edge_rect_buy;
    bn.stacked_sell_zones = bn.num_edge_rect_sell;

    // Force de l'attaque basÃ©e sur empilement + domination
    bn.attack_strength_buy = 0.0f;
    bn.attack_strength_sell = 0.0f;

    if (bn.stacked_buy_zones >= 3) {
        bn.attack_strength_buy = 1.0f;  // 3+ rectangles = attaque MASSIVE
    } else if (bn.stacked_buy_zones == 2) {
        bn.attack_strength_buy = 0.7f;  // 2 rectangles = attaque forte
    } else if (bn.stacked_buy_zones == 1) {
        bn.attack_strength_buy = 0.4f;  // 1 rectangle = zone isolÃ©e
    }
    // Bonus si edge_dominant_buy
    if (bn.edge_dominant_buy) bn.attack_strength_buy += 0.2f;
    if (bn.attack_strength_buy > 1.0f) bn.attack_strength_buy = 1.0f;

    if (bn.stacked_sell_zones >= 3) {
        bn.attack_strength_sell = 1.0f;
    } else if (bn.stacked_sell_zones == 2) {
        bn.attack_strength_sell = 0.7f;
    } else if (bn.stacked_sell_zones == 1) {
        bn.attack_strength_sell = 0.4f;
    }
    if (bn.edge_dominant_sell) bn.attack_strength_sell += 0.2f;
    if (bn.attack_strength_sell > 1.0f) bn.attack_strength_sell = 1.0f;

    // --- 4. CohÃ©rence directionnelle ---
    // Compter combien de signaux pointent dans chaque direction
    int bullish_signals = 0;
    int bearish_signals = 0;

    // ðŸ”§ 30/01/2026: FIX - Utiliser les COUNTS de rectangles, pas les PRIX
    if (bn.num_edge_rect_buy > bn.num_edge_rect_sell) bullish_signals++;
    else if (bn.num_edge_rect_sell > bn.num_edge_rect_buy) bearish_signals++;
    if (bn.color_up > bn.color_down) bullish_signals++; else if (bn.color_down > bn.color_up) bearish_signals++;
    if (bn.rotation_up > bn.rotation_down) bullish_signals++; else if (bn.rotation_down > bn.rotation_up) bearish_signals++;
    if (bn.absorb_bid > bn.absorb_ask) bullish_signals++; else if (bn.absorb_ask > bn.absorb_bid) bearish_signals++;
    if (bn.long_down_up > bn.long_up_down) bullish_signals++; else if (bn.long_up_down > bn.long_down_up) bearish_signals++;
    if (bn.num_edge_rect_buy > bn.num_edge_rect_sell) bullish_signals++;
    else if (bn.num_edge_rect_sell > bn.num_edge_rect_buy) bearish_signals++;

    int total_signals = bullish_signals + bearish_signals;
    bn.all_signals_bullish = (bullish_signals >= 4 && bearish_signals == 0);
    bn.all_signals_bearish = (bearish_signals >= 4 && bullish_signals == 0);

    if (total_signals > 0) {
        bn.directional_coherence = (float)(bullish_signals - bearish_signals) / (float)total_signals;
    } else {
        bn.directional_coherence = 0.0f;
    }

    // Trouver la plus proche de chaque cÃ´tÃ©
    if (bn.num_ext_support > 0) {
        bn.nearest_ext_support = bn.ext_lines_support[0];
        for (int i = 1; i < bn.num_ext_support; i++) {
            if (bn.ext_lines_support[i] > bn.nearest_ext_support) {
                bn.nearest_ext_support = bn.ext_lines_support[i];  // Support le plus haut = plus proche
            }
        }
    }
    if (bn.num_ext_resist > 0) {
        bn.nearest_ext_resist = bn.ext_lines_resist[0];
        for (int i = 1; i < bn.num_ext_resist; i++) {
            if (bn.ext_lines_resist[i] < bn.nearest_ext_resist) {
                bn.nearest_ext_resist = bn.ext_lines_resist[i];  // RÃ©sistance la plus basse = plus proche
            }
        }
    }

    // ðŸ†• CALCUL DES DISTANCES EN TICKS (comme Python: ext_lines.nearest_support/resist)
    float tick_size_bn = 0.25f;  // Tick size identique ES/NQ pour BN
    bn.dist_nearest_support_ticks = 0;
    bn.dist_nearest_resist_ticks = 0;
    if (bn.nearest_ext_support > 0 && bn.nearest_ext_support < current_price) {
        bn.dist_nearest_support_ticks = (current_price - bn.nearest_ext_support) / tick_size_bn;
    }
    if (bn.nearest_ext_resist > 0 && bn.nearest_ext_resist > current_price) {
        bn.dist_nearest_resist_ticks = (bn.nearest_ext_resist - current_price) / tick_size_bn;
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 30/01/2026: RÃˆGLE SUBTILE AVEC LES BOULES (Alignement Python)
    // - LONG: Pas de boule ROUGE sous la BASE VERTE
    // - SHORT: Pas de boule VERTE au-dessus de la BASE ROUGE
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    // 1. Trouver la BASE VERTE = max(boules vertes SOUS le prix)
    bn.green_base_price = 0;
    for (int i = 0; i < bn.num_color_up_prices; i++) {
        if (bn.color_up_prices[i] < current_price && bn.color_up_prices[i] > bn.green_base_price) {
            bn.green_base_price = bn.color_up_prices[i];
        }
    }

    // 2. Trouver la BASE ROUGE = min(boules rouges AU-DESSUS du prix)
    bn.red_base_price = 999999.0f;
    for (int i = 0; i < bn.num_color_down_prices; i++) {
        if (bn.color_down_prices[i] > current_price && bn.color_down_prices[i] < bn.red_base_price) {
            bn.red_base_price = bn.color_down_prices[i];
        }
    }
    if (bn.red_base_price > 900000.0f) bn.red_base_price = 0;

    // 3. RÃˆGLE SUBTILE LONG: Pas de rouge sous la base verte
    bn.bn_subtile_long_valid = true;
    if (bn.green_base_price > 0) {
        for (int i = 0; i < bn.num_color_down_prices; i++) {
            if (bn.color_down_prices[i] < bn.green_base_price) {
                bn.bn_subtile_long_valid = false;
                snprintf(bn.subtile_long_reason, sizeof(bn.subtile_long_reason),
                         "Rouge %.2f sous base verte %.2f", bn.color_down_prices[i], bn.green_base_price);
                break;
            }
        }
    }

    // 4. RÃˆGLE SUBTILE SHORT: Pas de vert au-dessus de la base rouge
    bn.bn_subtile_short_valid = true;
    if (bn.red_base_price > 0) {
        for (int i = 0; i < bn.num_color_up_prices; i++) {
            if (bn.color_up_prices[i] > bn.red_base_price) {
                bn.bn_subtile_short_valid = false;
                snprintf(bn.subtile_short_reason, sizeof(bn.subtile_short_reason),
                         "Verte %.2f au-dessus base rouge %.2f", bn.color_up_prices[i], bn.red_base_price);
                break;
            }
        }
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 30/01/2026: MODE RANGE - DÃ©tection et position (Alignement Python)
    // Range = min(ext_lines_support) Ã  max(ext_lines_resist)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    // ParamÃ¨tres de range selon symbole
    float range_min_pts = is_nq ? 20.0f : 5.0f;   // NQ: 20-200, ES: 5-50
    float range_max_pts = is_nq ? 200.0f : 50.0f;
    float near_pct = 15.0f;  // 15% = NEAR_SUPPORT ou NEAR_RESISTANCE

    // Trouver min support et max rÃ©sistance
    float min_support = 999999.0f;
    float max_resist = 0.0f;

    for (int i = 0; i < bn.num_ext_support; i++) {
        if (bn.ext_lines_support[i] > 0 && bn.ext_lines_support[i] < min_support) {
            min_support = bn.ext_lines_support[i];
        }
    }
    for (int i = 0; i < bn.num_ext_resist; i++) {
        if (bn.ext_lines_resist[i] > max_resist) {
            max_resist = bn.ext_lines_resist[i];
        }
    }

    // Calculer le range
    if (min_support < 900000.0f && max_resist > 0 && max_resist > min_support) {
        float range_size = max_resist - min_support;

        // Valider la taille du range
        if (range_size >= range_min_pts && range_size <= range_max_pts) {
            bn.is_range = true;
            bn.range_support = min_support;
            bn.range_resistance = max_resist;
            bn.range_midpoint = (min_support + max_resist) / 2.0f;
            bn.range_size_pts = range_size;

            // Position du prix dans le range (0% = support, 100% = rÃ©sistance)
            bn.price_position_pct = ((current_price - min_support) / range_size) * 100.0f;
            if (bn.price_position_pct < 0) bn.price_position_pct = 0;
            if (bn.price_position_pct > 100) bn.price_position_pct = 100;

            // DÃ©terminer la zone
            if (bn.price_position_pct <= near_pct) {
                bn.price_position = 0;  // NEAR_SUPPORT
            } else if (bn.price_position_pct >= (100.0f - near_pct)) {
                bn.price_position = 2;  // NEAR_RESISTANCE
            } else {
                bn.price_position = 1;  // MIDDLE
            }
        }
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• TROUVER RECTANGLES TRADABLES LES PLUS PROCHES
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    float tick_size = is_nq ? 0.25f : 0.25f;  // Tick size pour calculs
    float proximity_threshold = is_nq ? 30.0f : 8.0f;  // 30 pts NQ, 8 pts ES

    if (bn.num_long_up_bar > 0) {
        bn.nearest_long_up_bar = bn.long_up_bar_ext[0];
        for (int i = 1; i < bn.num_long_up_bar; i++) {
            if (bn.long_up_bar_ext[i] > bn.nearest_long_up_bar) {
                bn.nearest_long_up_bar = bn.long_up_bar_ext[i];  // Support le plus haut = plus proche
            }
        }
        // VÃ©rifier si assez proche pour Ãªtre "tradable"
        float dist_support = current_price - bn.nearest_long_up_bar;
        bn.has_tradable_support = (dist_support > 0 && dist_support <= proximity_threshold);
    }

    if (bn.num_long_down_bar > 0) {
        bn.nearest_long_down_bar = bn.long_down_bar_ext[0];
        for (int i = 1; i < bn.num_long_down_bar; i++) {
            if (bn.long_down_bar_ext[i] < bn.nearest_long_down_bar) {
                bn.nearest_long_down_bar = bn.long_down_bar_ext[i];  // RÃ©sistance la plus basse = plus proche
            }
        }
        // VÃ©rifier si assez proche pour Ãªtre "tradable"
        float dist_resist = bn.nearest_long_down_bar - current_price;
        bn.has_tradable_resist = (dist_resist > 0 && dist_resist <= proximity_threshold);
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // CALCUL SCORE BN COMPLET - Toutes donnÃ©es utilisÃ©es
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    // === 1. SIGNAUX FOOTPRINT (base) ===
    // ðŸ”§ 30/01/2026: FIX - edge_buy/edge_sell sont des PRIX, pas des COUNTS!
    //               Utiliser num_edge_rect_buy/sell * poids comme proxy pour l'activitÃ© edge
    float edge_weight = 50.0f;  // Un rectangle edge â‰ˆ signal fort
    float buyer_strength = (bn.num_edge_rect_buy * edge_weight) + bn.color_up + bn.absorb_bid;
    float seller_strength = (bn.num_edge_rect_sell * edge_weight) + bn.color_down + bn.absorb_ask;

    // === 2. MOMENTUM (rotation) - CRITIQUE ===
    // Le momentum donne la direction court-terme
    bn.momentum_score = 0;
    float rotation_total = bn.rotation_up + bn.rotation_down;
    if (rotation_total > 0) {
        bn.momentum_score = (bn.rotation_up - bn.rotation_down) / rotation_total;
    }
    // Ajouter au score (poids x0.5 pour normaliser)
    buyer_strength += bn.rotation_up * 0.5f;
    seller_strength += bn.rotation_down * 0.5f;

    // === 3. REVERSALS (long_down_up/up_down) - CRITIQUE x2 ===
    // Les reversals sont des signaux FORTS de retournement
    bn.reversal_score = 0;
    if (bn.long_down_up > 0 || bn.long_up_down > 0) {
        bn.reversal_score = (bn.long_down_up - bn.long_up_down) / fmax(1.0f, bn.long_down_up + bn.long_up_down);
    }
    // Poids x2 car signal de retournement institutionnel
    buyer_strength += bn.long_down_up * 2.0f;
    seller_strength += bn.long_up_down * 2.0f;

    // === 4. SIGNAUX SPÃ‰CIFIQUES NQ/ES ===
    if (is_nq) {
        buyer_strength += bn.triple_bid + bn.volume_up;
        seller_strength += bn.triple_ask + bn.volume_down;
    } else {
        buyer_strength += bn.double_bid;
        seller_strength += bn.double_ask;
    }

    // === 5. GROS ORDRES (Pression institutionnelle) ===
    // Les gros ordres montrent l'intÃ©rÃªt des institutionnels
    bn.institutional_pressure = 0;
    float inst_buy = bn.bid_100 + bn.bid_150 * 1.5f + bn.bid_400 * 2.0f + bn.bid_1000 * 3.0f;
    float inst_sell = bn.ask_100 + bn.ask_150 * 1.5f + bn.ask_400 * 2.0f + bn.ask_1000 * 3.0f;
    if (inst_buy + inst_sell > 0) {
        bn.institutional_pressure = (inst_buy - inst_sell) / (inst_buy + inst_sell);
    }
    // Ajouter avec poids progressif
    buyer_strength += inst_buy * 0.3f;
    seller_strength += inst_sell * 0.3f;

    // === 6. FPBS (Force de pression) ===
    // DÃ©sÃ©quilibre FPBS confirme la direction
    if (bn.fpbs_ask_pct > 0 || bn.fpbs_bid_pct > 0) {
        buyer_strength += bn.fpbs_bid_pct * 10.0f;  // Normaliser sur ~1
        seller_strength += bn.fpbs_ask_pct * 10.0f;
    }

    // === ðŸ†• 6b. FPBS DELTA (Direction de la barre) ===
    // Delta > 0 = Plus d'achats que de ventes sur cette barre
    // Delta < 0 = Plus de ventes que d'achats sur cette barre
    if (bn.fpbs_delta != 0) {
        // Normalisation: Delta peut Ãªtre trÃ¨s grand (milliers), on normalise
        float delta_normalized = bn.fpbs_delta / 1000.0f;  // Ã‰chelle ~1
        if (delta_normalized > 3.0f) delta_normalized = 3.0f;  // Cap
        if (delta_normalized < -3.0f) delta_normalized = -3.0f;

        if (delta_normalized > 0) {
            buyer_strength += delta_normalized * 0.5f;  // Delta positif = acheteurs
        } else {
            seller_strength += (-delta_normalized) * 0.5f;  // Delta nÃ©gatif = vendeurs
        }
    }

    // === ðŸ†• 6c. FPBS DELTA_DAY (Biais journalier) ===
    // Delta_Day cumulÃ© indique le biais global de la journÃ©e
    if (bn.fpbs_delta_day != 0) {
        float delta_day_normalized = bn.fpbs_delta_day / 10000.0f;  // Plus grand car cumulÃ©
        if (delta_day_normalized > 2.0f) delta_day_normalized = 2.0f;
        if (delta_day_normalized < -2.0f) delta_day_normalized = -2.0f;

        if (delta_day_normalized > 0) {
            buyer_strength += delta_day_normalized * 0.3f;  // Biais acheteur journalier
        } else {
            seller_strength += (-delta_day_normalized) * 0.3f;  // Biais vendeur journalier
        }
    }

    // === 7. SIGNAUX BARRES (confirmation) ===
    // Les barres donnent une vue plus "macro"
    buyer_strength += bn.bar_color_up * 0.3f + bn.bar_edge_buy * 0.5f;
    seller_strength += bn.bar_color_down * 0.3f + bn.bar_edge_sell * 0.5f;

    // === 8. CLUSTER VOLUME (zones d'intÃ©rÃªt) ===
    // Les clusters ajoutent de la confluence
    if (bn.cluster_vol > 0) {
        // Cluster renforce le cÃ´tÃ© dominant
        if (buyer_strength > seller_strength) {
            buyer_strength += bn.cluster_vol * 0.2f;
        } else {
            seller_strength += bn.cluster_vol * 0.2f;
        }
    }

    float total = buyer_strength + seller_strength;

    // === FIX BUG BN SCORE Â±1.0 ===
    // Compter les signaux valides de chaque cÃ´tÃ©
    // ðŸ”§ 30/01/2026: FIX - Utiliser num_edge_rect_buy/sell au lieu de edge_buy/sell (qui sont des PRIX)
    int buyer_signals = (bn.num_edge_rect_buy > 0 ? 1 : 0) + (bn.color_up > 0 ? 1 : 0) +
                        (bn.absorb_bid > 0 ? 1 : 0) + (bn.rotation_up > 0 ? 1 : 0);
    int seller_signals = (bn.num_edge_rect_sell > 0 ? 1 : 0) + (bn.color_down > 0 ? 1 : 0) +
                         (bn.absorb_ask > 0 ? 1 : 0) + (bn.rotation_down > 0 ? 1 : 0);

    // Si un cÃ´tÃ© n'a AUCUN signal mais l'autre oui = donnÃ©es incomplÃ¨tes
    // Dans ce cas, score = 0 (neutre) au lieu de Â±1.0
    bool data_incomplete = (buyer_signals == 0 && seller_signals > 0) ||
                          (seller_signals == 0 && buyer_signals > 0);

    if (total > 0 && !data_incomplete) {
        bn.score = (buyer_strength - seller_strength) / total;
        // Clamp pour Ã©viter les extrÃªmes dus Ã  des artefacts
        if (bn.score > 0.95f) bn.score = 0.95f;
        if (bn.score < -0.95f) bn.score = -0.95f;
    } else if (data_incomplete) {
        // DonnÃ©es incomplÃ¨tes = ne pas utiliser, score neutre
        bn.score = 0.0f;
        bn.signal = 0;
        return;  // Exit early
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• PRO FEATURE 1: MOMENTUM DELTA (dÃ©tection changements)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // color_momentum = valeur intermÃ©diaire, momentum_shift = rÃ©sultat final utilisÃ©
    float current_momentum = bn.color_up - bn.color_down;
    float prev_momentum = bn.prev_color_up - bn.prev_color_down;
    bn.color_momentum = current_momentum - prev_momentum;  // IntermÃ©diaire (pour logs)

    // momentum_shift = indicateur final utilisÃ© dans Layer 2
    if (bn.color_momentum > 5.0f) {
        bn.momentum_shift = 1.0f;   // Shift BULLISH!
        bn.score += 0.05f;          // Bonus au score
    } else if (bn.color_momentum < -5.0f) {
        bn.momentum_shift = -1.0f;  // Shift BEARISH!
        bn.score -= 0.05f;          // Malus au score
    } else {
        bn.momentum_shift = 0.0f;   // Stable
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• PRO FEATURE 2: RECTANGLES FRAIS (dÃ©tection nouvelles zones)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // Un rectangle FRAIS = zone institutionnelle VIENT d'Ãªtre touchÃ©e
    bn.fresh_rectangle_buy = (bn.double_bid > bn.prev_double_bid);
    bn.fresh_rectangle_sell = (bn.double_ask > bn.prev_double_ask);

    if (bn.fresh_rectangle_buy) {
        bn.score += 0.08f;  // GROS bonus! Zone achat frais = signal fort
        bn.fresh_rect_age_bars = 0;
    }
    if (bn.fresh_rectangle_sell) {
        bn.score -= 0.08f;  // GROS malus! Zone vente frais = signal fort
        bn.fresh_rect_age_bars = 0;
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• PRO FEATURE 3: EDGE ZONE RATIO (domination claire)
    // ðŸ”§ 30/01/2026: FIX - Utilise num_edge_rect_buy/sell (COUNTS rÃ©els) au lieu de
    //               edge_buy/edge_sell qui retournent des PRIX (pas de sg "Count" pour EDGE ZONES)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    int edge_count_buy = bn.num_edge_rect_buy;
    int edge_count_sell = bn.num_edge_rect_sell;
    int edge_total = edge_count_buy + edge_count_sell;

    if (edge_total > 0) {
        bn.edge_ratio = (float)edge_count_buy / (float)edge_total;

        // Domination claire si ratio > 0.65 ou < 0.35
        bn.edge_dominant_buy = (bn.edge_ratio > 0.65f);
        bn.edge_dominant_sell = (bn.edge_ratio < 0.35f);

        // Bonus/Malus pour domination
        if (bn.edge_dominant_buy) {
            bn.score += 0.04f;  // Acheteurs dominent (plus de rectangles verts)
        }
        if (bn.edge_dominant_sell) {
            bn.score -= 0.04f;  // Vendeurs dominent (plus de rectangles rouges)
        }
    } else {
        bn.edge_ratio = 0.5f;
        bn.edge_dominant_buy = false;
        bn.edge_dominant_sell = false;
    }

    // ðŸ†• Stocker le premier trigger actif pour rÃ©fÃ©rence (prix du niveau edge)
    // Note: edge_buy/edge_sell contiennent le prix du trigger 0 s'il existe
    // Ce n'est PAS un count mais le prix de la zone - utile pour SL/TP

    // Sauvegarder valeurs pour prochaine itÃ©ration
    bn.prev_color_up = bn.color_up;
    bn.prev_color_down = bn.color_down;
    bn.prev_double_bid = bn.double_bid;
    bn.prev_double_ask = bn.double_ask;

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• CVD & POC ANALYSIS (Confirmation de Tendance)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    // --- CVD SLOPE CALCULATION ---
    // Calcule la pente du CVD pour dÃ©tecter la tendance et les divergences
    // CVD slope > 0 = acheteurs accumulent = bullish
    // CVD slope < 0 = vendeurs accumulent = bearish
    // Divergence = prix monte + CVD baisse (ou inverse) = DANGER!

    bn.cvd_slope = 0;
    bn.cvd_divergence = false;
    bn.cvd_trend_score = 0;

    if (bn.fpbs_cvd != 0 && bn.prev_cvd != 0) {
        // Slope = variation du CVD (normalisÃ©)
        bn.cvd_slope = bn.fpbs_cvd - bn.prev_cvd;

        // Trend score basÃ© sur la magnitude du slope
        // +100 Ã  +500 = lÃ©gÃ¨rement bullish â†’ +500 Ã  +2000 = fortement bullish
        if (bn.cvd_slope > 100) {
            bn.cvd_trend_score = fmin(bn.cvd_slope / 500.0f, 1.0f);  // Max 1.0
        } else if (bn.cvd_slope < -100) {
            bn.cvd_trend_score = fmax(bn.cvd_slope / 500.0f, -1.0f);  // Min -1.0
        }

        // DÃ©tection DIVERGENCE (CVD vs Prix)
        // Forte divergence = CVD slope > 500 dans direction opposÃ©e au prix
        // On utilise le score BN comme proxy du mouvement de prix
        if (bn.score > 0.1f && bn.cvd_slope < -500) {
            // Prix monte (score bullish) MAIS CVD chute fortement = DIVERGENCE BEARISH
            bn.cvd_divergence = true;
        }
        if (bn.score < -0.1f && bn.cvd_slope > 500) {
            // Prix baisse (score bearish) MAIS CVD monte fortement = DIVERGENCE BULLISH
            bn.cvd_divergence = true;
        }
    }

    // ðŸ”§ FIX CVD SLOPE: Sauvegarder CVD pour prochaine itÃ©ration (persistant!)
    // NOTE: Ne PAS Ã©craser bn.prev_cvd ici - on garde la valeur originale pour le diagnostic!
    // bn.prev_cvd = bn.fpbs_cvd;  // âŒ SupprimÃ© pour debug
    sc.SetPersistentFloat(cvd_persist_idx, bn.fpbs_cvd);  // Persiste entre les appels!

    // --- POC CONFIRMATION ---
    // Compare le prix actuel (Close) avec le POC de la bougie
    // Close > POC = acheteurs ont gagnÃ© la bougie = BULLISH confirmation
    // Close < POC = vendeurs ont gagnÃ© la bougie = BEARISH confirmation

    bn.poc_confirm = 0;  // Neutre par dÃ©faut

    if (bn.fpbs_poc > 0 && current_price > 0) {
        float poc_distance = current_price - bn.fpbs_poc;
        float tick_threshold = is_nq ? 2.0f : 0.5f;  // 2 ticks NQ, 0.5 pts ES

        if (poc_distance > tick_threshold) {
            bn.poc_confirm = 1;   // BULLISH - Close au-dessus POC
        } else if (poc_distance < -tick_threshold) {
            bn.poc_confirm = -1;  // BEARISH - Close en-dessous POC
        }
        // Sinon reste 0 (neutre - Close â‰ˆ POC)
    }

    // Re-clamp aprÃ¨s bonus/malus
    if (bn.score > 0.95f) bn.score = 0.95f;
    if (bn.score < -0.95f) bn.score = -0.95f;

    // âš ï¸ DEPRECATED: Signal est redondant avec score
    // GardÃ© uniquement pour compatibilitÃ© logs/dumps
    // Utiliser bn.score directement dans la logique de trading!
    if (bn.score > 0.08f) bn.signal = 1;
    else if (bn.score < -0.08f) bn.signal = -1;
    else bn.signal = 0;
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// SECTION 6: COLLECTE DONNÃ‰ES MENTHORQ
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

inline void CollectMenthorQ_Data(SCStudyInterfaceRef sc, int main_chart, MenthorQ_Data& mq, bool is_nq) {
    memset(&mq, 0, sizeof(MenthorQ_Data));

    SCFloatArray study_array;
    SCGraphData chart_data;
    sc.GetChartBaseData(main_chart, chart_data);

    int last_idx = chart_data[0].GetArraySize() - 1;
    if (last_idx < 0) return;

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // STUDY IDs MenthorQ - VRAIS IDs DES CHARTS (scan du 17/01/2026)
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // MenthorQ Gamma Levels subgraphs:
    //   0=Call Resistance, 1=Put Support, 2=HVL, 3=1D Min, 4=1D Max,
    //   5=Call 0DTE/Gamma Wall, 6=Put 0DTE, 7=HVL 0DTE, 8=Gamma Wall 0DTE,
    //   9-18=GEX 1-10
    // MenthorQ Blind Spots subgraphs: 0-9=BL 1-10
    // VWAP subgraphs: 0=VWAP, 1=+1Ïƒ, 2=-1Ïƒ, 3=+2Ïƒ, 4=-2Ïƒ...

    // ðŸ”§ 31/01/2026: MIGRATION vers study_mapping.json (Correction 4)
    const char* barres_key = is_nq ? "NQ_BARRES" : "ES_BARRES";
    int STUDY_MQ_GAMMA = STUDY_ID(barres_key, "MQ_GAMMA");
    int STUDY_MQ_BLINDSPOT = STUDY_ID(barres_key, "MQ_BLIND");
    int STUDY_MQ_VWAP = STUDY_ID(barres_key, "VWAP");

    // Call/Put Resistance/Support (subgraphs 0, 1)
    mq.call_resistance = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 0);
    mq.put_support = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 1);

    // HVL (subgraph 2)
    mq.hvl = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 2);

    // ðŸ”§ 28/01/2026: FIX - Lire TOUS les niveaux 0DTE (manquaient!)
    // Ces niveaux sont CRITIQUES pour dÃ©tecter les obstacles intraday!
    // Subgraphs MenthorQ Gamma:
    //   5 = call_resistance_0dte
    //   6 = put_support_0dte
    //   7 = hvl_0dte
    //   8 = gamma_wall_0dte
    mq.call_resistance_0dte = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 5);
    mq.put_support_0dte = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 6);
    mq.hvl_0dte = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 7);
    mq.gamma_wall_0dte = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 8);
    // Fallback: gamma_wall affiche au moins gamma_wall_0dte si pas de subgraph dedie (JSON 100% rempli)
    if (mq.gamma_wall == 0.0f && mq.gamma_wall_0dte > 0.0f) mq.gamma_wall = mq.gamma_wall_0dte;

    // 1D Min/Max (subgraphs 3, 4)
    mq.day_min = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 3);
    mq.day_max = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 4);

    // GEX 1-10 (subgraphs 9-18)
    for (int i = 0; i < 10; i++) {
        mq.gex[i] = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 9 + i);
    }

    // VWAP et bandes
    mq.vwap = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 0);
    mq.vwap_up1 = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 1);
    mq.vwap_dn1 = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 2);
    mq.vwap_up2 = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 3);
    mq.vwap_dn2 = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 4);

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // Value Area (VAH/VAL) - PARITÃ‰ PYTHON
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ”§ 31/01/2026: MIGRATION vers study_mapping.json (Correction 4)
    // Volume Profile study avec subgraphs VAH/VAL/POC
    int STUDY_VP = STUDY_ID(barres_key, "VP");

    // VAH subgraph typiquement index 0 ou 1
    float vah_tmp = ReadStudyValue(sc, main_chart, STUDY_VP, 0);
    if (vah_tmp > 0) mq.vah = vah_tmp;

    // VAL subgraph typiquement index 1 ou 2
    float val_tmp = ReadStudyValue(sc, main_chart, STUDY_VP, 1);
    if (val_tmp > 0) mq.val = val_tmp;

    // Blind Spots (subgraphs 0-9 = BL 1-10)
    for (int i = 0; i < 9; i++) {
        mq.blind_spots[i] = ReadStudyValue(sc, main_chart, STUDY_MQ_BLINDSPOT, i);
    }

    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    // ðŸ†• 30/01/2026: CALCUL DES DISTANCES EN TICKS (comme Python: menthor_distances)
    // Ces distances sont CRITIQUES pour comprendre "pourquoi" un trade est pris/rejetÃ©
    // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    float current_price = sc.Close[sc.ArraySize - 1];
    float tick_size_mq = (mq.hvl > 10000.0f) ? 0.25f : 0.25f;  // NQ vs ES detection heuristique

    // Initialisation
    mq.dist_gex_up_ticks = 99999.0f;
    mq.dist_gex_dn_ticks = 99999.0f;
    mq.dist_blind_ticks = 99999.0f;
    mq.nearest_gex_up = 0;
    mq.nearest_gex_dn = 0;
    mq.nearest_blind = 0;

    // GEX le plus proche au-dessus et en-dessous
    for (int i = 0; i < 10; i++) {
        if (mq.gex[i] > 0) {
            float dist_ticks = (mq.gex[i] - current_price) / tick_size_mq;
            if (dist_ticks > 0 && dist_ticks < mq.dist_gex_up_ticks) {
                mq.dist_gex_up_ticks = dist_ticks;
                mq.nearest_gex_up = mq.gex[i];
            } else if (dist_ticks < 0 && (-dist_ticks) < mq.dist_gex_dn_ticks) {
                mq.dist_gex_dn_ticks = -dist_ticks;
                mq.nearest_gex_dn = mq.gex[i];
            }
        }
    }

    // Blind spot le plus proche
    for (int i = 0; i < 9; i++) {
        if (mq.blind_spots[i] > 0) {
            float dist_ticks = fabs(mq.blind_spots[i] - current_price) / tick_size_mq;
            if (dist_ticks < mq.dist_blind_ticks) {
                mq.dist_blind_ticks = dist_ticks;
                mq.nearest_blind = mq.blind_spots[i];
            }
        }
    }

    // Distances aux niveaux d'options
    mq.dist_gamma_ticks = (mq.gamma_wall > 0) ? fabs(mq.gamma_wall - current_price) / tick_size_mq : 99999.0f;
    mq.dist_call_ticks = (mq.call_resistance > 0) ? fabs(mq.call_resistance - current_price) / tick_size_mq : 99999.0f;
    mq.dist_put_ticks = (mq.put_support > 0) ? fabs(mq.put_support - current_price) / tick_size_mq : 99999.0f;

    // Convertir 99999 en 0 si non trouvÃ© (pour le log)
    if (mq.dist_gex_up_ticks >= 99999.0f) mq.dist_gex_up_ticks = 0;
    if (mq.dist_gex_dn_ticks >= 99999.0f) mq.dist_gex_dn_ticks = 0;
    if (mq.dist_blind_ticks >= 99999.0f) mq.dist_blind_ticks = 0;
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// SECTION 6.3: COLLECTE DONNÃ‰ES VOLUME PROFILE + DELTA DIVERGENCE (Chart 26/27)
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// ðŸ†• 31/01/2026: Nouvelles donnÃ©es pour amÃ©liorer les signaux
// - DELTA DIVERGENCE: Signal de retournement (prix vs delta)
// - PREVIOUS VAH/VAL/VPOC: Niveaux clÃ©s de la session prÃ©cÃ©dente
// - PREVIOUS VWAP: VWAP de la veille avec bandes SD
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

inline void CollectVolumeProfile_Data(
    SCStudyInterfaceRef sc,
    int chart_number,   // 26 pour ES, 27 pour NQ
    BN_Data& bn,        // Pour delta divergence
    MenthorQ_Data& mq,  // Pour previous levels
    bool is_nq
) {
    // ClÃ© pour study_mapping.json
    const char* vp_key = is_nq ? "NQ_VOLUME_PROFILE" : "ES_VOLUME_PROFILE";

    // === DELTA DIVERGENCE (ID:31 et ID:32) ===
    // Color Bar Based On Alert Condition: sg0 = signal actif (non-zero = divergence)
    int STUDY_DELTA_DIV_BUY = STUDY_ID(vp_key, "DELTA_DIV_BUY");
    int STUDY_DELTA_DIV_SELL = STUDY_ID(vp_key, "DELTA_DIV_SELL");

    if (STUDY_DELTA_DIV_BUY > 0) {
        float div_buy_signal = ReadStudyValue(sc, chart_number, STUDY_DELTA_DIV_BUY, 0);
        bn.delta_div_buy = (div_buy_signal != 0);
    }

    if (STUDY_DELTA_DIV_SELL > 0) {
        float div_sell_signal = ReadStudyValue(sc, chart_number, STUDY_DELTA_DIV_SELL, 0);
        bn.delta_div_sell = (div_sell_signal != 0);
    }

    // Calculer la force de la divergence (si les deux sont actifs, aucune divergence claire)
    if (bn.delta_div_buy && !bn.delta_div_sell) {
        bn.delta_div_strength = 1.0f;  // Divergence bullish forte
    } else if (bn.delta_div_sell && !bn.delta_div_buy) {
        bn.delta_div_strength = 1.0f;  // Divergence bearish forte
    } else {
        bn.delta_div_strength = 0.0f;  // Pas de divergence claire
    }

    // === PREVIOUS VPOC VAH VAL (ID:2) ===
    // Subgraphs: 0=PREV_VAH, 1=PREV_VAL, 2=PREV_VPOC (Ã  vÃ©rifier dans Sierra)
    int STUDY_PREV_LEVELS = STUDY_ID(vp_key, "PREV_VPOC_VAH_VAL");

    if (STUDY_PREV_LEVELS > 0) {
        // Note: L'ordre des subgraphs peut varier selon la config Sierra
        // Typiquement: VAH=sg1, VAL=sg2, VPOC=sg0 ou similaire
        float sg0 = ReadStudyValue(sc, chart_number, STUDY_PREV_LEVELS, 0);
        float sg1 = ReadStudyValue(sc, chart_number, STUDY_PREV_LEVELS, 1);
        float sg2 = ReadStudyValue(sc, chart_number, STUDY_PREV_LEVELS, 2);

        // DÃ©terminer quel subgraph est quoi (VAH > VPOC > VAL gÃ©nÃ©ralement)
        // On assume l'ordre standard: VAH=sg0, VAL=sg1, VPOC=sg2
        // Mais on peut aussi dÃ©tecter automatiquement
        if (sg0 > 0 && sg1 > 0) {
            if (sg0 > sg1) {
                mq.prev_vah = sg0;
                mq.prev_val = sg1;
            } else {
                mq.prev_vah = sg1;
                mq.prev_val = sg0;
            }
        }
        if (sg2 > 0) {
            mq.prev_vpoc = sg2;
        } else if (sg0 > 0 && sg1 > 0) {
            // VPOC est gÃ©nÃ©ralement entre VAH et VAL
            mq.prev_vpoc = (mq.prev_vah + mq.prev_val) / 2.0f;
        }
    }

    // === PREVIOUS VWAP + SD (ID:4) ===
    // Subgraphs: 0=VWAP, 1=+1SD, 2=-1SD
    int STUDY_PREV_VWAP = STUDY_ID(vp_key, "PREV_VWAP_SD");

    if (STUDY_PREV_VWAP > 0) {
        mq.prev_vwap = ReadStudyValue(sc, chart_number, STUDY_PREV_VWAP, 0);
        mq.prev_vwap_sd1_up = ReadStudyValue(sc, chart_number, STUDY_PREV_VWAP, 1);
        mq.prev_vwap_sd1_dn = ReadStudyValue(sc, chart_number, STUDY_PREV_VWAP, 2);
    }
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// SECTION 6.3.5: COLLECTE SWING STRUCTURE + SINGLE PRINTS (Chart 28/29)
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// ðŸ†• 31/01/2026: Nouvelles donnÃ©es de structure de marchÃ©
// - SWING HIGH/LOW: Points pivots pour identifier la tendance (HH, HL, LH, LL)
// - COLOR BAR DELTA: Direction du flux d'ordres sur chaque barre
// - SINGLE PRINTS: Zones de faiblesse (creux de volume = gaps potentiels)
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

inline void CollectSwingStructure_Data(
    SCStudyInterfaceRef sc,
    int chart_number,   // 28 pour ES, 29 pour NQ
    BN_Data& bn,
    float current_price,
    bool is_nq
) {
    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 02/02/2026: STUDY IDs HARDCODÉS (inventaire Charts 28/29)
    // Ces Study IDs sont identiques sur ES (Chart 28) et NQ (Chart 29)
    // ═══════════════════════════════════════════════════════════════════════════
    const int STUDY_SWING = 6;           // Swing High/Low
    const int STUDY_VP_SESSION = 35;     // Volume Profile Session (VBP)
    const int STUDY_DELTA_BAR = 4;       // Color Bar Delta (optionnel)

    // 🔧 DEBUG: Log pour vérifier que la fonction est appelée et les valeurs lues
    SCString debug_msg;
    debug_msg.Format("📊 CollectSwingStructure Chart=%d %s: ", chart_number, is_nq ? "NQ" : "ES");

    // === SWING HIGH/LOW (Study 6) ===
    // Subgraphs: sg0 = Swing High, sg1 = Swing Low
    if (STUDY_SWING > 0) {
        float swing_high = ReadStudyValue(sc, chart_number, STUDY_SWING, 0);
        float swing_low = ReadStudyValue(sc, chart_number, STUDY_SWING, 1);

        // Log des valeurs brutes
        SCString swing_log;
        swing_log.Format("Swing[Study6] H=%.2f L=%.2f | ", swing_high, swing_low);
        debug_msg += swing_log;

        // Ne stocker que si valide (non-zero et cohérent)
        if (swing_high > 0 && swing_high > current_price * 0.9f) {
            bn.swing_high = swing_high;
        }
        if (swing_low > 0 && swing_low < current_price * 1.1f) {
            bn.swing_low = swing_low;
        }
    }

    // === COLOR BAR DELTA (Study 4) ===
    // Color Bar Based On Above/Below Study
    // sg0 = signal couleur (positif = bullish, négatif = bearish)
    if (STUDY_DELTA_BAR > 0) {
        float delta_signal = ReadStudyValue(sc, chart_number, STUDY_DELTA_BAR, 0);

        // Interprétation: valeur > 0 = bullish (acheteurs dominent)
        if (delta_signal > 0) {
            bn.delta_bar_bullish = true;
            bn.delta_bar_bearish = false;
        } else if (delta_signal < 0) {
            bn.delta_bar_bullish = false;
            bn.delta_bar_bearish = true;
        } else {
            bn.delta_bar_bullish = false;
            bn.delta_bar_bearish = false;
        }
    }

    // === VOLUME PROFILE SESSION (Study 35) ===
    // D'après l'inventaire: SG1=VPOC, SG2=VAH, SG3=VAL, SG4=VWAP, SG17=HVN, SG18=LVN
    // NOTE: SG0 est vide, les données commencent à SG1

    if (STUDY_VP_SESSION > 0) {
        // POC, VAH, VAL de la session actuelle (indices corrigés!)
        bn.session_vpoc = ReadStudyValue(sc, chart_number, STUDY_VP_SESSION, 1);  // SG1 = VPOC
        bn.session_vah = ReadStudyValue(sc, chart_number, STUDY_VP_SESSION, 2);   // SG2 = VAH
        bn.session_val = ReadStudyValue(sc, chart_number, STUDY_VP_SESSION, 3);   // SG3 = VAL
        bn.session_vwap_vp = ReadStudyValue(sc, chart_number, STUDY_VP_SESSION, 4);  // SG4 = VWAP
        bn.session_hvn = ReadStudyValue(sc, chart_number, STUDY_VP_SESSION, 17);  // SG17 = HVN
        bn.session_lvn = ReadStudyValue(sc, chart_number, STUDY_VP_SESSION, 18);  // SG18 = LVN

        // Log VP Session values
        SCString vp_log;
        vp_log.Format("VP[35] POC=%.2f VAH=%.2f VAL=%.2f HVN=%.2f LVN=%.2f",
                      bn.session_vpoc, bn.session_vah, bn.session_val, bn.session_hvn, bn.session_lvn);
        debug_msg += vp_log;

        // Alias pour compatibilité
        bn.session_poc = bn.session_vpoc;

        // Single Prints (zones de faiblesse - les traits bleus = LVN)
        // ðŸ†• 30/01/2026: CAPTURER SEULEMENT LES LVN PROCHES DU PRIX (zone pertinente)
        bn.num_lvn = 0;
        for (int i = 0; i < 10; i++) {
            bn.lvn_levels[i] = 0;
        }

        // Zone pertinente: Â±200 ticks autour du prix (NQ: Â±50pts, ES: Â±50pts)
        float proximity_range = is_nq ? 50.0f : 50.0f;  // 50 points = ~200 ticks
        float min_price = current_price - proximity_range;
        float max_price = current_price + proximity_range;

        // Scanner les subgraphs 3 Ã  12 pour les LVN proches du prix
        for (int sg = 3; sg < 13; sg++) {
            float lvn = ReadStudyValue(sc, chart_number, STUDY_VP_SESSION, sg);
            // Garder seulement si dans la zone pertinente et pas trop loin
            if (lvn > min_price && lvn < max_price && bn.num_lvn < 10) {
                bn.lvn_levels[bn.num_lvn] = lvn;
                bn.num_lvn++;
            }
        }

        // Trier les LVN par distance au prix (les plus proches en premier)
        for (int i = 0; i < bn.num_lvn - 1; i++) {
            for (int j = i + 1; j < bn.num_lvn; j++) {
                float dist_i = fabs(bn.lvn_levels[i] - current_price);
                float dist_j = fabs(bn.lvn_levels[j] - current_price);
                if (dist_j < dist_i) {
                    // Swap
                    float tmp = bn.lvn_levels[i];
                    bn.lvn_levels[i] = bn.lvn_levels[j];
                    bn.lvn_levels[j] = tmp;
                }
            }
        }

        // CompatibilitÃ©: single_print_high/low = les 2 LVN les plus proches
        if (bn.num_lvn >= 1) {
            bn.single_print_high = bn.lvn_levels[0];
        }
        if (bn.num_lvn >= 2) {
            bn.single_print_low = bn.lvn_levels[1];
        }

        // Trouver les LVN les plus proches au-dessus et en-dessous du prix
        bn.nearest_lvn_above = 0;
        bn.nearest_lvn_below = 0;
        float min_dist_above = 999999.0f;
        float min_dist_below = 999999.0f;

        for (int i = 0; i < bn.num_lvn; i++) {
            float lvn = bn.lvn_levels[i];
            if (lvn > current_price) {
                // LVN au-dessus
                float dist = lvn - current_price;
                if (dist < min_dist_above) {
                    min_dist_above = dist;
                    bn.nearest_lvn_above = lvn;
                }
            } else if (lvn < current_price) {
                // LVN en-dessous
                float dist = current_price - lvn;
                if (dist < min_dist_below) {
                    min_dist_below = dist;
                    bn.nearest_lvn_below = lvn;
                }
            }
        }

        // Calculer si le prix est proche d'un LVN
        float proximity_threshold = is_nq ? 15.0f : 3.0f;  // 15 pts NQ, 3 pts ES

        bn.near_single_print = false;
        if (bn.nearest_lvn_above > 0 && (bn.nearest_lvn_above - current_price) < proximity_threshold) {
            bn.near_single_print = true;
        }
        if (bn.nearest_lvn_below > 0 && (current_price - bn.nearest_lvn_below) < proximity_threshold) {
            bn.near_single_print = true;
        }

        // ðŸ†• 30/01/2026: CALCUL DES DISTANCES EN TICKS (comme GEX/Blind)
        float tick_size_vp = is_nq ? 0.25f : 0.25f;

        // Distance au LVN le plus proche (au-dessus ou en-dessous)
        bn.dist_single_print_ticks = 99999.0f;
        if (bn.nearest_lvn_above > 0) {
            float dist = (bn.nearest_lvn_above - current_price) / tick_size_vp;
            if (dist < bn.dist_single_print_ticks) bn.dist_single_print_ticks = dist;
        }
        if (bn.nearest_lvn_below > 0) {
            float dist = (current_price - bn.nearest_lvn_below) / tick_size_vp;
            if (dist < bn.dist_single_print_ticks) bn.dist_single_print_ticks = dist;
        }
        if (bn.dist_single_print_ticks >= 99999.0f) bn.dist_single_print_ticks = 0;

        // Distances spÃ©cifiques au-dessus/en-dessous
        bn.dist_lvn_above_ticks = (bn.nearest_lvn_above > 0) ? (bn.nearest_lvn_above - current_price) / tick_size_vp : 0;
        bn.dist_lvn_below_ticks = (bn.nearest_lvn_below > 0) ? (current_price - bn.nearest_lvn_below) / tick_size_vp : 0;

        // Distances aux niveaux de session
        bn.dist_session_poc_ticks = (bn.session_poc > 0) ? fabs(bn.session_poc - current_price) / tick_size_vp : 0;
        bn.dist_session_vah_ticks = (bn.session_vah > 0) ? fabs(bn.session_vah - current_price) / tick_size_vp : 0;
        bn.dist_session_val_ticks = (bn.session_val > 0) ? fabs(bn.session_val - current_price) / tick_size_vp : 0;
    }

    // 🔧 DEBUG: Afficher le log (une seule fois par minute pour éviter spam)
    static int last_log_minute = -1;
    SCDateTime now = sc.CurrentSystemDateTime;
    int current_minute = now.GetMinute();
    if (current_minute != last_log_minute) {
        last_log_minute = current_minute;
        sc.AddMessageToLog(debug_msg, 0);
    }
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// SECTION 6.4: CALCUL NEXT_WALL (PARITÃ‰ PYTHON)
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// next_wall = niveau MenthorQ le plus important ET le plus proche du prix actuel
// PrioritÃ©: HVL (5pts), GEX_TOP (4pts), Put/Call (3pts), Gamma Wall (3pts)

inline void CalculateNextWall(MenthorQ_Data& mq, float current_price) {
    // Structure pour stocker les candidats
    struct WallCandidate {
        float price;
        int importance;  // Points d'importance
        int side;        // 0=call/resist, 1=put/support
    };

    std::vector<WallCandidate> candidates;

    // HVL - importance max (5 points)
    if (mq.hvl > 0) {
        int side = (mq.hvl > current_price) ? 0 : 1;  // Au-dessus = rÃ©sistance
        candidates.push_back({mq.hvl, 5, side});
    }
    if (mq.hvl_0dte > 0 && fabs(mq.hvl_0dte - mq.hvl) > 1.0f) {
        int side = (mq.hvl_0dte > current_price) ? 0 : 1;
        candidates.push_back({mq.hvl_0dte, 5, side});
    }

    // GEX TOP 1-3 (4 points)
    for (int i = 0; i < 3; i++) {
        if (mq.gex[i] > 0) {
            int side = (mq.gex[i] > current_price) ? 0 : 1;
            candidates.push_back({mq.gex[i], 4, side});
        }
    }

    // Call/Put Resistance/Support (3 points)
    if (mq.call_resistance > 0) {
        candidates.push_back({mq.call_resistance, 3, 0});  // Toujours rÃ©sistance
    }
    if (mq.put_support > 0) {
        candidates.push_back({mq.put_support, 3, 1});  // Toujours support
    }
    if (mq.call_resistance_0dte > 0 && fabs(mq.call_resistance_0dte - mq.call_resistance) > 1.0f) {
        candidates.push_back({mq.call_resistance_0dte, 3, 0});
    }
    if (mq.put_support_0dte > 0 && fabs(mq.put_support_0dte - mq.put_support) > 1.0f) {
        candidates.push_back({mq.put_support_0dte, 3, 1});
    }

    // Gamma Walls (3 points)
    if (mq.gamma_wall > 0) {
        int side = (mq.gamma_wall > current_price) ? 0 : 1;
        candidates.push_back({mq.gamma_wall, 3, side});
    }
    if (mq.gamma_wall_0dte > 0 && fabs(mq.gamma_wall_0dte - mq.gamma_wall) > 1.0f) {
        int side = (mq.gamma_wall_0dte > current_price) ? 0 : 1;
        candidates.push_back({mq.gamma_wall_0dte, 3, side});
    }

    // ðŸ†• 31/01/2026: PREVIOUS LEVELS (4 points - trÃ¨s importants!)
    // Previous VAH = rÃ©sistance, Previous VAL = support, Previous VPOC = pivot
    if (mq.prev_vah > 0) {
        candidates.push_back({mq.prev_vah, 4, 0});  // Toujours rÃ©sistance
    }
    if (mq.prev_val > 0) {
        candidates.push_back({mq.prev_val, 4, 1});  // Toujours support
    }
    if (mq.prev_vpoc > 0) {
        int side = (mq.prev_vpoc > current_price) ? 0 : 1;  // Pivot = dÃ©pend position prix
        candidates.push_back({mq.prev_vpoc, 4, side});
    }

    // Trouver le next_wall: le niveau le plus proche avec importance max
    // Formule: score = importance / (1 + distance_ticks/10)
    float best_score = 0;
    int best_idx = -1;

    for (size_t i = 0; i < candidates.size(); i++) {
        float distance = fabs(candidates[i].price - current_price);
        float score = candidates[i].importance / (1.0f + distance / 10.0f);

        if (score > best_score) {
            best_score = score;
            best_idx = i;
        }
    }

    // Assigner le next_wall
    if (best_idx >= 0) {
        mq.next_wall_price = candidates[best_idx].price;
        mq.next_wall_strength = best_score / 5.0f;  // Normaliser sur 1.0
        mq.next_wall_side = candidates[best_idx].side;
    } else {
        mq.next_wall_price = 0;
        mq.next_wall_strength = 0;
        mq.next_wall_side = 0;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 01/02/2026: COLLECTE COMPOSITE PROFILES MULTI-PÉRIODES (Charts 30/31)
// ═══════════════════════════════════════════════════════════════════════════════
// Collecte les données des 5 COMPOSITE PROFILES (1j, 20j, 50j, 100j, 200j)
// Usage: LVN = cibles TP (prix traverse vite), HVN = protection SL (prix stable)

// Collecte UN SEUL profile (une période)
inline void CollectSingleProfile(SCStudyInterfaceRef sc, int chart_number, int study_id,
                                  int period_days, float current_price, float tick_size,
                                  SingleProfile& profile) {
    profile.period_days = period_days;
    profile.valid = false;
    profile.vpoc = 0;
    profile.vah = 0;
    profile.val = 0;
    profile.vwap = 0;
    profile.hvn = 0;
    profile.lvn = 0;
    profile.dist_vpoc_ticks = 9999.0f;
    profile.dist_vah_ticks = 9999.0f;
    profile.dist_val_ticks = 9999.0f;
    profile.dist_hvn_ticks = 9999.0f;
    profile.dist_lvn_ticks = 9999.0f;

    // Lire les valeurs via ReadStudyValue
    profile.vpoc = ReadStudyValue(sc, chart_number, study_id, CP_SG_VPOC);
    profile.vah  = ReadStudyValue(sc, chart_number, study_id, CP_SG_VAH);
    profile.val  = ReadStudyValue(sc, chart_number, study_id, CP_SG_VAL);
    profile.vwap = ReadStudyValue(sc, chart_number, study_id, CP_SG_VWAP);
    profile.hvn  = ReadStudyValue(sc, chart_number, study_id, CP_SG_HVN);
    profile.lvn  = ReadStudyValue(sc, chart_number, study_id, CP_SG_LVN);

    // Vérifier validité (au moins VPOC doit être > 0)
    if (profile.vpoc > 0 && tick_size > 0) {
        profile.valid = true;

        // Calculer les distances en ticks
        profile.dist_vpoc_ticks = (profile.vpoc - current_price) / tick_size;
        profile.dist_vah_ticks  = (profile.vah - current_price) / tick_size;
        profile.dist_val_ticks  = (profile.val - current_price) / tick_size;

        if (profile.hvn > 0) {
            profile.dist_hvn_ticks = (profile.hvn - current_price) / tick_size;
        }

        if (profile.lvn > 0) {
            profile.dist_lvn_ticks = (profile.lvn - current_price) / tick_size;
        }
    }
}

// Collecte TOUS les profiles (5 périodes)
inline void CollectCompositeProfile_Data(SCStudyInterfaceRef sc, int chart_number,
                                          float current_price, float tick_size,
                                          CompositeProfile_Data& cp) {
    // Reset complet
    memset(&cp, 0, sizeof(CompositeProfile_Data));
    cp.nearest_lvn_above = 0;
    cp.nearest_lvn_below = 0;
    cp.nearest_hvn_above = 0;
    cp.nearest_hvn_below = 0;
    cp.dist_nearest_lvn_above_ticks = 9999.0f;
    cp.dist_nearest_lvn_below_ticks = 9999.0f;
    cp.dist_nearest_hvn_above_ticks = 9999.0f;
    cp.dist_nearest_hvn_below_ticks = 9999.0f;

    // Collecter chaque période
    CollectSingleProfile(sc, chart_number, CP_STUDY_1D,   1,   current_price, tick_size, cp.p1d);
    CollectSingleProfile(sc, chart_number, CP_STUDY_20D,  20,  current_price, tick_size, cp.p20d);
    CollectSingleProfile(sc, chart_number, CP_STUDY_50D,  50,  current_price, tick_size, cp.p50d);
    CollectSingleProfile(sc, chart_number, CP_STUDY_100D, 100, current_price, tick_size, cp.p100d);
    CollectSingleProfile(sc, chart_number, CP_STUDY_200D, 200, current_price, tick_size, cp.p200d);

    // Tableau pour itérer facilement
    SingleProfile* profiles[] = { &cp.p1d, &cp.p20d, &cp.p50d, &cp.p100d, &cp.p200d };
    int periods[] = { 1, 20, 50, 100, 200 };

    // Trouver les niveaux les plus proches (toutes périodes confondues)
    for (int i = 0; i < 5; i++) {
        SingleProfile* p = profiles[i];
        if (!p->valid) continue;

        // LVN au-dessus du prix actuel
        if (p->lvn > current_price && p->lvn > 0) {
            float dist = (p->lvn - current_price) / tick_size;
            if (dist < cp.dist_nearest_lvn_above_ticks) {
                cp.nearest_lvn_above = p->lvn;
                cp.dist_nearest_lvn_above_ticks = dist;
                cp.nearest_lvn_above_period = periods[i];
            }
        }
        // LVN en-dessous du prix actuel
        else if (p->lvn < current_price && p->lvn > 0) {
            float dist = (current_price - p->lvn) / tick_size;
            if (dist < cp.dist_nearest_lvn_below_ticks) {
                cp.nearest_lvn_below = p->lvn;
                cp.dist_nearest_lvn_below_ticks = dist;
                cp.nearest_lvn_below_period = periods[i];
            }
        }

        // HVN au-dessus du prix actuel
        if (p->hvn > current_price && p->hvn > 0) {
            float dist = (p->hvn - current_price) / tick_size;
            if (dist < cp.dist_nearest_hvn_above_ticks) {
                cp.nearest_hvn_above = p->hvn;
                cp.dist_nearest_hvn_above_ticks = dist;
                cp.nearest_hvn_above_period = periods[i];
            }
        }
        // HVN en-dessous du prix actuel
        else if (p->hvn < current_price && p->hvn > 0) {
            float dist = (current_price - p->hvn) / tick_size;
            if (dist < cp.dist_nearest_hvn_below_ticks) {
                cp.nearest_hvn_below = p->hvn;
                cp.dist_nearest_hvn_below_ticks = dist;
                cp.nearest_hvn_below_period = periods[i];
            }
        }
    }

    // Calculer confluence (combien de périodes ont LVN/HVN proches)
    const float CONFLUENCE_THRESHOLD = 5.0f; // 5 ticks de tolérance

    for (int i = 0; i < 5; i++) {
        SingleProfile* p1 = profiles[i];
        if (!p1->valid || p1->lvn <= 0) continue;

        for (int j = i + 1; j < 5; j++) {
            SingleProfile* p2 = profiles[j];
            if (!p2->valid) continue;

            // LVN proche entre deux périodes?
            if (p2->lvn > 0) {
                float dist_lvn = fabs(p1->lvn - p2->lvn) / tick_size;
                if (dist_lvn < CONFLUENCE_THRESHOLD) {
                    cp.lvn_confluence_count++;
                    if (cp.strongest_lvn == 0) {
                        cp.strongest_lvn = (p1->lvn + p2->lvn) / 2.0f;
                    }
                }
            }

            // HVN proche entre deux périodes?
            if (p1->hvn > 0 && p2->hvn > 0) {
                float dist_hvn = fabs(p1->hvn - p2->hvn) / tick_size;
                if (dist_hvn < CONFLUENCE_THRESHOLD) {
                    cp.hvn_confluence_count++;
                    if (cp.strongest_hvn == 0) {
                        cp.strongest_hvn = (p1->hvn + p2->hvn) / 2.0f;
                    }
                }
            }
        }
    }
}
