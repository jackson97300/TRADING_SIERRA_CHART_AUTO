#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// DMP_Reader.h  —  MIA Data Dumper G3 : Section A — LECTURE SIERRA CHART
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Rôle   : Lire TOUS les subgraphs nécessaires depuis Sierra Chart et les
//           stocker dans DMP_RawData. Aucun calcul ici — seulement de la
//           lecture robuste avec gestion des erreurs.
//
//  Règle  : UN seul endroit pour les Study IDs. Si Sierra Chart change un ID,
//           on modifie ici et ici seulement. Le reste du dumper ne connaît
//           que des noms symboliques.
//
//  Auteur : MIA Trading System
//  Date   : 2026-02-28
//  Build  : G3-Unifier v1.0
//
//  ⚠️  CE FICHIER EST PARTAGÉ BOT + DUMPER — Ne pas y mettre de logique trading.
//
// ═══════════════════════════════════════════════════════════════════════════════

#include "DMP_Config.h"     // sierrachart.h + constantes minimales du Dumper
#include <cfloat>           // FLT_MAX
#include <cmath>            // std::isfinite
#include <cstring>          // memset
#include <ctime>            // gmtime_s, time_t — conversion UTC→ET

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — CONSTANTES CHARTS & STUDIES
// ═══════════════════════════════════════════════════════════════════════════════
// ⚠️  À synchroniser avec study_mapping.json pour les IDs partagés avec le bot.
//     Les IDs propres au dumper (Charts 26-31) sont définis ici uniquement.

namespace DMP_Charts {

    // ── Footprints ─────────────────────────────────────────────────────────────
    constexpr int ES_FP           =  1;   // ES Footprint - Bataille Navale
    constexpr int NQ_FP           =  2;   // NQ Footprint - Bataille Navale

    // ── Contexte global ────────────────────────────────────────────────────────
    constexpr int VIX_MQ          = 15;   // VIX avec MenthorQ Gamma

    // ── Daily (ATR + VWAP Weekly/Monthly) ──────────────────────────────────────
    constexpr int ES_DAILY        = 16;   // ES Daily — ATR, MA, VWAP W/M
    constexpr int NQ_DAILY        = 17;   // NQ Daily — ATR, MA, VWAP W/M

    // ── Barres 1min (MenthorQ + Blind Spots + VWAP + Session) ─────────────────
    constexpr int NQ_BARRES       = 23;   // NQ 1min Barres
    constexpr int ES_BARRES       = 25;   // ES 1min Barres

    // ── Volume Profile courant + Précédent ────────────────────────────────────
    constexpr int ES_VP           = 26;   // ES Volume Profile
    constexpr int NQ_VP           = 27;   // NQ Volume Profile

    // ── CVD + Swing + VP session ──────────────────────────────────────────────
    constexpr int ES_CVD          = 28;   // ES CVD & Swing
    constexpr int NQ_CVD          = 29;   // NQ CVD & Swing

    // ── Composite Profiles ───────────────────────────────────────────────────
    // ⚠️  CRITIQUE : Chart 30 = NQ (NQH26-CME), Chart 31 = ES (ESH26-CME)
    //     L'ordre est INVERSÉ par rapport à ce qu'on aurait pu supposer.
    //     Confirmé par le scan JSON (chart_30.json = NQH26, chart_31.json = ESH26).
    constexpr int ES_COMPOSITE    = 31;   // ES Composite Profiles + MQ Gamma ES
    constexpr int NQ_COMPOSITE    = 30;   // NQ Composite Profiles + MQ Blind Spots NQ !

    // ── Footprints secondaires (FPBS complet) ─────────────────────────────
    // 🆕 FIX 31/03/2026 : Les FPBS sur charts 1/2 ont sg10+ morts (settings).
    //    Charts 33/34 ont le FPBS VOLUME (study 9) avec 54 sg fonctionnels.
    //    Mapping subgraphs 100% identique (vérifié par scan JSON).
    constexpr int ES_FP2          = 33;   // ES Footprint secondaire (FPBS complet)
    constexpr int NQ_FP2          = 34;   // NQ Footprint secondaire (FPBS complet)

} // namespace DMP_Charts

// ─────────────────────────────────────────────────────────────────────────────

namespace DMP_Studies {

    // ── Chart 1 ES_FOOTPRINT ──────────────────────────────────────────────────
    struct ES_FP {
        constexpr static int FPBS         = 31;   // NBCV originale (sg basiques), sg avancés via VAP
        constexpr static int VWAP_DAY     = 62;   // VWAP journalier (sg0=V, sg1=+1σ, sg2=-1σ)
        constexpr static int ROTATION     = 12;   // Rotation Reversal Bar
        constexpr static int ROTATION_UP  = 19;   // [AV] Rotation Up
        constexpr static int ROTATION_DN  = 20;   // [AV] Rotation Down
        constexpr static int OPEN_830     = 14;   // Open 08h30 ET
        constexpr static int HH_SESSION   = 15;   // Higher High session (sg1=High)
        constexpr static int LL_SESSION   = 16;   // Lower Low session  (sg2=Low)
        constexpr static int COLOR_UP     = 56;   // [AV] Color Zone Up — pullback simple (O[1]<C, H>L[1]+12t)
        constexpr static int COLOR_DN     = 57;   // [AV] Color Zone Down — pullback simple
        constexpr static int COLOR_UP_2   = 104;  // [AV] Color Zone Up 2 — double stacké + higher lows (continuation)
        constexpr static int COLOR_DN_2   = 105;  // [AV] Color Zone Down 2 — double stacké + lower highs
        constexpr static int ABSORB_ASK   = 25;   // [AV] Absorption Ask
        constexpr static int ABSORB_BID   = 26;   // [AV] Absorption Bid
        constexpr static int LONG_UP      = 21;   // [AV] Long Up Bar
        constexpr static int LONG_DN      = 22;   // [AV] Long Down Bar
        constexpr static int DOUBLE_ASK   = 28;   // [AV] Double Ask
        constexpr static int DOUBLE_BID   = 27;   // [AV] Double Bid
        constexpr static int ASK_100      = 102;  // Ask +100 lots (sg0-9) — fix scan 02/03/2026
        constexpr static int BID_100      = 103;  // Bid +100 lots (sg0-9) — fix scan 02/03/2026
        // 🆕 BUG #9 — Tous les seuils Big Orders ES (04/03/2026)
        constexpr static int ASK_150      =   6;  // Ask +150 lots
        constexpr static int BID_150      =   7;  // Bid +150 lots
        constexpr static int ASK_400      =   8;  // Ask +400 lots
        constexpr static int BID_400      =   9;  // Bid +400 lots
        constexpr static int ASK_1000     =  29;  // Ask +1000 lots
        constexpr static int BID_1000     =  30;  // Bid +1000 lots
        // 🆕 BUG #10 — Edge Zones Footprint ES (05/03/2026)
        constexpr static int EDGE_BUY     =  32;  // EDGE ZONES IMB BUY 600%DIAG (principal Bot)
        constexpr static int EDGE_SELL    =  35;  // EDGE ZONES IMB SELL 600%DIAG (principal Bot)
        constexpr static int EDGE_BUY_R1  =  52;  // EDGE ZONES IMB BUY rev1 800%DIAG
        constexpr static int EDGE_SELL_R1 =  53;  // EDGE ZONES IMB SELL rev1 800%DIAG
        // 🆕 12/03/2026 — Volume UP/DOWN ES (ajoutés manuellement dans SC)
        constexpr static int VOLUME_UP    =   2;  // [AV] VOLUME UP  — =AND(O>C[-1], V>1200)
        constexpr static int VOLUME_DN    =   4;  // [AV] VOLUME DOWN — =AND(O<C[-1], V>1200)
        constexpr static int EDGE_BUY_R2  =  42;  // EDGE ZONES IMB BUY rev2 800%DIAG
        constexpr static int EDGE_SELL_R2 =  41;  // EDGE ZONES IMB SELL rev2 800%DIAG
        constexpr static int EDGE_BUY_R3  =  98;  // EDGE ZONES IMB BUY rev3 800%DIAG
        constexpr static int EDGE_SELL_R3 =  99;  // EDGE ZONES IMB SELL rev3 800%DIAG
        constexpr static int CLUSTER      = 10;   // Cluster Volume
    };

    // ── Chart 2 NQ_FOOTPRINT ──────────────────────────────────────────────────
    struct NQ_FP {
        constexpr static int FPBS         = 33;   // NBCV originale (sg basiques), sg avancés via VAP
        constexpr static int VWAP_DAY     = 57;   // VWAP journalier
        constexpr static int ROTATION     = 14;   // Rotation Reversal Bar
        constexpr static int ROTATION_UP  = 21;   // [AV] Rotation Up
        constexpr static int ROTATION_DN  = 22;   // [AV] Rotation Down
        constexpr static int OPEN_830     = 16;   // Open 08h30 ET
        constexpr static int HH_SESSION   = 17;   // Higher High session
        constexpr static int LL_SESSION   = 18;   // Lower Low session
        constexpr static int COLOR_UP     = 53;   // [AV] Color Zone Up — pullback simple
        constexpr static int COLOR_DN     = 54;   // [AV] Color Zone Down — pullback simple
        constexpr static int COLOR_UP_2   =   3;  // [AV] Color Zone Up 2 — double stacké + higher lows
        constexpr static int COLOR_DN_2   =   5;  // [AV] Color Zone Down 2 — double stacké + lower highs
        constexpr static int ABSORB_ASK   = 29;   // [AV] Absorption Ask
        constexpr static int ABSORB_BID   = 30;   // [AV] Absorption Bid
        constexpr static int LONG_UP      = 23;   // [AV] Long Up Bar
        constexpr static int LONG_DN      = 24;   // [AV] Long Down Bar
        constexpr static int TRIPLE_ASK   = 28;   // [AV] Triple Ask (NQ = Triple, pas Double)
        constexpr static int TRIPLE_BID   = 27;   // [AV] Triple Bid
        constexpr static int MQ_GAMMA     =  6;   // MenthorQ Gamma (NQ)
        constexpr static int MQ_BLIND     =  7;   // MenthorQ Blind Spots (NQ)
        constexpr static int VWAP_NAMED   = 13;   // VWAP nommé (sg0=VWAP, sg1=SD+1...)
        // ⚠️ FIX 04/03/2026 BUG #1 : Big Orders NQ étaient exclus à tort
        constexpr static int ASK_100      = 31;   // Ask +100 lots (study_mapping NQ_FOOTPRINT)
        constexpr static int BID_100      = 32;   // Bid +100 lots (study_mapping NQ_FOOTPRINT)
        // 🆕 BUG #9 — Tous les seuils Big Orders NQ (04/03/2026)
        constexpr static int ASK_10       =   8;  // Ask +10 lots
        constexpr static int BID_10       =   9;  // Bid +10 lots
        constexpr static int ASK_30       =  10;  // Ask +30 lots
        constexpr static int BID_30       =  11;  // Bid +30 lots
        // 🆕 BUG #10 — Volume Up/Down + Edge Zones Footprint (05/03/2026)
        constexpr static int VOLUME_UP    =  35;  // [AV] VOLUME UP (NQ uniquement)
        constexpr static int VOLUME_DN    =  36;  // [AV] VOLUME DOWN (NQ uniquement)
        constexpr static int EDGE_BUY     =  55;  // EDGE ZONES IMB BUY rev8 0DIAG
        constexpr static int EDGE_SELL    =  56;  // EDGE ZONES IMB SELL rev8 0DIAG
        constexpr static int EDGE_BUY_2   =   4;  // EDGE ZONES IMB BUY 0DIAG (2ème variante)
        constexpr static int EDGE_SELL_2  =   2;  // EDGE ZONES IMB SELL 0DIAG (2ème variante)
        constexpr static int CLUSTER      =  12;  // Cluster Volume (60 subgraphs = prix triggers)
    };

    // ── Chart 15 VIX_MQ ───────────────────────────────────────────────────────
    struct VIX {
        constexpr static int MQ_GAMMA     =  2;   // MenthorQ Gamma sur VIX
                                                   // sg0=Call, sg1=Put, sg2=HVL
                                                   // sg9-sg18=GEX1-GEX10
    };

    // ── Chart 16 ES_DAILY ─────────────────────────────────────────────────────
    struct ES_DAILY {
        constexpr static int ATR          =  1;   // Average True Range (sg0)
        constexpr static int MA           =  3;   // Moving Averages (sg0=MA1, sg1=MA2)
        // VWAP_WEEKLY/MONTHLY SUPPRIMÉS — maintenant lus depuis ES_BARRES (chart 25)
    };

    // ── Chart 17 NQ_DAILY ─────────────────────────────────────────────────────
    struct NQ_DAILY {
        constexpr static int ATR          =  1;   // Average True Range (sg0)
        constexpr static int MA           =  3;   // Moving Averages
        // VWAP_WEEKLY/MONTHLY SUPPRIMÉS — maintenant lus depuis NQ_BARRES (chart 23)
    };

    // ── Chart 25 ES_BARRES ────────────────────────────────────────────────────
    struct ES_BARRES {
        constexpr static int VWAP_DAY     =  1;   // VWAP journalier (sg0=V, sg1=+1σ, sg2=-1σ)
        constexpr static int MQ_GAMMA     =  2;   // MenthorQ Gamma ES
        constexpr static int MQ_BLIND     = 22;   // MenthorQ Blind Spots ES (sg0-9=BL1-10)
        constexpr static int VWAP_WEEKLY  = 23;   // VWAP Weekly intraday (sg0=VWAP, sg1=SD+1, sg2=SD-1)
        constexpr static int VWAP_MONTHLY = 33;   // VWAP Monthly intraday (idem)
        // ⚠️ FIX 11/03/2026 — Study NUMBER (position 1-based) pour GetStudyArrayFromChart
        //  GetStudyArrayFromChartUsingID ne distingue pas 2 VWAP (même type étude)
        //  Positions vérifiées par chart scan du 11/03/2026
        constexpr static int VWAP_WEEKLY_NUM  = 2;  // Confirmé par VWAP_Probe 12/03/2026 (val=6752 ✅)
        constexpr static int VWAP_MONTHLY_NUM = 3;  // Confirmé par VWAP_Probe 12/03/2026 (val=6795 ✅)
        constexpr static int HH_SESSION   =  8;   // Higher High session (sg1=High)
        constexpr static int LL_SESSION   =  9;   // Lower Low session   (sg2=Low)
        constexpr static int HH_CASH      = 32;   // 🔧 FIX Bug #18 (17/03/2026): High/Low for Time Period 9:30-10:30 ET
        constexpr static int LL_CASH      = 32;   // ← MÊME study ID, sg1=High sg2=Low (gèle à 10:30)
        constexpr static int OPEN_830     = 14;   // Open 08h30 ET (sg0=Open)
        // 🆕 BUG #8 — Signaux BN Chart Barres (04/03/2026)
        constexpr static int COLOR_UP     = 24;   // [AV] COLOR UP — sg0=prix, sg1=extension
        constexpr static int COLOR_DN     = 25;   // [AV] COLOR DOWN — sg0=prix, sg1=extension
        constexpr static int LONG_UP_BAR  = 18;   // [AV] LONG UP BAR (rectangle vert Edge Zone)
        constexpr static int LONG_DN_BAR  = 17;   // [AV] LONG DOWN BAR (rectangle rouge Edge Zone)
        constexpr static int LONG_DN_UP   = 38;   // [AV] LONG DOWN UP BAR ROND JAUNE (reversal bull)
        constexpr static int LONG_UP_DN   = 39;   // [AV] LONG UP DOWN BAR ROND JAUNE (reversal bear)
        constexpr static int EDGE_BUY     = 16;   // EDGE ZONES IMBALANCE BUY 600%DIAG
        constexpr static int EDGE_SELL    = 44;   // EDGE ZONES IMBALANCE SELL 600%DIAG
        constexpr static int DOUBLE_ASK   = 41;   // [AV] DOUBLE ASK
        constexpr static int DOUBLE_BID   = 42;   // [AV] DOUBLE BID
    };

    // ── Chart 23 NQ_BARRES ────────────────────────────────────────────────────
    struct NQ_BARRES {
        constexpr static int VWAP_DAY     =  1;   // VWAP journalier
        constexpr static int MQ_GAMMA     = 25;   // MenthorQ Gamma NQ (sg0-sg18)
        constexpr static int VWAP_WEEKLY  = 43;   // VWAP Weekly intraday (sg0=VWAP, sg1=SD+1, sg2=SD-1)
        constexpr static int VWAP_MONTHLY = 41;   // VWAP Monthly intraday (idem)
        // ⚠️ FIX 11/03/2026 — Study NUMBER (position 1-based) pour GetStudyArrayFromChart
        constexpr static int VWAP_WEEKLY_NUM  = 2;  // Par analogie avec ES (pos=4 retournait null)
        constexpr static int VWAP_MONTHLY_NUM = 3;  // Confirmé par données 12/03 (val=24832 ≈ chart 24837 ✅)
        constexpr static int HH_SESSION   =  8;   // Higher High session (sg1)
        constexpr static int LL_SESSION   =  9;   // Lower Low session   (sg2)
        constexpr static int HH_CASH      = 44;   // 🔧 FIX Bug #18 (17/03/2026): High/Low for Time Period 9:30-10:30 ET
        constexpr static int LL_CASH      = 44;   // ← MÊME study ID, sg1=High sg2=Low (gèle à 10:30)
        constexpr static int OPEN_830     = 14;   // Open 08h30 ET
        // 🆕 BUG #8 — Signaux BN Chart Barres (04/03/2026)
        constexpr static int COLOR_UP     = 26;   // [AV] COLOR UP — sg0=prix, sg1=extension
        constexpr static int COLOR_DN     = 27;   // [AV] COLOR DOWN — sg0=prix, sg1=extension
        constexpr static int LONG_UP_BAR  = 18;   // [AV] LONG UP BAR (rectangle vert Edge Zone)
        constexpr static int LONG_DN_BAR  = 17;   // [AV] LONG DOWN BAR (rectangle rouge Edge Zone)
        constexpr static int LONG_DN_UP   = 23;   // [AV] LONG DOWN UP BAR (reversal bull)
        constexpr static int LONG_UP_DN   = 24;   // [AV] LONG UP DOWN BAR (reversal bear)
        // ⭐ FIX 15/04/2026 : IDs natives au lieu des overlays (bug 26+ jours)
        //    Ancien : EDGE_BUY=32, EDGE_SELL=33 → overlays "rev8 0DIAG" cassés
        //             (Study Subgraphs Overlay pointant vers Chart #14, input10_raw=1
        //             détecté par StudyExplorer 15/04). sg0 Trigger retournait 0.
        //    Nouveau : 40/16 → études natives "EDGE ZONES IMBALANCE BUY/SELL 0DIAG"
        //             attachées directement sur Chart #23 (confirmé dump StudyExplorer).
        //    Cf. mia_studies_dump.txt Chart #23 lignes ID:40 BUY + ID:16 SELL.
        constexpr static int EDGE_BUY     = 40;   // EDGE ZONES IMBALANCE BUY 0DIAG (native, ex-32 overlay)
        constexpr static int EDGE_SELL    = 16;   // EDGE ZONES IMBALANCE SELL 0DIAG (native, ex-33 overlay)
        constexpr static int TRIPLE_ASK   = 37;   // [AV] TRIPLE ASK
        constexpr static int TRIPLE_BID   = 38;   // [AV] TRIPLE BID
    };

    // ── Chart 26 ES_VP ────────────────────────────────────────────────────────
    struct ES_VP {
        constexpr static int VP_CURRENT   =  1;   // VP session courante sg1=VPOC, sg2=VAH, sg3=VAL, sg4=VWAP
        constexpr static int VP_PREVIOUS  =  2;   // VP session précédente (idem)
        constexpr static int VWAP_DAY     =  3;   // VWAP session courante sg0
        constexpr static int VP_PREV_WAPS =  4;   // Previous VWAP + SD+1/-1 sg4=+1, sg12=SD+1, sg13=SD-1
        constexpr static int OHLC_SESSION = 29;   // OHLC session courante sg0=O, sg1=H, sg2=L, sg3=C
    };

    // ── Chart 27 NQ_VP ────────────────────────────────────────────────────────
    struct NQ_VP {
        constexpr static int VP_CURRENT   =  1;
        constexpr static int VP_PREVIOUS  =  2;
        constexpr static int VWAP_DAY     =  3;
        constexpr static int VP_PREV_WAPS =  4;
        constexpr static int OHLC_SESSION = 29;
    };

    // ── Chart 28 ES_CVD ───────────────────────────────────────────────────────
    struct ES_CVD {
        constexpr static int CVD          =  1;   // Cumulative Delta sg0=CVD, sg1=CVD_High?, sg2=?, sg3=Close
        constexpr static int CVD_OHLC     =  2;   // CVD OHLC sg0=Open, sg1=High, sg2=Low, sg3=Close
        constexpr static int VWAP         = 19;   // VWAP sg0
        constexpr static int VP_SESSION   = 35;   // Volume Profile session sg1=VPOC, sg2=VAH, sg3=VAL
        constexpr static int SWING        =  6;   // Swing High/Low sg0=High, sg1=Low
        constexpr static int DELTA_DIV_BUY  = 31; // Delta Divergence Buy
        constexpr static int DELTA_DIV_SELL = 32; // Delta Divergence Sell
    };

    // ── Chart 29 NQ_CVD ───────────────────────────────────────────────────────
    struct NQ_CVD {
        constexpr static int CVD          =  1;
        constexpr static int CVD_OHLC     =  2;
        constexpr static int VWAP         = 19;
        constexpr static int VP_SESSION   = 35;
        constexpr static int SWING        =  6;
        constexpr static int DELTA_DIV_BUY  = 31;
        constexpr static int DELTA_DIV_SELL = 32;
    };

    // ── Chart 31 ES_COMPOSITE ─────────────────────────────────────────────────
    // ESH26-CME — recréé + confirmé scan 02/03/2026 (miroir chart #30 NQ)
    struct ES_COMPOSITE {
        // Composite Profiles — IDs confirmés scan chart_31.json 02/03/2026
        constexpr static int COMP_PREV    = 34;   // 1J  ✅ confirmé scan
        constexpr static int COMP_20D     =  2;   // 20J ✅ confirmé scan
        constexpr static int COMP_50D     =  3;   // 50J ✅ confirmé scan
        constexpr static int COMP_100D    =  4;   // 100J ✅ confirmé scan
        constexpr static int COMP_200D    =  5;   // 200J ✅ confirmé scan
        // MenthorQ ES — confirmé scan 02/03/2026
        constexpr static int MQ_GAMMA     =  6;   // Gamma Levels ES ✅ confirmé scan
        constexpr static int MQ_BLIND     =  7;   // Blind Spots ES ✅ confirmé scan
        // Overnight — "High/Low for Time Period" 18h→9h29 ET — scan 02/03/2026
        constexpr static int OVN_HL       =  8;   // ✅ sg0=High, sg1=Low — ID confirmé scan
    };

    // ── Chart 30 NQ_COMPOSITE ─────────────────────────────────────────────────
    // NQH26-CME — confirmé scan 02/03/2026
    struct NQ_COMPOSITE {
        // Composite Profiles NQ — IDs confirmés scan chart_30.json 02/03/2026
        constexpr static int COMP_PREV    = 34;   // 1J  ✅ confirmé scan
        constexpr static int COMP_20D     =  2;   // 20J ✅ confirmé scan
        constexpr static int COMP_50D     =  3;   // 50J ✅ confirmé scan
        constexpr static int COMP_100D    =  4;   // 100J ✅ confirmé scan
        constexpr static int COMP_200D    =  5;   // 200J ✅ confirmé scan
        // MenthorQ NQ — confirmé scan 02/03/2026
        constexpr static int MQ_BLIND     =  7;   // Blind Spots NQ ✅ confirmé scan
        constexpr static int MQ_GAMMA     =  6;   // Gamma NQ ✅ confirmé scan
        // Overnight — "High/Low for Time Period" 18h→9h29 ET — scan 02/03/2026
        constexpr static int OVN_HL       =  8;   // ✅ sg0=High, sg1=Low — ID confirmé scan
    };

} // namespace DMP_Studies

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — STRUCTURE DMP_RawData
// ═══════════════════════════════════════════════════════════════════════════════
// Contient TOUS les prix bruts lus depuis Sierra Chart.
// Pas de calcul ici — uniquement du stockage. Les champs INVALIDES valent
// DMP_INVALID (= FLT_MAX) pour permettre la détection dans DMP_Transform.h.
// Défini comme #define dans DMP_Config.h — ne pas redéfinir ici.
constexpr float DMP_BOOL_TRUE  = 1.0f;    // Signal booléen actif
constexpr float DMP_BOOL_FALSE = 0.0f;    // Signal booléen inactif

struct DMP_RawData {

    // ── IDENTIFICATION ─────────────────────────────────────────────────────────
    long long   timestamp_ms;             // Timestamp Unix millisecondes
    int         bar_index;                // Index de la barre courante
    bool        is_nq;                    // true=NQ, false=ES
    char        contract[32];             // Symbole contrat complet (ex: "ESH26-CME")
    int         session;                  // 0=Asia, 1=London, 2=US (depuis heure barre)
    float       price_close;             // Prix de clôture de la barre
    float       price_open;              // Prix d'ouverture de la barre
    float       price_high;              // High de la barre
    float       price_low;               // Low de la barre
    float       tick_size;               // Taille du tick (0.25)

    // ─────────────────────────────────────────────────────────────────────────
    // A. FPBS / FOOTPRINT BAR STUDY
    // Source : Chart 1 (ES) Study 31 / Chart 2 (NQ) Study 33
    // ─────────────────────────────────────────────────────────────────────────
    float fpbs_delta;                    // sg0  — Delta barre (ask - bid)
    float fpbs_delta_change;             // sg2  — Variation delta vs barre précédente
    float fpbs_pos_delta;                // sg3  — Somme deltas positifs session
    float fpbs_neg_delta;                // sg4  — Somme deltas négatifs session
    float fpbs_max_delta;                // sg7  — Delta max de la barre
    float fpbs_min_delta;                // sg8  — Delta min de la barre
    float fpbs_delta_day;                // sg9  — Delta cumulatif journée
    float fpbs_volume;                   // sg12 — Volume total barre
    float fpbs_avg_size;                 // sg14 — Taille moyenne des trades ⭐
    float fpbs_ask_pct;                  // sg16 — % volume Ask
    float fpbs_bid_pct;                  // sg17 — % volume Bid
    float fpbs_cvd_day;                  // sg18 — CVD cumulatif journée (All)
    float fpbs_poc_vol;                  // sg19 — Volume au POC de la barre
    float fpbs_cvd_high;                 // sg20 — CVD High barre
    float fpbs_cvd_low;                  // sg21 — CVD Low barre
    float fpbs_bar_duration;             // sg29 — Durée barre en secondes
    float fpbs_finish;                   // sg33 — Finish (AskVol-BidVol final %)
    float fpbs_vol_per_sec;              // sg35 — Volume par seconde
    float fpbs_hl_range;                 // sg40 — Range High-Low barre
    float fpbs_poc_price;                // sg41 — Prix du POC intra-barre
    float fpbs_avg_bid_size;             // sg50 — Taille moy trades Bid ⭐
    float fpbs_avg_ask_size;             // sg51 — Taille moy trades Ask ⭐

    // 12 subgraphs FPBS ajoutés — 02/03/2026
    float fpbs_total_vol;                // sg1  — Volume total (Ask+Bid)
    float fpbs_buy_vol;                  // sg5  — BUY VOL (Ask brut)
    float fpbs_sell_vol;                 // sg6  — SELL VOL (Bid brut)
    float fpbs_delta_pct;                // sg10 — Delta % normalisé
    float fpbs_ticks;                    // sg11 — Nombre de trades
    float fpbs_finish_pct;               // sg34 — Finish AskVol BidVol Diff %
    float fpbs_high_pullback;            // sg36 — High Pullback Ask/Bid Vol Diff
    float fpbs_low_pullback;             // sg37 — Low Pullback Ask/Bid Vol Diff
    float fpbs_diag_pos_delta;           // sg42 — Diagonal Positive Delta Sum
    float fpbs_diag_neg_delta;           // sg43 — Diagonal Negative Delta Sum
    float fpbs_low_bid_pct;              // sg44 — Low Bid Volume %
    float fpbs_high_ask_pct;             // sg45 — High Ask Volume %

    // ─────────────────────────────────────────────────────────────────────────
    // B. ROTATION & CLUSTER
    // Source : Chart 1/2 Study ROTATION, ROTATION_UP/DN
    // ─────────────────────────────────────────────────────────────────────────
    float rotation_value;                // sg0  — >0=pivot HIGH / <0=pivot LOW
    float rotation_zz_mid;              // sg6  — ZigZag Midpoint
    float rotation_zz_osc;              // sg8  — ZigZag Oscillateur
    float rotation_up_signal;           // ROTATION_UP sg0  — Signal rotation haussière
    float rotation_dn_signal;           // ROTATION_DN sg0  — Signal rotation baissière
    // FIX 13/04/2026 : array etendu 10 → 20, lecture via DMP_ReadVolumeClustersFromVAP
    // (scan direct VAP cells, seuil total volume ES=500 / NQ=50, tri par distance
    // au prix courant). Remplace l'ancien code buggy qui scannait les subgraphs
    // de l'etude Cluster Volume (meme bug que big orders — 26 jours de code mort).
    float cluster_prices[20];            // 20 prix clusters les plus proches du prix courant

    // ─────────────────────────────────────────────────────────────────────────
    // C. SIGNAUX BATAILLE NAVALE
    // Source : Chart 1 (ES) / Chart 2 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float bn_color_up;                   // COLOR_UP sg0   — Zone bullish active (pullback simple)
    float bn_color_dn;                   // COLOR_DN sg0   — Zone bearish active (pullback simple)
    float bn_color_up_2;                 // COLOR_UP_2     — Zone bullish double stackée (continuation)
    float bn_color_dn_2;                 // COLOR_DN_2     — Zone bearish double stackée
    float bn_absorb_ask;                 // ABSORB_ASK sg0 — Absorption vendeurs (bullish)
    float bn_absorb_bid;                 // ABSORB_BID sg0 — Absorption acheteurs (bearish)
    float bn_long_up;                    // LONG_UP sg0    — Longue barre haussière
    float bn_long_dn;                    // LONG_DN sg0    — Longue barre baissière
    float bn_double_ask;                 // DOUBLE_ASK sg0 — Double pression Ask (ES)
    float bn_double_bid;                 // DOUBLE_BID sg0 — Double pression Bid (ES)
    float bn_triple_ask;                 // TRIPLE_ASK sg0 — Triple pression Ask (NQ)
    float bn_triple_bid;                 // TRIPLE_BID sg0 — Triple pression Bid (NQ)
    // Big Orders (10 niveaux, le plus proche sera calculé dans Transform)
    // FIX 13/04/2026 : buffers etendus 10 → 20 pour eviter la saturation
    // sur ES (tres liquide, nombreux big orders par tier). Tri par distance
    // au prix courant dans DMP_ReadBigOrdersFromVAP pour garder les 20 plus
    // pertinents. Transform.h utilise 20 en taille pour NearestAboveBelow.
    float bn_ask100[20];                 // ASK_100 — 20 niveaux Ask big orders t1
    float bn_bid100[20];                 // BID_100 — 20 niveaux Bid big orders t1
    // 🆕 BUG #9 — Tous les seuils Big Orders (04/03/2026)
    // NQ: +10, +30 (fire souvent) | ES: +150, +400, +1000 (seuils progressifs)
    float bn_ask_extra1[20];             // NQ: ASK+10  | ES: ASK+150
    float bn_bid_extra1[20];             // NQ: BID+10  | ES: BID+150
    float bn_ask_extra2[20];             // NQ: ASK+30  | ES: ASK+400
    float bn_bid_extra2[20];             // NQ: BID+30  | ES: BID+400
    float bn_ask_extra3[20];             // ES: ASK+1000 | NQ: unused (INVALID)
    float bn_bid_extra3[20];             // ES: BID+1000 | NQ: unused (INVALID)

    // ─────────────────────────────────────────────────────────────────────────
    // C4. VOLUME UP/DOWN + EDGE ZONES FOOTPRINT — BUG #10 (05/03/2026)
    // ─────────────────────────────────────────────────────────────────────────
    float bn_volume_up;                  // [AV] VOLUME UP sg2 (NQ uniquement, 0 pour ES)
    float bn_volume_dn;                  // [AV] VOLUME DOWN sg2 (NQ uniquement, 0 pour ES)
    float fp_edge_buy;                   // Edge Zone Imbalance BUY Footprint (sg2, principal)
    float fp_edge_sell;                  // Edge Zone Imbalance SELL Footprint (sg2, principal)
    float fp_edge_buy_2;                 // Edge Zone BUY 2ème variante (NQ: 0DIAG, ES: rev1 800%)
    float fp_edge_sell_2;                // Edge Zone SELL 2ème variante

    // ─────────────────────────────────────────────────────────────────────────
    // C2. SIGNAUX BN — CHART BARRES (1min) — BUG #8 (04/03/2026)
    // Source : Chart 25 (ES) / Chart 23 (NQ)
    // Le Bot lit ces signaux pour ses décisions ; le DMP les ignorait.
    // ─────────────────────────────────────────────────────────────────────────
    float bar_color_up;                  // COLOR_UP sg0  — Point vert per-bar
    float bar_color_dn;                  // COLOR_DN sg0  — Point rouge per-bar
    float bar_long_up_bar;               // LONG_UP_BAR sg0  — Rectangle vert (Edge Zone)
    float bar_long_dn_bar;               // LONG_DN_BAR sg0  — Rectangle rouge (Edge Zone)
    float bar_long_dn_up;                // LONG_DN_UP sg0   — Reversal haussier
    float bar_long_up_dn;                // LONG_UP_DN sg0   — Reversal baissier
    float bar_edge_buy;                  // EDGE_BUY sg0  — Imbalance acheteur
    float bar_edge_sell;                 // EDGE_SELL sg0  — Imbalance vendeur
    float bar_pressure_ask;              // DOUBLE/TRIPLE ASK sg0 (ES=Double, NQ=Triple)
    float bar_pressure_bid;              // DOUBLE/TRIPLE BID sg0 (ES=Double, NQ=Triple)

    // ─────────────────────────────────────────────────────────────────────────
    // C3. EXTENSION LINES — PRIX S/R NON-TOUCHÉS — BUG #8 (04/03/2026)
    // Source : Chart 25 (ES) / Chart 23 (NQ) — sg1 des études ci-dessus
    // sg1 = prix de la ligne S/R qui s'étend vers le futur ("Extend to Future
    // Intersection"). Tant que le prix n'a pas touché la ligne, elle reste active.
    // ─────────────────────────────────────────────────────────────────────────
    float ext_color_up_px;               // Extension Line COLOR UP = support
    float ext_color_dn_px;               // Extension Line COLOR DN = résistance
    float ext_long_up_px;                // Extension Line LONG UP BAR = résistance forte
    float ext_long_dn_px;                // Extension Line LONG DN BAR = support fort
    float ext_edge_buy_px;               // Extension Line EDGE BUY = support imbalance
    float ext_edge_sell_px;              // Extension Line EDGE SELL = résistance imbalance

    // ─────────────────────────────────────────────────────────────────────────
    // D. VWAP JOURNALIER
    // Source : Chart 26 Study 3 (ES) / Chart 27 Study 3 (NQ) — VP Charts
    // ⚠️  Ancienne source Chart 1/2 retournait NULL — corrigé Bug #2
    // ─────────────────────────────────────────────────────────────────────────
    float vwap_day;                      // sg0 — VWAP journalier (reset 9h30 ET)
    float vwap_day_sd1u;                 // sg1 — VWAP +1σ
    float vwap_day_sd1d;                 // sg2 — VWAP -1σ
    float vwap_day_sd2u;                 // sg3 — VWAP +2σ
    float vwap_day_sd2d;                 // sg4 — VWAP -2σ
    float vwap_day_sd3u;                 // sg5 — VWAP +3σ (confirmé chart_26/27 JSON 28/03/2026)
    float vwap_day_sd3d;                 // sg6 — VWAP -3σ
    // Pente VWAP — CRITIQUE Layer 3 : slope>0 AND delta>0 → long (82% WR ES)
    float vwap_slope_10;                 // (vwap_now - vwap_10bars_ago) / 10 pts/barre
    float vwap_slope_30;                 // (vwap_now - vwap_30bars_ago) / 30 pts/barre

    // ─────────────────────────────────────────────────────────────────────────
    // E. VWAP WEEKLY & MONTHLY
    // Source : Chart 16 (ES) / Chart 17 (NQ) — Studies 4/5
    // ⚠️  À confirmer Lundi (Study IDs 4/5 à valider)
    // ─────────────────────────────────────────────────────────────────────────
    float vwap_weekly;                   // VWAP semaine glissante
    float vwap_weekly_sd1u;              // VWAP Weekly +1σ
    float vwap_weekly_sd1d;              // VWAP Weekly -1σ
    float vwap_monthly;                  // VWAP mensuel glissant
    float vwap_monthly_sd1u;             // VWAP Monthly +1σ
    float vwap_monthly_sd1d;             // VWAP Monthly -1σ

    // ─────────────────────────────────────────────────────────────────────────
    // F. ATR & MOVING AVERAGES (Daily)
    // Source : Chart 16 (ES) / Chart 17 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float atr_daily;                     // ATR daily (dénominateur normalisation)
    float ma_fast;                       // MA rapide (trend court terme)
    float ma_slow;                       // MA lente (trend long terme)

    // ─────────────────────────────────────────────────────────────────────────
    // G. MENTHORQ GAMMA & BLIND SPOTS
    // Source : Chart 25 Study 2 (ES) / Chart 23 Study 25 (NQ)
    //          Chart 30 Study 7 pour Blind Spots ES (valeurs actives !)
    // ─────────────────────────────────────────────────────────────────────────
    float mq_call;                       // sg0 — Call Resistance (mur Gamma Call)
    float mq_put;                        // sg1 — Put Support (mur Gamma Put)
    float mq_hvl;                        // sg2 — HVL (High Volume Level - point de flip)
    float mq_1d_min;                     // sg3 — Target BAS journée (MenthorQ daily range min)
    float mq_1d_max;                     // sg4 — Target HAUT journée (MenthorQ daily range max)
    float mq_gex[10];                    // sg9..18 — GEX niveaux 1 à 10
    float mq_blind[10];                  // sg0..9 — Blind Spots BL1 à BL10
    float mq_call_0dte;                  // sg5 — Call Resistance 0DTE
    float mq_put_0dte;                   // sg6 — Put Support 0DTE
    float mq_hvl_0dte;                   // sg7 — HVL 0DTE

    // ─────────────────────────────────────────────────────────────────────────
    // H. VIX
    // Source : Chart 15 prix courant + MenthorQ Gamma VIX
    // ─────────────────────────────────────────────────────────────────────────
    float vix_level;                     // Prix courant du VIX
    float vix_call;                      // sg0 VIX Chart15 — Résistance Call VIX
    float vix_put;                       // sg1 VIX Chart15 — Support Put VIX
    float vix_hvl;                       // sg2 VIX Chart15 — HVL VIX (zone de flip)
    float vix_call_0dte;                 // sg5 — Call Resistance 0DTE sur VIX
    float vix_put_0dte;                  // sg6 — Put Support 0DTE sur VIX
    float vix_hvl_0dte;                  // sg7 — HVL 0DTE sur VIX
    float vix_gex[10];                   // sg9..18 — GEX niveaux 1 à 10 sur VIX

    // ─────────────────────────────────────────────────────────────────────────
    // I. VOLUME PROFILE — SESSION COURANTE
    // Source : Chart 26 Study 1 (ES) / Chart 27 Study 1 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float cur_vpoc;                      // sg1 — VPOC session courante
    float cur_vah;                       // sg2 — VAH session courante
    float cur_val;                       // sg3 — VAL session courante
    float cur_vwap_vp;                   // sg4 — VWAP VP session courante

    // ─────────────────────────────────────────────────────────────────────────
    // J. VOLUME PROFILE — SESSION PRÉCÉDENTE
    // Source : Chart 26 Study 2 (ES) / Chart 27 Study 2 (NQ)
    // ⚠️  Valeurs nulles hors session — à rescanner Lundi 14h00 FR
    // ─────────────────────────────────────────────────────────────────────────
    float prev_vpoc;                     // sg1 — PVPOC (pivot central J-1)
    float prev_vah;                      // sg2 — PVAH (résistance VA J-1)
    float prev_val;                      // sg3 — PVAL (support VA J-1)
    float prev_vwap;                     // sg4 — PVWAP

    // ─────────────────────────────────────────────────────────────────────────
    // K. PREVIOUS VWAP SD+1/-1
    // Source : Chart 26 Study 4 (ES) / Chart 27 Study 4 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float prev_vwap_sd1u;                // sg12 — PVWAP +1σ
    float prev_vwap_sd1d;                // sg13 — PVWAP -1σ

    // ─────────────────────────────────────────────────────────────────────────
    // L. SESSION IB & OHLC
    // Source : Chart 25/23 (barres) + Chart 26/27 Study 29 (OHLC)
    // ─────────────────────────────────────────────────────────────────────────
    float open_830;                      // Open 08h30 ET (pré-market tardif)
    float sess_high;                     // High session courante (RTH)
    float sess_low;                      // Low session courante (RTH)
    float ib_high;                       // IB High = Max(High 9h30-10h30) ← calculé
    float ib_low;                        // IB Low  = Min(Low  9h30-10h30) ← calculé
    float open_cash;                     // Open exact 9h30 ET ← calculé depuis OHLC session

    // ─────────────────────────────────────────────────────────────────────────
    // M. OVERNIGHT HIGH/LOW
    // Source : Chart 30/31 Studies 10/11 (HIGHER HIGH / LOWER LOW)
    // ─────────────────────────────────────────────────────────────────────────
    float ovn_high;                      // High session 18h00-9h29 ET
    float ovn_low;                       // Low session 18h00-9h29 ET

    // ─────────────────────────────────────────────────────────────────────────
    // N. CVD & SWING HIGH/LOW
    // Source : Chart 28 (ES) / Chart 29 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float cvd_close;                     // CVD Study sg3 — CVD Close barre courante
    float cvd_ohlc_open;                 // CVD OHLC sg0 — Open CVD (contexte swing)
    float cvd_ohlc_high;                 // CVD OHLC sg1 — High CVD
    float cvd_ohlc_low;                  // CVD OHLC sg2 — Low CVD
    float swing_high;                    // SWING sg0 — Dernier Swing High validé
    float swing_low;                     // SWING sg1 — Dernier Swing Low validé
    float delta_div_buy;                 // DELTA_DIV_BUY Extension Lines — Nb zones divergence bullish actives
    float delta_div_sell;                // DELTA_DIV_SELL Extension Lines — Nb zones divergence bearish actives
    float vp_session_vpoc;               // VP_SESSION sg1 — VPOC session CVD chart

    // ─────────────────────────────────────────────────────────────────────────
    // O. COMPOSITE PROFILES (20/50/100/200 jours)
    // Source : Chart 31 (ES) / Chart 30 (NQ) — ⚠️ ordre inversé vs numérotation
    // ─────────────────────────────────────────────────────────────────────────
    float comp_20d_vpoc;
    float comp_20d_vah;
    float comp_20d_val;
    float comp_20d_vwap;                 // sg4 — VWAP Composite 20J
    float comp_50d_vpoc;
    float comp_50d_vah;
    float comp_50d_val;
    float comp_50d_vwap;                 // sg4 — VWAP Composite 50J

    // ─────────────────────────────────────────────────────────────────────────
    // P. STATUS & DIAGNOSTICS
    // ─────────────────────────────────────────────────────────────────────────
    int     read_errors;                 // Nombre de lectures en erreur cette barre
    bool    is_rth_session;              // true si dans session RTH (9h30-16h00 ET)
    bool    ib_complete;                 // true si IB formée (heure >= 10h30 ET)
    char    error_detail[256];           // Détail erreurs pour diagnostic

    // ─────────────────────────────────────────────────────────────────────────
    // 🆕 Q. POOR HIGHS / LOWS (15/03/2026 — Market Profile avancé)
    // ─────────────────────────────────────────────────────────────────────────
    // Un "poor high" = le haut du profil n'a PAS de tail (excess).
    // Seulement 1-2 barres ont touché le session high = le marché n'a pas
    // fini son auction = continuation probable le lendemain.
    //
    // Calculé via PersistentFloat dans DMP_Main.cpp :
    //   bars_near_sess_high = barres où price_high >= sess_high - 5*tick_size
    //   bars_near_sess_low  = barres où price_low  <= sess_low  + 5*tick_size
    //
    // poor_high = (bars_near_sess_high < POOR_THRESHOLD)  // Pas assez d'excess
    // poor_low  = (bars_near_sess_low  < POOR_THRESHOLD)  // Pas assez d'excess
    //
    // Usage: si poor_high hier → biais LONG (le marché va finir l'auction)
    //        si poor_low hier  → biais SHORT
    // ─────────────────────────────────────────────────────────────────────────
    int     excess_high_bars;            // Barres dans les 5t du session high
    int     excess_low_bars;             // Barres dans les 5t du session low
    bool    poor_high;                   // true si excess_high_bars < 3
    bool    poor_low;                    // true si excess_low_bars < 3

};

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — HELPER : LECTURE SÉCURISÉE
// ═══════════════════════════════════════════════════════════════════════════════

// Lecture d'une valeur d'une étude d'un autre chart.
// Retourne DMP_INVALID si le chart/study n'est pas disponible ou la valeur
// est NaN/Inf. Ne génère jamais d'exception.

inline float DMP_SafeRead(
    SCStudyInterfaceRef sc,
    int                 chart_number,
    int                 study_id,
    int                 subgraph_index,
    int                 bar_offset = 0)    // 0=barre courante, 1=barre précédente...
{
    if (study_id < 0) return DMP_INVALID;  // ID invalide (== -1 dans study_mapping)

    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart_number, study_id, subgraph_index, arr);

    if (arr.GetArraySize() == 0) return DMP_INVALID;   // Chart/Study pas disponible

    int idx = sc.Index - bar_offset;
    if (idx < 0 || idx >= (int)arr.GetArraySize()) return DMP_INVALID;

    float val = arr[idx];

    // Rejeter NaN, Inf, et la valeur sentinelle Sierra Chart (1e38)
    if (!std::isfinite(val)) return DMP_INVALID;
    if (val >= 1e37f)        return DMP_INVALID;   // Sentinel Sierra Chart

    return val;
}

// 🆕 FIX 31/03/2026 — Lecture MÊME CHART via sc.GetStudyArrayUsingID()
//   GetStudyArrayFromChartUsingID ne retourne pas les sg avancés du FPBS
//   (Numbers Bars Calculated Values) même quand le DMP est sur le même chart.
//   GetStudyArrayUsingID accède directement aux données du même chart → tous les sg.
inline float DMP_SafeReadLocal(
    SCStudyInterfaceRef sc,
    int                 study_id,
    int                 subgraph_index,
    int                 bar_offset = 0)
{
    if (study_id < 0) return DMP_INVALID;

    SCFloatArray arr;
    sc.GetStudyArrayUsingID(study_id, subgraph_index, arr);

    if (arr.GetArraySize() == 0) return DMP_INVALID;

    int idx = sc.Index - bar_offset;
    if (idx < 0 || idx >= (int)arr.GetArraySize()) return DMP_INVALID;

    float val = arr[idx];

    if (!std::isfinite(val)) return DMP_INVALID;
    if (val >= 1e37f)        return DMP_INVALID;

    return val;
}

// Version qui retourne 0.0f si invalide (pour les booléens/signaux)
inline float DMP_SafeReadBool(SCStudyInterfaceRef sc, int chart, int study, int sg) {
    float v = DMP_SafeRead(sc, chart, study, sg);
    return (v == DMP_INVALID) ? 0.0f : v;
}

// ⚠️ FIX 11/03/2026 — Lecture par STUDY NUMBER (position 1-based) au lieu de Study ID.
//  GetStudyArrayFromChartUsingID a un bug SC : quand 2 instances du même type
//  d'étude existent (ex: 2× VWAP avec périodes différentes), l'API résout par
//  type de fonction et retourne toujours la PREMIÈRE instance, ignorant l'ID.
//  GetStudyArrayFromChart utilise le numéro de position (1-based) dans la liste
//  des études du chart → distingue correctement les 2 instances.
//
//  ⚠️ ATTENTION OFFSET SUBGRAPH : GetStudyArrayFromChart retourne le base graph
//  du chart en sg0 (= FLT_MAX pour les études). Les subgraphs de la study
//  commencent à sg1. L'appelant doit passer subgraph_index+1.
//  Confirmé par debug log 11/03/2026 : ByID sg0=VWAP, ByNum sg0=FLT_MAX, sg1=VWAP.
inline float DMP_SafeReadByNum(
    SCStudyInterfaceRef sc,
    int                 chart_number,
    int                 study_number,     // Position 1-based dans Chart Studies
    int                 subgraph_index,   // ⚠️ Passer subgraph_index+1 vs GetStudyArrayFromChartUsingID
    int                 bar_offset = 0)
{
    if (study_number <= 0) return DMP_INVALID;

    SCFloatArray arr;
    sc.GetStudyArrayFromChart(chart_number, study_number, subgraph_index, arr);

    if (arr.GetArraySize() == 0) return DMP_INVALID;

    int idx = sc.Index - bar_offset;
    if (idx < 0 || idx >= (int)arr.GetArraySize()) return DMP_INVALID;

    float val = arr[idx];

    if (!std::isfinite(val)) return DMP_INVALID;
    if (val >= 1e37f)        return DMP_INVALID;

    return val;
}

// ─────────────────────────────────────────────────────────────────────────────
// DMP_SafeReadByNumLast — Comme SafeReadByNum mais lit arr[LAST] pas arr[sc.Index]
// ─────────────────────────────────────────────────────────────────────────────
//  ⚠️ FIX 12/03/2026 — GetStudyArrayFromChart NE FAIT PAS de synchronisation
//  temporelle cross-chart. Il retourne le tableau brut du chart cible.
//  Quand le DMP tourne sur chart 1 (footprint, ~1300 barres) et lit chart 25
//  (barres, ~60000 barres), arr[sc.Index=1300] pointe vers une barre HISTORIQUE.
//  Solution: lire arr[GetArraySize()-1] = dernière barre = valeur actuelle.
//  Confirmé par debug: bar#59916 (last) = 6751 ✅, bar#1320 (sc.Index) = 6996 ❌.
//
//  À utiliser pour VWAP W/M uniquement (études per-bar lues cross-chart par position).
inline float DMP_SafeReadByNumLast(
    SCStudyInterfaceRef sc,
    int                 chart_number,
    int                 study_number,     // Position 1-based dans Chart Studies
    int                 subgraph_index)
{
    if (study_number <= 0) return DMP_INVALID;

    SCFloatArray arr;
    sc.GetStudyArrayFromChart(chart_number, study_number, subgraph_index, arr);

    int sz = (int)arr.GetArraySize();
    if (sz == 0) return DMP_INVALID;

    float val = arr[sz - 1];  // DERNIÈRE barre = valeur actuelle

    if (!std::isfinite(val)) return DMP_INVALID;
    if (val >= 1e37f)        return DMP_INVALID;

    return val;
}

// ─────────────────────────────────────────────────────────────────────────────
// DMP_SafeReadLast — Lit la DERNIÈRE valeur du tableau (pas arr[sc.Index])
// ─────────────────────────────────────────────────────────────────────────────
//  Identique à l'ancien dumper (MIA_Dumper_G3_Unifier.cpp lignes 411/422):
//      float v = arr[arr.GetArraySize()-1];
//
//  À utiliser pour les études "reference line" qui ne peignent leur valeur
//  que sur la DERNIÈRE barre du chart source, PAS sur chaque barre:
//    - VP_PREVIOUS, VP_PREV_WAPS, OHLC_SESSION
//    - MQ_GAMMA, MQ_BLIND (niveaux horizontaux)
//    - COMPOSITE PROFILES
//    - OVN_HL (High/Low for Time Period)
//    - HH_SESSION, LL_SESSION
//    - OPEN_830
//    - ATR, MA (sur chart daily cross-timeframe)
//
//  DMP_SafeReadLastValid (scan arrière val > 100) pour études WINDOWED :
//    - OVN_HL (peint seulement 18h→9h29 ET, 0 après)
//    - SWING HIGH/LOW (peint seulement aux pivots, 0 entre)
//
//  DMP_SafeRead (arr[sc.Index]) reste pour les études per-bar:
//    - VP_CURRENT, VWAP Day, CVD, FPBS, Rotation, BN signaux, ATR, etc.
//    - VWAP_WEEKLY, VWAP_MONTHLY (migrés sur charts BARRES intraday)
//
inline float DMP_SafeReadLast(
    SCStudyInterfaceRef sc,
    int                 chart_number,
    int                 study_id,
    int                 subgraph_index)
{
    if (study_id < 0) return DMP_INVALID;

    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart_number, study_id, subgraph_index, arr);

    int sz = (int)arr.GetArraySize();
    if (sz == 0) return DMP_INVALID;

    float val = arr[sz - 1];  // DERNIÈRE valeur (comme l'ancien dumper)

    if (!std::isfinite(val)) return DMP_INVALID;
    if (val >= 1e37f)        return DMP_INVALID;

    return val;
}

// Version Bool de SafeReadLast (retourne 0.0f si invalide)
inline float DMP_SafeReadLastBool(SCStudyInterfaceRef sc, int chart, int study, int sg) {
    float v = DMP_SafeReadLast(sc, chart, study, sg);
    return (v == DMP_INVALID) ? 0.0f : v;
}

// ─────────────────────────────────────────────────────────────────────────────
// DMP_SafeReadLastValid — Scanne EN ARRIÈRE pour trouver la dernière valeur
//                          qui est un prix valide (> 100, < 100000)
// ─────────────────────────────────────────────────────────────────────────────
//  Pour les études à FENÊTRE TEMPORELLE comme "High/Low for Time Period" (OVN):
//    - La valeur est peinte SEULEMENT pendant la période (ex: 18h→9h29 ET)
//    - Après 9h30, arr[last_bar] = 0 car la dernière barre est hors fenêtre
//    - SafeReadLast retourne 0 → IsPriceValid(0) = false → null
//    - SafeReadLastValid scanne en arrière (max 1000 barres) pour trouver
//      la dernière valeur réelle (= la barre 9h29, fin de l'OVN)
//
//  Limité à 1000 barres de scan pour éviter les perfs issues.
//  1000 barres * 1min = ~16h de lookback = couvre largement l'OVN.
//
inline float DMP_SafeReadLastValid(
    SCStudyInterfaceRef sc,
    int                 chart_number,
    int                 study_id,
    int                 subgraph_index,
    int                 max_lookback = 1000)
{
    if (study_id < 0) return DMP_INVALID;

    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart_number, study_id, subgraph_index, arr);

    int sz = (int)arr.GetArraySize();
    if (sz == 0) return DMP_INVALID;

    // Scanner en arrière depuis la dernière barre
    int start = sz - 1;
    int stop  = (sz - max_lookback > 0) ? (sz - max_lookback) : 0;

    for (int i = start; i >= stop; i--) {
        float val = arr[i];
        if (!std::isfinite(val)) continue;
        if (val >= 1e37f) continue;           // Sentinel SC
        if (val > 100.0f && val < 100000.0f)  // Prix valide
            return val;
    }

    return DMP_INVALID;  // Rien trouvé dans les 1000 dernières barres
}

// Vérification si une valeur est valide (non-sentinelle)
inline bool DMP_IsValid(float v) {
    return (v != DMP_INVALID) && std::isfinite(v);
}

// Vérification si un niveau de prix est cohérent (entre 100 et 100000)
inline bool DMP_IsPriceValid(float price) {
    return DMP_IsValid(price) && (price > 100.0f) && (price < 100000.0f);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — FONCTIONS DE LECTURE PAR SECTION
// ═══════════════════════════════════════════════════════════════════════════════

// ─────────────────────────────────────────────────────────────────────────────
// FPBS — Footprint Bar Study
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadFPBS(SCStudyInterfaceRef sc, DMP_RawData& d) {
    // ── Phase 1 : Lire les basiques depuis NBCV (sg0,1,2,3,4,5,6,7,8,9,35) ──
    //   Ces subgraphs fonctionnent via GetStudyArrayUsingID.
    const int study = d.is_nq ? DMP_Studies::NQ_FP::FPBS : DMP_Studies::ES_FP::FPBS;

    d.fpbs_delta         = DMP_SafeReadLocal(sc, study,  0);
    d.fpbs_delta_change  = DMP_SafeReadLocal(sc, study,  2);
    d.fpbs_pos_delta     = DMP_SafeReadLocal(sc, study,  3);
    d.fpbs_neg_delta     = DMP_SafeReadLocal(sc, study,  4);
    d.fpbs_max_delta     = DMP_SafeReadLocal(sc, study,  7);
    d.fpbs_min_delta     = DMP_SafeReadLocal(sc, study,  8);
    d.fpbs_delta_day     = DMP_SafeReadLocal(sc, study,  9);
    d.fpbs_cvd_day       = DMP_SafeReadLocal(sc, study, 18);
    d.fpbs_cvd_high      = DMP_SafeReadLocal(sc, study, 20);
    d.fpbs_cvd_low       = DMP_SafeReadLocal(sc, study, 21);
    d.fpbs_vol_per_sec   = DMP_SafeReadLocal(sc, study, 35);
    d.fpbs_total_vol     = DMP_SafeReadLocal(sc, study,  1);
    d.fpbs_buy_vol       = DMP_SafeReadLocal(sc, study,  5);
    d.fpbs_sell_vol      = DMP_SafeReadLocal(sc, study,  6);
    d.fpbs_finish        = DMP_SafeReadLocal(sc, study, 33);

    // ── Phase 2 : Calculer les sg avancés depuis VolumeAtPrice (barre courante) ──
    // 🆕 FIX 31/03/2026 : Les sg10+ du NBCV ne sont pas accessibles via ACSIL.
    //   On calcule directement depuis sc.VolumeAtPriceForBars (données brutes).
    //   Chaque s_VolumeAtPriceV2 fournit : PriceInTicks, Volume, BidVolume,
    //   AskVolume, NumberOfTrades — suffisant pour tout recalculer.
    d.fpbs_delta_pct      = 0.0f;
    d.fpbs_ticks          = 0.0f;
    d.fpbs_volume         = 0.0f;
    d.fpbs_avg_size       = 0.0f;
    d.fpbs_ask_pct        = 0.0f;
    d.fpbs_bid_pct        = 0.0f;
    d.fpbs_poc_vol        = 0.0f;
    d.fpbs_poc_price      = DMP_INVALID;
    d.fpbs_bar_duration   = 0.0f;
    d.fpbs_hl_range       = 0.0f;
    d.fpbs_finish_pct     = 0.0f;
    d.fpbs_high_pullback  = 0.0f;
    d.fpbs_low_pullback   = 0.0f;
    d.fpbs_diag_pos_delta = 0.0f;
    d.fpbs_diag_neg_delta = 0.0f;
    d.fpbs_low_bid_pct    = 0.0f;
    d.fpbs_high_ask_pct   = 0.0f;
    d.fpbs_avg_bid_size   = 0.0f;
    d.fpbs_avg_ask_size   = 0.0f;

    if (sc.VolumeAtPriceForBars) {
        const int bar = sc.Index;
        const int n_levels = sc.VolumeAtPriceForBars->GetSizeAtBarIndex(bar);

        if (n_levels > 0) {
            // Accumulateurs
            unsigned int sum_vol = 0, sum_ask = 0, sum_bid = 0, sum_trades = 0;
            int min_tick = INT_MAX, max_tick = INT_MIN;
            unsigned int poc_vol_best = 0;
            int poc_tick = 0;
            int close_tick = INT_MIN;  // dernier niveau = plus récent
            int ask_levels = 0, bid_levels = 0;

            // Buffer pour diagonal (max 500 niveaux, trié par prix)
            struct VapLevel { int tick; int ask; int bid; };
            VapLevel levels[500];
            int lvl_count = 0;

            for (int k = 0; k < n_levels; k++) {
                const s_VolumeAtPriceV2* v = nullptr;
                if (!sc.VolumeAtPriceForBars->GetVAPElementAtIndex(bar, k, &v) || !v)
                    continue;
                if (v->Volume == 0) continue;

                int tick   = v->PriceInTicks;
                unsigned int vol = v->Volume;
                unsigned int ask = v->AskVolume;
                unsigned int bid = v->BidVolume;
                unsigned int trades = v->NumberOfTrades;

                sum_vol    += vol;
                sum_ask    += ask;
                sum_bid    += bid;
                sum_trades += trades;

                if (ask > 0) ask_levels++;
                if (bid > 0) bid_levels++;

                // POC = niveau avec le plus de volume
                if (vol > poc_vol_best) {
                    poc_vol_best = vol;
                    poc_tick = tick;
                }

                // High / Low
                if (tick > max_tick) max_tick = tick;
                if (tick < min_tick) min_tick = tick;

                // Close = dernier tick rencontré (plus haut index dans le VAP)
                close_tick = tick;

                // Buffer diagonal (trié après)
                if (lvl_count < 500) {
                    levels[lvl_count++] = {tick, (int)ask, (int)bid};
                }
            }

            const float ts = d.tick_size > 0.0f ? d.tick_size : 0.25f;

            if (sum_vol > 0) {
                float delta = (float)sum_ask - (float)sum_bid;
                // Ratios [0,1] — convention NBCV (le Transform attend [0,1])
                d.fpbs_delta_pct  = delta / (float)sum_vol;
                d.fpbs_ask_pct    = (float)sum_ask / (float)sum_vol;
                d.fpbs_bid_pct    = (float)sum_bid / (float)sum_vol;
                d.fpbs_volume     = (float)sum_vol;
                d.fpbs_ticks      = (float)sum_trades;
                d.fpbs_avg_size   = (float)sum_vol / (float)n_levels;
                d.fpbs_poc_vol    = (float)poc_vol_best;
                d.fpbs_poc_price  = (float)poc_tick * ts;
                d.fpbs_hl_range   = (float)(max_tick - min_tick);

                // Duration : stocker en fraction de jour (convention NBCV sg29)
                // Le Transform multiplie par 86400 pour convertir en secondes.
                if (DMP_IsValid(d.fpbs_vol_per_sec) && d.fpbs_vol_per_sec > 0.0f)
                    d.fpbs_bar_duration = ((float)sum_vol / d.fpbs_vol_per_sec) / 86400.0f;

                // Avg bid/ask size
                d.fpbs_avg_bid_size = bid_levels > 0 ? (float)sum_bid / (float)bid_levels : 0.0f;
                d.fpbs_avg_ask_size = ask_levels > 0 ? (float)sum_ask / (float)ask_levels : 0.0f;

                // High pullback : delta au High (askVol - bidVol au max_tick)
                // Low pullback  : delta au Low  (bidVol - askVol au min_tick)
                for (int k = 0; k < n_levels; k++) {
                    const s_VolumeAtPriceV2* v = nullptr;
                    if (!sc.VolumeAtPriceForBars->GetVAPElementAtIndex(bar, k, &v) || !v)
                        continue;
                    if (v->PriceInTicks == max_tick)
                        d.fpbs_high_pullback = (float)v->AskVolume - (float)v->BidVolume;
                    if (v->PriceInTicks == min_tick)
                        d.fpbs_low_pullback = (float)v->BidVolume - (float)v->AskVolume;
                    if (v->PriceInTicks == close_tick && v->Volume > 0)
                        d.fpbs_finish_pct = ((float)v->AskVolume - (float)v->BidVolume) / (float)v->Volume;
                    // High ask % et Low bid % — ratios [0,1]
                    if (v->PriceInTicks == max_tick && v->Volume > 0)
                        d.fpbs_high_ask_pct = (float)v->AskVolume / (float)v->Volume;
                    if (v->PriceInTicks == min_tick && v->Volume > 0)
                        d.fpbs_low_bid_pct = (float)v->BidVolume / (float)v->Volume;
                }

                // ── Absorption VAP (remplace ExtensionLineCount, per-bar exact) ──
                // Formule Sierra Chart : AVAP(H) > BVAP(H)*3 && AVAP(H) > seuil
                // On a déjà les volumes au High et au Low depuis le scan ci-dessus
                {
                    // Seuils : ES=50 (vol élevé), NQ=10 (vol plus faible)
                    const float absorb_threshold = d.is_nq ? 10.0f : 50.0f;

                    // Chercher les volumes au High et au Low
                    unsigned int ask_at_high = 0, bid_at_high = 0;
                    unsigned int ask_at_low = 0, bid_at_low = 0;
                    for (int k = 0; k < n_levels; k++) {
                        const s_VolumeAtPriceV2* v = nullptr;
                        if (!sc.VolumeAtPriceForBars->GetVAPElementAtIndex(bar, k, &v) || !v)
                            continue;
                        if (v->PriceInTicks == max_tick) {
                            ask_at_high = v->AskVolume;
                            bid_at_high = v->BidVolume;
                        }
                        if (v->PriceInTicks == min_tick) {
                            ask_at_low = v->AskVolume;
                            bid_at_low = v->BidVolume;
                        }
                    }

                    // Absorption Ask : acheteurs dominent au High (3:1 + seuil)
                    // Contexte : O > prev_close (approximé par O, le gap up)
                    bool ask_absorb = (ask_at_high > bid_at_high * 3)
                                   && ((float)ask_at_high > absorb_threshold);

                    // Absorption Bid : vendeurs dominent au Low (3:1 + seuil)
                    bool bid_absorb = (bid_at_low > ask_at_low * 3)
                                   && ((float)bid_at_low > absorb_threshold);

                    d.bn_absorb_ask = ask_absorb ? 1.0f : 0.0f;
                    d.bn_absorb_bid = bid_absorb ? 1.0f : 0.0f;
                }

                // Diagonal : comparer AskVol[i] vs BidVol[i-1] (niveaux adjacents)
                // Trier par prix croissant d'abord
                for (int i = 0; i < lvl_count - 1; i++)
                    for (int j = i + 1; j < lvl_count; j++)
                        if (levels[j].tick < levels[i].tick) {
                            VapLevel tmp = levels[i];
                            levels[i] = levels[j];
                            levels[j] = tmp;
                        }

                float diag_pos = 0.0f, diag_neg = 0.0f;
                for (int i = 1; i < lvl_count; i++) {
                    // Diagonal positive : ask du niveau supérieur vs bid du niveau inférieur
                    int diff_up = levels[i].ask - levels[i-1].bid;
                    if (diff_up > 0) diag_pos += (float)diff_up;
                    // Diagonal negative : bid du niveau inférieur vs ask du niveau supérieur
                    int diff_dn = levels[i-1].bid - levels[i].ask;
                    if (diff_dn > 0) diag_neg += (float)diff_dn;
                }
                d.fpbs_diag_pos_delta = diag_pos;
                d.fpbs_diag_neg_delta = diag_neg;
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// HELPER BN : lecture sg2 "Sum of Alerts" via arr[size-1]
// ─────────────────────────────────────────────────────────────────────────────
//  Utilisé par DMP_ReadRotation ET DMP_ReadBNSignals.
//  Identique à BN_ReadInt de MIA_Dumper_G3_Unifier.cpp lignes 406-415.
inline float DMP_ReadBN_SumOfAlerts(SCStudyInterfaceRef sc, int chart, int study) {
    if (study < 0) return 0.0f;
    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart, study, 2, arr);  // sg2 = Sum of Alerts
    int sz = (int)arr.GetArraySize();
    if (sz == 0) return 0.0f;
    float v = arr[sz - 1];   // Dernière barre (comme l'ancien BN_ReadInt)
    if (!std::isfinite(v) || v >= 1e37f) return 0.0f;
    return v;
}

// ─────────────────────────────────────────────────────────────────────────────
// ROTATION & CLUSTER
// ─────────────────────────────────────────────────────────────────────────────

// Forward declaration (definition complete dans la section BN signals plus bas).
// Necessaire car DMP_ReadRotation (ci-dessous) appelle DMP_ReadBN_Event.
inline float DMP_ReadBN_Event(SCStudyInterfaceRef sc, int chart, int study);

inline void DMP_ReadRotation(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart   = d.is_nq ? DMP_Charts::NQ_FP : DMP_Charts::ES_FP;
    const int rot_id  = d.is_nq ? DMP_Studies::NQ_FP::ROTATION    : DMP_Studies::ES_FP::ROTATION;
    const int rup_id  = d.is_nq ? DMP_Studies::NQ_FP::ROTATION_UP : DMP_Studies::ES_FP::ROTATION_UP;
    const int rdn_id  = d.is_nq ? DMP_Studies::NQ_FP::ROTATION_DN : DMP_Studies::ES_FP::ROTATION_DN;

    d.rotation_value     = DMP_SafeRead(sc, chart, rot_id, 0);
    d.rotation_zz_mid    = DMP_SafeRead(sc, chart, rot_id, 6);
    d.rotation_zz_osc    = DMP_SafeRead(sc, chart, rot_id, 8);
    // ⚠️ FIX 04/03/2026 : Rotation UP/DN = mêmes études [AV] que BN → sg2 "Sum of Alerts"
    //  Ancien code (bot ligne 1483) : ReadStudyValue(sc, chart, ES_FP_ROTATION_UP, 2)
    //  avec arr[size-1]. Même pattern que Color/Absorb.
    // FIX 18/04/2026 : rotation via SG0 evenementiel (pas SumOfAlerts)
    // ROTATION UP/DN n'ont PAS d'Extension Lines dessinees (Draw=None dans SC)
    // -> SumOfAlerts sg2 est VIDE/non-populate par l'etude (pas saturation,
    //    mais feature morte a 0% systematique dans JSONL 15/04).
    // -> SG0 (Color Bar Background Transparent) = vraie detection ponctuelle.
    d.rotation_up_signal = DMP_ReadBN_Event(sc, chart, rup_id);
    d.rotation_dn_signal = DMP_ReadBN_Event(sc, chart, rdn_id);

    // FIX 13/04/2026 : l'ancien code scannait sg0-59 de l'etude Cluster Volume
    // avec la meme approche buggy que les Big Orders. Bug 26 jours : d.cluster_prices
    // etait quasi-vide et JAMAIS utilise dans DMP_Transform.h. Code mort supprime.
    // Remplace par DMP_ReadVolumeClustersFromVAP appele dans DMP_ReadBN_Footprint
    // avec seuil total volume ES=500 / NQ=50 (config SC screenshot 13/04/2026).
}

// ─────────────────────────────────────────────────────────────────────────────
// SIGNAUX BATAILLE NAVALE
// ─────────────────────────────────────────────────────────────────────────────
//
//  ⚠️ FIX 04/03/2026 : les études [AV] Bataille Navale ont 3 subgraphs :
//    sg0 = "Color Bar"       → colorisation visuelle, PAS exploitable par code
//    sg1 = "Extension Lines" → prix des rectangles/boules (zones de support/résistance)
//    sg2 = "Sum of Alerts"   → COMPTEUR CUMULATIF des signaux (le seul lisible par code)
//
//  L'ancien dumper (MIA_Dumper_G3_Unifier.cpp) et le bot (MIA_AutoTrader_BN_v1.cpp)
//  lisaient TOUS les signaux BN depuis sg2 avec arr[size-1] (dernière barre).
//  Le nouveau code lisait sg0 avec arr[sc.Index] → valeurs toujours 0.
//
//  Approche : lire sg2 "Sum of Alerts" via SafeReadLast (même méthode que l'ancien code).
//  La valeur est un compteur cumulatif de session (ex: 3 = trois fois color_up a firé).
//  Transform.SafeBool convertit >0 → 1 (= "au moins un signal Color/Absorb actif").

// Helper dédié BN : défini plus haut (avant DMP_ReadRotation) car utilisé par les deux sections.

// Helper : lit un seuil Big Orders (sg0-46, arr[size-1]) dans des tableaux de 10 prix.
// Utilisé pour lire +10/+30/+100 (NQ) et +100/+150/+400/+1000 (ES).
//
// ⚠️ DEPRECATED 13/04/2026 : cette fonction scanne les subgraphs sg0-46 mais ceux-ci
// ne contiennent PAS les prix des triggers big orders (ils contiennent seulement
// sg0=Trigger pulse 1 barre + sg1-58=Highlight visual props). Résultat : 99% des
// barres remontent 0. Utiliser DMP_ReadBigOrderThresholdViaExtLines à la place.
// Conservée pour référence, mais ne plus appeler.
inline void DMP_ReadBigOrderThreshold(
    SCStudyInterfaceRef sc, int chart,
    int ask_study, int bid_study, float min_price,
    float* ask_out, float* bid_out)
{
    int ac = 0, bc = 0;
    for (int sg = 0; sg <= 46 && (ac < 10 || bc < 10); sg++) {
        if (ac < 10) {
            SCFloatArray arr;
            sc.GetStudyArrayFromChartUsingID(chart, ask_study, sg, arr);
            int sz = (int)arr.GetArraySize();
            if (sz > 0) {
                float v = arr[sz - 1];
                if (std::isfinite(v) && v > min_price) ask_out[ac++] = v;
            }
        }
        if (bc < 10) {
            SCFloatArray arr;
            sc.GetStudyArrayFromChartUsingID(chart, bid_study, sg, arr);
            int sz = (int)arr.GetArraySize();
            if (sz > 0) {
                float v = arr[sz - 1];
                if (std::isfinite(v) && v > min_price) bid_out[bc++] = v;
            }
        }
    }
    for (int i = ac; i < 10; i++) ask_out[i] = DMP_INVALID;
    for (int i = bc; i < 10; i++) bid_out[i] = DMP_INVALID;
}

// ⚠️ DEPRECATED 13/04/2026 (tentative 1) — NE FONCTIONNE PAS.
// Les etudes "Volume At Price Threshold Alert V2" ne dessinent PAS des lignes
// d'extension avec AddLineUntilFutureIntersection. Elles coloriient les cellules
// VolumeAtPrice (VAP) directement dans le footprint quand AskVolume/BidVolume
// depasse un seuil. Cette fonction retourne systematiquement 0.
// Conservee pour reference. Ne plus appeler.
inline void DMP_ReadBigOrderThresholdViaExtLines(
    SCStudyInterfaceRef sc, int chart,
    int ask_study, int bid_study, float min_price,
    float* ask_out, float* bid_out)
{
    int ac = 0, bc = 0;

    if (ask_study >= 0) {
        int n_ask = sc.GetNumLinesUntilFutureIntersection(chart, ask_study);
        for (int i = 0; i < n_ask && ac < 10; i++) {
            int32_t lineID = 0, startIndex = 0, endIndex = 0;
            float lineValue = 0.0f;
            if (sc.GetStudyLineUntilFutureIntersectionByIndex(chart, ask_study, i,
                    lineID, startIndex, lineValue, endIndex) == 0)
                continue;
            if (std::isfinite(lineValue) && lineValue > min_price)
                ask_out[ac++] = lineValue;
        }
    }
    if (bid_study >= 0) {
        int n_bid = sc.GetNumLinesUntilFutureIntersection(chart, bid_study);
        for (int i = 0; i < n_bid && bc < 10; i++) {
            int32_t lineID = 0, startIndex = 0, endIndex = 0;
            float lineValue = 0.0f;
            if (sc.GetStudyLineUntilFutureIntersectionByIndex(chart, bid_study, i,
                    lineID, startIndex, lineValue, endIndex) == 0)
                continue;
            if (std::isfinite(lineValue) && lineValue > min_price)
                bid_out[bc++] = lineValue;
        }
    }
    for (int i = ac; i < 10; i++) ask_out[i] = DMP_INVALID;
    for (int i = bc; i < 10; i++) bid_out[i] = DMP_INVALID;
}

// ⭐ FIX 13/04/2026 (tentative 2 v2) — Lecture Big Orders via VAP direct
// ─────────────────────────────────────────────────────────────────────────────
// Les etudes "Volume At Price Threshold Alert V2" colorient les cellules VAP
// quand AskVolume ou BidVolume depasse un seuil. On reproduit la logique en C++
// en scannant directement sc.VolumeAtPriceForBars.
//
// v2 (13/04/2026 apres-midi) :
//   - Buffer 10 → 20 slots par cote (evite saturation sur ES tres liquide)
//   - Tri par distance au prix courant : garder les 20 plus proches
//   - Dedup strict par prix (min_tick_diff / 2)
//   - Parametre ref_price pour trier (prix courant)
//
// Avantages v2 :
//   - Signal de qualite : les 20 big orders retournes sont les plus pertinents
//     (proches du prix courant), pas les 20 "premiers trouves"
//   - Capture les clusters distribues sur plusieurs barres
//   - Symetrie ES/NQ plus stable (moins de saturation a 10)
//
// Algo :
//   1. Scanner les n_bars_lookback dernieres barres
//   2. Pour chaque cellule VAP : si AskVolume/BidVolume >= threshold → candidat
//   3. Inserer dans un buffer de 20 trie par distance au ref_price
//   4. Si buffer plein, remplacer le plus eloigne si le nouveau est plus proche
//   5. Dedup : skip si le prix est deja dans le buffer
//
// Utilise par DMP_ReadBN_Footprint pour les 7 seuils (ES: 100/150/400/1000, NQ: 10/30/100).
inline void DMP_ReadBigOrdersFromVAP(
    SCStudyInterfaceRef sc,
    float ask_threshold, float bid_threshold,
    int n_bars_lookback,
    float min_price, float tick_size,
    float ref_price,           // prix courant — pour tri par distance
    float* ask_out, float* bid_out)
{
    constexpr int BUF = 20;

    // Init OUT
    for (int i = 0; i < BUF; i++) {
        ask_out[i] = DMP_INVALID;
        bid_out[i] = DMP_INVALID;
    }

    if (!sc.VolumeAtPriceForBars) return;
    if (tick_size <= 0.0f) tick_size = 0.25f;
    if (!std::isfinite(ref_price) || ref_price <= 0.0f) return;

    // Buffers ordonnes par distance au prix courant (index du max garde en cache)
    float ask_dist[BUF]; int ask_count = 0;
    int   ask_max_idx = 0; float ask_max_dist = 0.0f;

    float bid_dist[BUF]; int bid_count = 0;
    int   bid_max_idx = 0; float bid_max_dist = 0.0f;

    const int bar_end = sc.Index;
    const int bar_start = (bar_end - n_bars_lookback + 1 > 0)
                          ? (bar_end - n_bars_lookback + 1) : 0;

    auto insert_sorted = [&](float price, float* out_arr, float* dist_arr,
                              int& count, int& max_idx, float& max_dist) {
        const float d = std::fabs(price - ref_price);

        // Dedup par prix (tolerance 0.5 tick)
        for (int i = 0; i < count; i++) {
            if (std::fabs(out_arr[i] - price) < tick_size * 0.5f) return;
        }

        if (count < BUF) {
            // Buffer pas plein : ajouter
            out_arr[count] = price;
            dist_arr[count] = d;
            if (d > max_dist) {
                max_dist = d;
                max_idx = count;
            }
            count++;
        } else if (d < max_dist) {
            // Buffer plein : remplacer le plus eloigne
            out_arr[max_idx] = price;
            dist_arr[max_idx] = d;
            // Recalculer le nouveau max
            max_dist = 0.0f;
            max_idx = 0;
            for (int i = 0; i < BUF; i++) {
                if (dist_arr[i] > max_dist) {
                    max_dist = dist_arr[i];
                    max_idx = i;
                }
            }
        }
    };

    // Scan des plus recentes vers les plus anciennes
    for (int bar = bar_end; bar >= bar_start; bar--) {
        const int n_levels = sc.VolumeAtPriceForBars->GetSizeAtBarIndex(bar);
        if (n_levels <= 0) continue;

        for (int k = 0; k < n_levels; k++) {
            const s_VolumeAtPriceV2* v = nullptr;
            if (!sc.VolumeAtPriceForBars->GetVAPElementAtIndex(bar, k, &v) || !v)
                continue;
            if (v->Volume == 0) continue;

            const float price = (float)v->PriceInTicks * tick_size;
            if (!std::isfinite(price) || price <= min_price) continue;

            if ((float)v->AskVolume >= ask_threshold) {
                insert_sorted(price, ask_out, ask_dist,
                              ask_count, ask_max_idx, ask_max_dist);
            }
            if ((float)v->BidVolume >= bid_threshold) {
                insert_sorted(price, bid_out, bid_dist,
                              bid_count, bid_max_idx, bid_max_dist);
            }
        }
    }
}

// ⭐ FIX 13/04/2026 — Lecture Cluster Volume via VAP direct (schema 3.7.3)
// ─────────────────────────────────────────────────────────────────────────────
// Reproduit la logique de l'etude Sierra Chart "Volume At Price Threshold Alert V2"
// configuree en Comparison Method = "Total Volume" (seuils ES=500 / NQ=50).
// L'etude colorie les cellules VAP quand v->Volume >= threshold. On reproduit
// ca directement en C++ via sc.VolumeAtPriceForBars, sans dependance a l'etude.
//
// Meme pattern que DMP_ReadBigOrdersFromVAP mais avec v->Volume (total) au lieu
// de v->AskVolume / v->BidVolume separes. Pas de distinction ask/bid : un cluster
// volume est une zone d'interet institutionnelle generale (stop/target niveau).
//
// Usage trader (Jackson 13/04) : "me permet de mettre mon stop ou de tenir un
// trade plus longtemps". Signal de support/resistance solide.
//
// Parametres :
//   threshold    : seuil total volume par cellule (500 ES / 50 NQ)
//   ref_price    : prix courant pour tri par distance
//   out[20]      : 20 prix clusters les plus proches, dedup stricte
inline void DMP_ReadVolumeClustersFromVAP(
    SCStudyInterfaceRef sc,
    float threshold,
    int n_bars_lookback,
    float min_price, float tick_size,
    float ref_price,
    float* cluster_out)
{
    constexpr int BUF = 20;

    for (int i = 0; i < BUF; i++) cluster_out[i] = DMP_INVALID;

    if (!sc.VolumeAtPriceForBars) return;
    if (tick_size <= 0.0f) tick_size = 0.25f;
    if (!std::isfinite(ref_price) || ref_price <= 0.0f) return;

    float cluster_dist[BUF];
    int   cluster_count = 0;
    int   cluster_max_idx = 0;
    float cluster_max_dist = 0.0f;

    const int bar_end = sc.Index;
    const int bar_start = (bar_end - n_bars_lookback + 1 > 0)
                          ? (bar_end - n_bars_lookback + 1) : 0;

    for (int bar = bar_end; bar >= bar_start; bar--) {
        const int n_levels = sc.VolumeAtPriceForBars->GetSizeAtBarIndex(bar);
        if (n_levels <= 0) continue;

        for (int k = 0; k < n_levels; k++) {
            const s_VolumeAtPriceV2* v = nullptr;
            if (!sc.VolumeAtPriceForBars->GetVAPElementAtIndex(bar, k, &v) || !v)
                continue;
            if (v->Volume == 0) continue;

            if ((float)v->Volume < threshold) continue;  // filtre cluster

            const float price = (float)v->PriceInTicks * tick_size;
            if (!std::isfinite(price) || price <= min_price) continue;

            const float d = std::fabs(price - ref_price);

            // Dedup par prix (tolerance 0.5 tick)
            bool dup = false;
            for (int i = 0; i < cluster_count; i++) {
                if (std::fabs(cluster_out[i] - price) < tick_size * 0.5f) {
                    dup = true;
                    break;
                }
            }
            if (dup) continue;

            if (cluster_count < BUF) {
                cluster_out[cluster_count] = price;
                cluster_dist[cluster_count] = d;
                if (d > cluster_max_dist) {
                    cluster_max_dist = d;
                    cluster_max_idx = cluster_count;
                }
                cluster_count++;
            } else if (d < cluster_max_dist) {
                cluster_out[cluster_max_idx] = price;
                cluster_dist[cluster_max_idx] = d;
                cluster_max_dist = 0.0f;
                cluster_max_idx = 0;
                for (int i = 0; i < BUF; i++) {
                    if (cluster_dist[i] > cluster_max_dist) {
                        cluster_max_dist = cluster_dist[i];
                        cluster_max_idx = i;
                    }
                }
            }
        }
    }
}

// Helper: lit sg0 (Trigger per-bar) — retourne prix si condition fire, 0 sinon.
// Différent de DMP_ReadBN_SumOfAlerts qui lit sg2 (compteur cumulatif).
// sg0 avec arr[size-1] = état courant de la dernière barre du chart source.
// Pour les signaux ponctuels (divergence, volume spike), retourne 0
// dès que la barre source suivante n'a pas de fire = pulse temporaire.
// Pour les signaux BN (Bar Signals), même logique = per-bar correct.
inline float DMP_ReadBN_Trigger(SCStudyInterfaceRef sc, int chart, int study) {
    if (study < 0) return 0.0f;
    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart, study, 0, arr);  // sg0 = Trigger (per-bar)
    int sz = (int)arr.GetArraySize();
    if (sz == 0) return 0.0f;
    float v = arr[sz - 1];   // Dernière barre = état courant
    if (!std::isfinite(v) || v >= 1e37f) return 0.0f;
    return v;
}

// 🆕 FIX 09/03/2026 — Lecture des Extension Lines via ACSIL
// Les études COLOR UP/DN utilisent [1] (barre suivante) dans leur formule.
// → sg0 ne fire JAMAIS sur arr[sz-1] car la barre suivante n'existe pas encore.
// → sg1 ne contient PAS les extension lines (c'est un rendu séparé de SC).
// → Les Extension Lines sont accessibles via sc.GetStudyLineUntilFutureIntersectionByIndex()
// → sc.GetNumLinesUntilFutureIntersection(chart, study) = nombre de lignes actives
// → Si > 0 = il y a des zones COLOR actives = ce que le trader voit visuellement.
// Retourne le nombre de zones actives (extension lines non intersectées).
inline float DMP_ReadExtensionLineCount(SCStudyInterfaceRef sc, int chart, int study) {
    if (study < 0) return 0.0f;
    int n = sc.GetNumLinesUntilFutureIntersection(chart, study);
    return (float)(n > 0 ? n : 0);
}

// ─────────────────────────────────────────────────────────────────────────────
// FIX 18/04/2026 — Lecture SG0 evenementielle pour etudes BN Battle Navale
//
// Probleme 1 (saturation ExtensionLineCount) :
//   DMP_ReadExtensionLineCount lit le NOMBRE de lignes d'extension actives
//   (GetNumLinesUntilFutureIntersection). Sur marche trending, les lignes
//   s'accumulent et ne sont jamais intersectees -> compteur >0 permanent
//   -> bn_color_up/dn, bn_double_*, bar_color_up/dn, bar_pressure_* saturent
//   a 1 sur 90% des barres NQ 15/04 (confirme empirique) = features mortes ML.
//
// Probleme 2 (SumOfAlerts vide) :
//   rotation_up/dn lus via DMP_ReadBN_SumOfAlerts (sg2 compteur session).
//   ROTATION UP/DN n'ont PAS d'Extension Lines (Draw=None dans SC) et sg2
//   Sum of Alerts n'est jamais populate par ces etudes -> lit toujours 0
//   -> rotation_up/dn_signal a 0% dans JSONL (feature morte autrement).
//
// Solution unifiee : lire SG0 (Color Bar = prix quand condition TRUE, 0 sinon)
// directement a arr[sz-1] (meme index que DMP_ReadBN_Trigger existant qui
// fonctionne deja pour bn_absorb, bn_long, bar_edge). Convertir en bool 0/1
// (DMP_ReadBN_Trigger renvoie la valeur brute = prix, on veut un flag).
//
// Choix sz-2 (CORRECTION 17/04/2026) :
//   Les etudes [AV] COLOR UP/DN utilisent O[1] dans leur formule ACSIL
//   (= barre SUIVANTE). Sur arr[sz-1] (derniere barre = live en formation),
//   [1] n'existe pas encore -> formule retourne 0/NaN -> 0 fire permanent.
//   Confirmation empirique : 650 barres ES+NQ post-deploy sz-1 = 0.0% color
//   partout. Switch sz-2 (avant-derniere barre fermee, stable car [1] existe).
//   Divergence volontaire avec DMP_ReadBN_Trigger (sz-1) qui est OK pour les
//   etudes sans [1] dans la formule (absorb, long, edge).
//
// Visuel Sierra Chart :
//   SG1 UI = ACSIL sg0 = Color Bar (Point On Low / Background Transparent)
//     = le POINT VERT / FOND COLORE que Jackson voit et trade manuellement
//   SG2 UI = ACSIL sg1 = Extension Lines (horizontales, persistent)
//     = NE PAS utiliser pour detection evenementielle
//   SG3 UI = ACSIL sg2 = Sum of Alerts (compteur cumul session)
//     = NE PAS utiliser pour detection evenementielle
//
// Compatible toutes etudes "Color Bar Based On Alert Condition" :
//   [AV] COLOR UP / DN (ID:26/25 NQ, ID:24/25 ES)
//   [AV] COLOR UP 2 / DN 2 (double stackees)
//   [AV] ROTATION UP / DN (ID:21/22 NQ, ID:19/20 ES) - pas d'Ext Lines mais SG0 OK
//   [AV] DOUBLE ASK / BID (ID:41/42 ES FP)
//   [AV] TRIPLE ASK / BID (ID:37/38 NQ FP)
//
// Difference avec DMP_ReadBN_Trigger :
//   Trigger renvoie la valeur raw (= prix LOW/HIGH selon Input Data) pour
//   usage "est-ce un prix valide", ici on veut un bool 0/1 pour feature ML.
// ─────────────────────────────────────────────────────────────────────────────
inline float DMP_ReadBN_Event(SCStudyInterfaceRef sc, int chart, int study) {
    if (study < 0) return 0.0f;
    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart, study, 0, arr);  // sg0 = Color Bar
    int sz = (int)arr.GetArraySize();
    if (sz < 2) return 0.0f;
    float v = arr[sz - 2];   // avant-derniere : formule [1] stable (fix 17/04)
    if (!std::isfinite(v) || v >= 1e37f) return 0.0f;
    return (v > 0.0f) ? 1.0f : 0.0f;
}

// Retourne le prix de l'Extension Line la plus proche du prix courant.
// Utile pour calculer la distance à la zone COLOR UP/DN la plus proche.
// Retourne DMP_INVALID si aucune extension line active.
inline float DMP_ReadNearestExtensionLine(SCStudyInterfaceRef sc, int chart, int study, float price) {
    if (study < 0 || !DMP_IsPriceValid(price)) return DMP_INVALID;
    int n = sc.GetNumLinesUntilFutureIntersection(chart, study);
    if (n <= 0) return DMP_INVALID;

    float nearest = DMP_INVALID;
    float min_dist = 1e30f;

    for (int i = 0; i < n && i < 50; i++) {  // cap à 50 pour éviter boucle infinie
        int32_t lineID = 0, startIndex = 0, endIndex = 0;
        float lineValue = 0.0f;
        if (sc.GetStudyLineUntilFutureIntersectionByIndex(chart, study, i,
                lineID, startIndex, lineValue, endIndex) == 0)
            continue;
        if (!std::isfinite(lineValue) || lineValue < 100.0f) continue;
        float d = std::fabs(lineValue - price);
        if (d < min_dist) {
            min_dist = d;
            nearest = lineValue;
        }
    }
    return nearest;
}

inline void DMP_ReadBNSignals(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart = d.is_nq ? DMP_Charts::NQ_FP : DMP_Charts::ES_FP;

    // ── Signaux BN — lecture adaptée par type de signal ──────────────────
    //  🆕 FIX 09/03/2026 : COLOR = Extension Lines (sc.GetStudyLineUntilFutureIntersection)
    //  La formule COLOR UP utilise [1] (barre suivante) → sg0 ne fire JAMAIS sur la dernière barre.
    //  Les boules vertes/rouges visibles = Extension Lines = rendu séparé, pas dans les subgraphs.
    //  → Utiliser sc.GetNumLinesUntilFutureIntersection() pour détecter les zones actives.
    //  LONG UP/DN = signal per-bar → sg0 correct (43/98 fires confirmé).
    //  ABSORB, TRIPLE, DOUBLE = Extension Lines activées → ExtensionLineCount.
    //  Si l'étude fire rarement (formule stricte), sg0[last]=0 mais Extension Lines persistent.
    // FIX 18/04/2026 : COLOR via SG0 evenementiel (pas ExtensionLineCount)
    // Les boules vertes/rouges visibles = SG1 UI = ACSIL sg0 Color Bar (Point On Low)
    // Ancien code lisait Extension Lines count = sature 99% sur trending.
    d.bn_color_up   = DMP_ReadBN_Event(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_UP   : DMP_Studies::ES_FP::COLOR_UP);
    d.bn_color_dn   = DMP_ReadBN_Event(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_DN   : DMP_Studies::ES_FP::COLOR_DN);
    // 10/03/2026 : COLOR_UP_2 = double stacké (continuation), séparé de COLOR simple
    d.bn_color_up_2 = DMP_ReadBN_Event(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_UP_2 : DMP_Studies::ES_FP::COLOR_UP_2);
    d.bn_color_dn_2 = DMP_ReadBN_Event(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_DN_2 : DMP_Studies::ES_FP::COLOR_DN_2);
    // ⭐ FIX 15/04/2026 : bn_absorb via sg0 Trigger per-bar
    //   Historique du bug :
    //     - Avant 01/04 : ExtensionLineCount → 100% fire rate (lignes persistentes)
    //     - 01/04 (fix cassé) : calcul VAP custom dans DMP_ReadFPBS
    //         → manque O>C[-1], utilise max_tick au lieu de sc.High réel
    //         → 0.1-2.7% fire rate (trop restrictif, max_tick ≠ High)
    //     - 15/04 : override ici via DMP_ReadBN_Trigger (sg0)
    //         L'étude "Color Bar Based On Alert Condition" populate sg0 avec le prix
    //         Input Data (configuré sur High) quand la condition fire, 0 sinon.
    //         C'est un signal per-bar exact qui suit la formule SC exacte :
    //           =AND(O>C[-1], AVAP(H,0) > BVAP(H,0)*3, AVAP(H,0) > 50)
    //         (confirmé par Jackson via Study Settings Chart #1 ID:25 le 15/04).
    //   Pattern identique à bar_edge_buy/sell ES qui fire ~8% live avec Trigger sg0.
    //   Note : d.bn_absorb_ask/bid sont aussi écrits par DMP_ReadFPBS (formule VAP
    //   cassée du 01/04). L'override ci-dessous ÉCRASE ces valeurs — le calcul
    //   VAP custom reste pour les autres champs fpbs_* mais n'affecte plus bn_absorb.
    d.bn_absorb_ask = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::ABSORB_ASK : DMP_Studies::ES_FP::ABSORB_ASK);
    d.bn_absorb_bid = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::ABSORB_BID : DMP_Studies::ES_FP::ABSORB_BID);

    d.bn_long_up    = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::LONG_UP    : DMP_Studies::ES_FP::LONG_UP);
    d.bn_long_dn    = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::LONG_DN    : DMP_Studies::ES_FP::LONG_DN);

    // ES = Double Ask/Bid — NQ = Triple Ask/Bid → Extension Lines
    if (!d.is_nq) {
        // FIX 18/04/2026 : DOUBLE via SG0 evenementiel (pas ExtensionLineCount)
        d.bn_double_ask  = DMP_ReadBN_Event(sc, chart, DMP_Studies::ES_FP::DOUBLE_ASK);
        d.bn_double_bid  = DMP_ReadBN_Event(sc, chart, DMP_Studies::ES_FP::DOUBLE_BID);
        d.bn_triple_ask  = DMP_BOOL_FALSE;
        d.bn_triple_bid  = DMP_BOOL_FALSE;
    } else {
        d.bn_double_ask  = DMP_BOOL_FALSE;
        d.bn_double_bid  = DMP_BOOL_FALSE;
        // FIX 18/04/2026 : TRIPLE via SG0 evenementiel (pas ExtensionLineCount)
        d.bn_triple_ask  = DMP_ReadBN_Event(sc, chart, DMP_Studies::NQ_FP::TRIPLE_ASK);
        d.bn_triple_bid  = DMP_ReadBN_Event(sc, chart, DMP_Studies::NQ_FP::TRIPLE_BID);
    }

    // 🆕 BUG #10 — Volume UP/DOWN + Edge Zones Footprint (05/03/2026)
    // 🆕 FIX 12/03/2026 — ES VOLUME UP/DOWN ajoutés (ID:2, ID:4)
    // ⭐ FIX 15/04/2026 : fp_edge_* via sg0 Trigger per-bar (ex-SumOfAlerts sg2 cassé)
    //   Bug : DMP_ReadBN_SumOfAlerts lit sg2 "Sum of Alerts" qui n'est PAS populé
    //   pour les études "Color Bar Based On Alert Condition" (retourne 0 ou valeur
    //   indéfinie). Fire rate ES 0.1% live 20260415 au lieu du ~8% attendu.
    //   Fix : utiliser DMP_ReadBN_Trigger (sg0) qui populate le prix Output (High)
    //   quand la condition fire, 0 sinon. Pattern identique à bar_edge_* qui
    //   fire ~8% avec Trigger sg0 sur les études Edge Zones 600%DIAG.
    if (!d.is_nq) {
        d.bn_volume_up   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::ES_FP::VOLUME_UP);
        d.bn_volume_dn   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::ES_FP::VOLUME_DN);
        d.fp_edge_buy    = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::ES_FP::EDGE_BUY);
        d.fp_edge_sell   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::ES_FP::EDGE_SELL);
        d.fp_edge_buy_2  = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::ES_FP::EDGE_BUY_R1);
        d.fp_edge_sell_2 = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::ES_FP::EDGE_SELL_R1);
    } else {
        // 🆕 FIX : Trigger(sg0) au lieu de SumOfAlerts(sg2)
        // Volume spike = événement ponctuel, pas zone permanente
        d.bn_volume_up   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::NQ_FP::VOLUME_UP);
        d.bn_volume_dn   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::NQ_FP::VOLUME_DN);
        d.fp_edge_buy    = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::NQ_FP::EDGE_BUY);
        d.fp_edge_sell   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::NQ_FP::EDGE_SELL);
        d.fp_edge_buy_2  = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::NQ_FP::EDGE_BUY_2);
        d.fp_edge_sell_2 = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::NQ_FP::EDGE_SELL_2);
    }

    // Big Orders — TOUS LES SEUILS (BUG #9 : +10/+30/+100 NQ, +100/+150/+400/+1000 ES)
    // ⚠️ FIX 04/03/2026 BUG #1 : sg0-46, arr[size-1] (ne marche pas, DEPRECATED)
    // ⚠️ FIX 05/03/2026 BUG #9 : ajout TOUS les seuils — seul +100 était lu (DEPRECATED)
    // ⚠️ FIX 13/04/2026 tentative 1 : Extension Lines — NE FONCTIONNE PAS
    //    (les etudes Volume At Price Threshold Alert V2 n'utilisent pas AddLine).
    // ⭐ FIX 13/04/2026 tentative 2 : scan direct des VAP cells.
    //    Les etudes colorient les cellules VolumeAtPrice quand Ask/Bid depasse un
    //    seuil. On reproduit la meme logique en C++ directement via
    //    sc.VolumeAtPriceForBars, sans aucune dependance aux etudes SC.
    //    Seuils hardcodes : ES=100/150/400/1000 | NQ=10/30/100.
    //    Lookback : 60 barres (= 1 heure sur chart 1min).
    //    Cf. helper DMP_ReadBigOrdersFromVAP.
    {
        const float min_price = d.is_nq ? 15000.0f : 5000.0f;
        const float ts        = d.tick_size > 0.0f ? d.tick_size : 0.25f;
        const float ref_price = d.price_close;  // tri par distance au prix courant
        constexpr int LOOKBACK_BARS = 60;

        // Seuil principal : +100 (les deux symboles)
        DMP_ReadBigOrdersFromVAP(sc,
            100.0f, 100.0f, LOOKBACK_BARS, min_price, ts, ref_price,
            d.bn_ask100, d.bn_bid100);

        // Seuils supplementaires — NQ: +10, +30 | ES: +150, +400, +1000
        if (d.is_nq) {
            DMP_ReadBigOrdersFromVAP(sc,
                10.0f, 10.0f, LOOKBACK_BARS, min_price, ts, ref_price,
                d.bn_ask_extra1, d.bn_bid_extra1);
            DMP_ReadBigOrdersFromVAP(sc,
                30.0f, 30.0f, LOOKBACK_BARS, min_price, ts, ref_price,
                d.bn_ask_extra2, d.bn_bid_extra2);
            for (int i = 0; i < 20; i++) {
                d.bn_ask_extra3[i] = DMP_INVALID;
                d.bn_bid_extra3[i] = DMP_INVALID;
            }
        } else {
            DMP_ReadBigOrdersFromVAP(sc,
                150.0f, 150.0f, LOOKBACK_BARS, min_price, ts, ref_price,
                d.bn_ask_extra1, d.bn_bid_extra1);
            DMP_ReadBigOrdersFromVAP(sc,
                400.0f, 400.0f, LOOKBACK_BARS, min_price, ts, ref_price,
                d.bn_ask_extra2, d.bn_bid_extra2);
            DMP_ReadBigOrdersFromVAP(sc,
                1000.0f, 1000.0f, LOOKBACK_BARS, min_price, ts, ref_price,
                d.bn_ask_extra3, d.bn_bid_extra3);
        }

        // ⭐ SCHEMA 3.7.3 (13/04/2026) — Cluster Volume via VAP direct
        // Seuil total volume ES=500 / NQ=50 (config SC "Volume At Price Threshold
        // Alert V2" Comparison Method = Total Volume). Utilise pour stop/target.
        const float cluster_threshold = d.is_nq ? 50.0f : 500.0f;
        DMP_ReadVolumeClustersFromVAP(sc,
            cluster_threshold, LOOKBACK_BARS, min_price, ts, ref_price,
            d.cluster_prices);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// BN SIGNAUX CHART BARRES + EXTENSION LINES — BUG #8 (04/03/2026)
// ─────────────────────────────────────────────────────────────────────────────
//  Le Bot combine signaux de 2 charts : Footprint (Chart 1/2) + Barres (Chart 25/23).
//  Le DMP ne lisait que le Footprint. Cette fonction ajoute la lecture Barres.
//
//  Subgraphs (Color Bar Based On Alert Condition) :
//    sg0 = Output (prix quand condition fire, 0 sinon) → DMP_ReadBN_Trigger
//    sg1 = Extension Lines (prix S/R non-touché)       → DMP_SafeReadLast
//    sg2 = Sum of Alerts (compteur cumulatif — inutile per-bar)

// Helper DMP_ReadBN_Trigger → déplacé avant DMP_ReadBNSignals (BUG #12 v2)

inline void DMP_ReadBarSignals(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart = d.is_nq ? DMP_Charts::NQ_BARRES : DMP_Charts::ES_BARRES;

    // ── A. Signaux booléens ─────────────────────────────────────────────
    // FIX 18/04/2026 : COLOR via SG0 evenementiel (pas ExtensionLineCount)
    // LONG/EDGE = per-bar → sg0 correct (deja)
    // PRESSURE (DOUBLE/TRIPLE) = SG0 evenementiel (fix)
    d.bar_color_up    = DMP_ReadBN_Event(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_BARRES::COLOR_UP    : DMP_Studies::ES_BARRES::COLOR_UP);
    d.bar_color_dn    = DMP_ReadBN_Event(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_BARRES::COLOR_DN    : DMP_Studies::ES_BARRES::COLOR_DN);
    d.bar_long_up_bar = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_BARRES::LONG_UP_BAR : DMP_Studies::ES_BARRES::LONG_UP_BAR);
    d.bar_long_dn_bar = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_BARRES::LONG_DN_BAR : DMP_Studies::ES_BARRES::LONG_DN_BAR);
    d.bar_long_dn_up  = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_BARRES::LONG_DN_UP  : DMP_Studies::ES_BARRES::LONG_DN_UP);
    d.bar_long_up_dn  = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_BARRES::LONG_UP_DN  : DMP_Studies::ES_BARRES::LONG_UP_DN);
    d.bar_edge_buy    = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_BARRES::EDGE_BUY    : DMP_Studies::ES_BARRES::EDGE_BUY);
    d.bar_edge_sell   = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_BARRES::EDGE_SELL   : DMP_Studies::ES_BARRES::EDGE_SELL);

    // FIX 18/04/2026 : DOUBLE/TRIPLE via SG0 evenementiel (pas ExtensionLineCount)
    if (!d.is_nq) {
        d.bar_pressure_ask = DMP_ReadBN_Event(sc, chart, DMP_Studies::ES_BARRES::DOUBLE_ASK);
        d.bar_pressure_bid = DMP_ReadBN_Event(sc, chart, DMP_Studies::ES_BARRES::DOUBLE_BID);
    } else {
        d.bar_pressure_ask = DMP_ReadBN_Event(sc, chart, DMP_Studies::NQ_BARRES::TRIPLE_ASK);
        d.bar_pressure_bid = DMP_ReadBN_Event(sc, chart, DMP_Studies::NQ_BARRES::TRIPLE_BID);
    }

    // ── B. Extension Lines prix — via sc.GetStudyLineUntilFutureIntersection ──
    // 🆕 FIX 09/03/2026 : Les Extension Lines ne sont PAS dans sg1.
    //   Elles sont un rendu séparé de SC, accessible uniquement via ACSIL API.
    //   DMP_ReadNearestExtensionLine() retourne le prix de la zone la plus proche.
    d.ext_color_up_px  = DMP_ReadNearestExtensionLine(sc, chart,
                         d.is_nq ? DMP_Studies::NQ_BARRES::COLOR_UP    : DMP_Studies::ES_BARRES::COLOR_UP,    d.price_close);
    d.ext_color_dn_px  = DMP_ReadNearestExtensionLine(sc, chart,
                         d.is_nq ? DMP_Studies::NQ_BARRES::COLOR_DN    : DMP_Studies::ES_BARRES::COLOR_DN,    d.price_close);
    d.ext_long_up_px   = DMP_ReadNearestExtensionLine(sc, chart,
                         d.is_nq ? DMP_Studies::NQ_BARRES::LONG_UP_BAR : DMP_Studies::ES_BARRES::LONG_UP_BAR, d.price_close);
    d.ext_long_dn_px   = DMP_ReadNearestExtensionLine(sc, chart,
                         d.is_nq ? DMP_Studies::NQ_BARRES::LONG_DN_BAR : DMP_Studies::ES_BARRES::LONG_DN_BAR, d.price_close);
    d.ext_edge_buy_px  = DMP_ReadNearestExtensionLine(sc, chart,
                         d.is_nq ? DMP_Studies::NQ_BARRES::EDGE_BUY    : DMP_Studies::ES_BARRES::EDGE_BUY,    d.price_close);
    d.ext_edge_sell_px = DMP_ReadNearestExtensionLine(sc, chart,
                         d.is_nq ? DMP_Studies::NQ_BARRES::EDGE_SELL   : DMP_Studies::ES_BARRES::EDGE_SELL,   d.price_close);
}

// ─────────────────────────────────────────────────────────────────────────────
// VWAP JOURNALIER
// Source : Chart VP (26=ES / 27=NQ) Study 3 — c'est là que le VWAP journalier
//          a des valeurs actives. Chart FP (1/2) VWAP studies retournent null.
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadVWAPDay(SCStudyInterfaceRef sc, DMP_RawData& d) {
    // ⚠️ FIX 04/03/2026 BUG #2 — ITÉRATION 2 :
    //  Itération 1 : source VP (chart 27) → BARRES (chart 23 study 1) = ERREUR !
    //    Study 1 sur chart 23 est un VWAP Weekly, pas Daily (valeur ≈ VWAP W).
    //  Itération 2 : retour au chart VP (26/27) study 3, MAIS avec SafeReadLast
    //    car chart VP = 30 Min, DMP host = 10 Min → cross-timeframe.
    //    SafeRead (arr[sc.Index]) retournait null, SafeReadLast (arr[size-1]) = valeur courante.
    //    Même pattern que VP Current fix (BUG #3).
    const int chart = d.is_nq ? DMP_Charts::NQ_VP : DMP_Charts::ES_VP;
    const int study = d.is_nq ? DMP_Studies::NQ_VP::VWAP_DAY : DMP_Studies::ES_VP::VWAP_DAY;

    d.vwap_day      = DMP_SafeReadLast(sc, chart, study, 0);
    d.vwap_day_sd1u = DMP_SafeReadLast(sc, chart, study, 1);
    d.vwap_day_sd1d = DMP_SafeReadLast(sc, chart, study, 2);
    d.vwap_day_sd2u = DMP_SafeReadLast(sc, chart, study, 3);
    d.vwap_day_sd2d = DMP_SafeReadLast(sc, chart, study, 4);
    d.vwap_day_sd3u = DMP_SafeReadLast(sc, chart, study, 5);  // SD+3 Top Band 3
    d.vwap_day_sd3d = DMP_SafeReadLast(sc, chart, study, 6);  // SD-3 Bottom Band 3

    // ── VWAP Slope (pente points/barre normalisée) ─────────────────────────
    // ⚠️ FIX 04/03/2026 BUG #6 : Chart VP = 30 Min, ancien dumper = 1 Min.
    //  Ancien: N=10 (10min), N=30 (30min) → direction court terme Layer 3.
    //  Nouveau: Chart VP 30min → N=3 (~1h30), N=10 (~5h).
    //  Guard: si vwap[sz-1-N] est loin du vwap courant (>50% de l'ATR),
    //  c'est probablement un reset de session → slope invalidé.
    //  Normalisation: divise par ATR pour rendre comparable ES vs NQ.
    if (DMP_IsValid(d.vwap_day) && d.vwap_day > 0.0f) {
        SCFloatArray vwap_arr;
        sc.GetStudyArrayFromChartUsingID(chart, study, 0, vwap_arr);
        int sz = (int)vwap_arr.GetArraySize();
        float atr_guard = DMP_IsValid(d.atr_daily) && d.atr_daily > 0 ? d.atr_daily * 0.5f : 9999.0f;

        // Slope court (N=3 barres VP 30min ≈ 1h30)
        if (sz > 3) {
            float v_ago = vwap_arr[sz - 1 - 3];
            if (v_ago > 0.0f && std::isfinite(v_ago)
                && std::fabs(d.vwap_day - v_ago) < atr_guard)
                d.vwap_slope_10 = (d.vwap_day - v_ago) / 3.0f;
        }
        // Slope long (N=10 barres VP 30min ≈ 5h)
        if (sz > 10) {
            float v_ago = vwap_arr[sz - 1 - 10];
            if (v_ago > 0.0f && std::isfinite(v_ago)
                && std::fabs(d.vwap_day - v_ago) < atr_guard)
                d.vwap_slope_30 = (d.vwap_day - v_ago) / 10.0f;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// VWAP WEEKLY & MONTHLY + ATR + MA (Daily Charts)
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadDaily(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart = d.is_nq ? DMP_Charts::NQ_DAILY : DMP_Charts::ES_DAILY;

    // ATR — chart daily, "reference line" → SafeReadLast
    d.atr_daily = DMP_SafeReadLast(sc, chart,
                    d.is_nq ? DMP_Studies::NQ_DAILY::ATR : DMP_Studies::ES_DAILY::ATR, 0);

    // Moving Averages — chart daily → SafeReadLast
    const int ma_id = d.is_nq ? DMP_Studies::NQ_DAILY::MA : DMP_Studies::ES_DAILY::MA;
    d.ma_fast = DMP_SafeReadLast(sc, chart, ma_id, 0);
    d.ma_slow = DMP_SafeReadLast(sc, chart, ma_id, 1);

    // ── VWAP Weekly & Monthly — DEPUIS CHART BARRES INTRADAY ──────────────
    //  ⚠️ FIX v6 — 12/03/2026 — DMP_SafeReadLast (ByID + arr[LAST])
    //
    //  Historique des bugs et tentatives:
    //    v1: ByID + arr[sc.Index] → SAME values (W==M) car sc.Index mauvais cross-chart
    //    v2-v4: ByNum (position) + arr[sc.Index] → mauvaises valeurs (bar historique)
    //    v5: ByNum + arr[LAST] → positions fragiles, décalées par d'autres études
    //    v6: ByID + arr[LAST] → SOLUTION DÉFINITIVE
    //
    //  Preuve: VWAP_Probe_Dual (chart 23 → chart 25) avec ByID + arr[LAST]:
    //    ES id=23 → 6752 ✅ (Weekly)   ES id=33 → 6795 ✅ (Monthly)
    //    W ≠ M confirmé ! Le bug SAME n'existe qu'avec arr[sc.Index].
    //
    //  DMP_SafeReadLast = GetStudyArrayFromChartUsingID + arr[GetArraySize()-1]
    //  Pas de positions, pas de study_number → robuste même si on réordonne les études.
    const int chart_b = d.is_nq ? DMP_Charts::NQ_BARRES : DMP_Charts::ES_BARRES;
    const int vw_id   = d.is_nq ? DMP_Studies::NQ_BARRES::VWAP_WEEKLY  : DMP_Studies::ES_BARRES::VWAP_WEEKLY;
    const int vm_id   = d.is_nq ? DMP_Studies::NQ_BARRES::VWAP_MONTHLY : DMP_Studies::ES_BARRES::VWAP_MONTHLY;

    d.vwap_weekly      = DMP_SafeReadLast(sc, chart_b, vw_id, 0);  // sg0 = VWAP
    d.vwap_weekly_sd1u = DMP_SafeReadLast(sc, chart_b, vw_id, 1);  // sg1 = SD+1
    d.vwap_weekly_sd1d = DMP_SafeReadLast(sc, chart_b, vw_id, 2);  // sg2 = SD-1

    d.vwap_monthly      = DMP_SafeReadLast(sc, chart_b, vm_id, 0);  // sg0 = VWAP
    d.vwap_monthly_sd1u = DMP_SafeReadLast(sc, chart_b, vm_id, 1);  // sg1 = SD+1
    d.vwap_monthly_sd1d = DMP_SafeReadLast(sc, chart_b, vm_id, 2);  // sg2 = SD-1

    // ── Debug log (200 premières barres) — À SUPPRIMER après validation ──────
    {
        static int s_vwap_dbg_count = 0;
        if (s_vwap_dbg_count < 200) {
            s_vwap_dbg_count++;
#ifdef _WIN32
            CreateDirectoryA("D:\\TRADING_SIERRA_CHART_AUTO\\LOGS", NULL);
            CreateDirectoryA("D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\DEBUG", NULL);
            FILE* dbg = fopen("D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\DEBUG\\DMP_VWAP_WM_debug.log", "a");
            if (dbg) {
                fprintf(dbg,
                    "[bar#%d] %s chart=%d | W_id=%d W=%.2f W_sd1u=%.2f"
                    " | M_id=%d M=%.2f M_sd1u=%.2f"
                    " | SAME=%d | px=%.2f | FIX=v6_ByID_Last\n",
                    sc.Index, d.is_nq ? "NQ" : "ES", chart_b,
                    vw_id, d.vwap_weekly, d.vwap_weekly_sd1u,
                    vm_id, d.vwap_monthly, d.vwap_monthly_sd1u,
                    (int)(d.vwap_weekly == d.vwap_monthly),
                    d.price_close);
                fclose(dbg);
            }
#endif
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MENTHORQ — GAMMA LEVELS & BLIND SPOTS
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadMenthorQ(SCStudyInterfaceRef sc, DMP_RawData& d) {

    // Chart ES_BARRES (25) Study 2 pour ES / Chart NQ_BARRES (23) Study 25 pour NQ
    const int chart_g  = d.is_nq ? DMP_Charts::NQ_BARRES : DMP_Charts::ES_BARRES;
    const int study_g  = d.is_nq ? DMP_Studies::NQ_BARRES::MQ_GAMMA : DMP_Studies::ES_BARRES::MQ_GAMMA;

    // MenthorQ Gamma — lignes horizontales, "reference line" → SafeReadLast
    d.mq_call      = DMP_SafeReadLast(sc, chart_g, study_g, 0);
    d.mq_put       = DMP_SafeReadLast(sc, chart_g, study_g, 1);
    d.mq_hvl       = DMP_SafeReadLast(sc, chart_g, study_g, 2);
    // sg3=1d_min / sg4=1d_max — targets de range journalier MenthorQ
    d.mq_1d_min    = DMP_SafeReadLast(sc, chart_g, study_g, 3);
    d.mq_1d_max    = DMP_SafeReadLast(sc, chart_g, study_g, 4);
    d.mq_call_0dte = DMP_SafeReadLast(sc, chart_g, study_g, 5);
    d.mq_put_0dte  = DMP_SafeReadLast(sc, chart_g, study_g, 6);
    d.mq_hvl_0dte  = DMP_SafeReadLast(sc, chart_g, study_g, 7);

    // GEX 1..10 → sg9..18 — reference lines
    for (int i = 0; i < 10; i++) {
        d.mq_gex[i] = DMP_SafeReadLast(sc, chart_g, study_g, 9 + i);
    }

    // Blind Spots — reference lines → SafeReadLast
    if (!d.is_nq) {
        const int study_bs = DMP_Studies::ES_COMPOSITE::MQ_BLIND;
        for (int i = 0; i < 10; i++) {
            float v = DMP_SafeReadLast(sc, DMP_Charts::ES_COMPOSITE, study_bs, i);
            d.mq_blind[i] = DMP_IsPriceValid(v) ? v : DMP_INVALID;
        }
    } else {
        const int study_bs = DMP_Studies::NQ_COMPOSITE::MQ_BLIND;
        for (int i = 0; i < 10; i++) {
            float v = DMP_SafeReadLast(sc, DMP_Charts::NQ_COMPOSITE, study_bs, i);
            d.mq_blind[i] = DMP_IsPriceValid(v) ? v : DMP_INVALID;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// VIX
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadVIX(SCStudyInterfaceRef sc, DMP_RawData& d) {
    // Prix courant VIX = Close du chart 15
    // ⚠️ GetChartBaseData retourne les barres BRUTES du chart source,
    //    SANS synchronisation avec le chart hôte. sc.Index est l'index
    //    du chart hôte (1min) → si chart 15 est 30min ou daily, sc.Index
    //    pointe à la MAUVAISE barre. On utilise arr[sz-1] (dernière barre)
    //    pour toujours lire le prix VIX le plus récent.
    SCGraphData chart_data;
    sc.GetChartBaseData(DMP_Charts::VIX_MQ, chart_data);
    SCFloatArray close_arr = chart_data[SC_LAST];
    int vix_sz = (int)close_arr.GetArraySize();
    if (vix_sz > 0) {
        float vix_last = close_arr[vix_sz - 1];
        d.vix_level = (std::isfinite(vix_last) && vix_last > 0.0f && vix_last < 200.0f)
                      ? vix_last : DMP_INVALID;
    } else {
        d.vix_level = DMP_INVALID;
    }

    // Niveaux MenthorQ sur VIX — reference lines → SafeReadLast
    d.vix_call = DMP_SafeReadLast(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 0);
    d.vix_put  = DMP_SafeReadLast(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 1);
    d.vix_hvl  = DMP_SafeReadLast(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 2);

    // Guard VIX MenthorQ : après 16h ET, MQ reset sg2 (HVL) à 0.0
    // VIX HVL réaliste = 10..60. En dehors → invalider pour éviter dist_vix_hvl aberrant.
    if (d.vix_hvl < 5.0f || d.vix_hvl > 80.0f) d.vix_hvl = DMP_INVALID;
    if (d.vix_call < 5.0f || d.vix_call > 80.0f) d.vix_call = DMP_INVALID;
    if (d.vix_put  < 5.0f || d.vix_put  > 80.0f) d.vix_put  = DMP_INVALID;

    // Niveaux VIX 0DTE (sg5=Call, sg6=Put, sg7=HVL)
    d.vix_call_0dte = DMP_SafeReadLast(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 5);
    d.vix_put_0dte  = DMP_SafeReadLast(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 6);
    d.vix_hvl_0dte  = DMP_SafeReadLast(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 7);
    if (d.vix_call_0dte < 5.0f || d.vix_call_0dte > 80.0f) d.vix_call_0dte = DMP_INVALID;
    if (d.vix_put_0dte  < 5.0f || d.vix_put_0dte  > 80.0f) d.vix_put_0dte  = DMP_INVALID;
    if (d.vix_hvl_0dte  < 5.0f || d.vix_hvl_0dte  > 80.0f) d.vix_hvl_0dte  = DMP_INVALID;

    // GEX VIX (sg9..18)
    for (int i = 0; i < 10; i++)
        d.vix_gex[i] = DMP_SafeReadLast(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 9 + i);
}

// ─────────────────────────────────────────────────────────────────────────────
// VOLUME PROFILE — Session Courante & Précédente
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadVolumeProfile(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart = d.is_nq ? DMP_Charts::NQ_VP : DMP_Charts::ES_VP;

    // VP Session courante
    // ⚠️ FIX 04/03/2026 BUG #3 : VP Current NQ = null sur 51/51 barres.
    //  Chart 27 NQ_VP = 30 Min, DMP host = 10 Min → cross-timeframe.
    //  DMP_SafeRead (arr[sc.Index]) ne résout pas correctement cross-TF pour VP.
    //  Fix : DMP_SafeReadLast (arr[size-1]) — identique à VP Previous qui fonctionne.
    //  VPOC/VAH/VAL sont des niveaux de session → la dernière valeur = la valeur courante.
    const int vp_cur = d.is_nq ? DMP_Studies::NQ_VP::VP_CURRENT : DMP_Studies::ES_VP::VP_CURRENT;
    d.cur_vpoc     = DMP_SafeReadLast(sc, chart, vp_cur, 1);
    d.cur_vah      = DMP_SafeReadLast(sc, chart, vp_cur, 2);
    d.cur_val      = DMP_SafeReadLast(sc, chart, vp_cur, 3);
    d.cur_vwap_vp  = DMP_SafeReadLast(sc, chart, vp_cur, 4);

    // VP Session précédente (Previous) — "reference line" → SafeReadLast
    const int vp_prv = d.is_nq ? DMP_Studies::NQ_VP::VP_PREVIOUS : DMP_Studies::ES_VP::VP_PREVIOUS;
    d.prev_vpoc = DMP_SafeReadLast(sc, chart, vp_prv, 1);
    d.prev_vah  = DMP_SafeReadLast(sc, chart, vp_prv, 2);
    d.prev_val  = DMP_SafeReadLast(sc, chart, vp_prv, 3);
    d.prev_vwap = DMP_SafeReadLast(sc, chart, vp_prv, 4);

    // Previous VWAP SD+1/-1 — reference lines → SafeReadLast
    const int vp_pvw = d.is_nq ? DMP_Studies::NQ_VP::VP_PREV_WAPS : DMP_Studies::ES_VP::VP_PREV_WAPS;
    d.prev_vwap_sd1u = DMP_SafeReadLast(sc, chart, vp_pvw, 12);
    d.prev_vwap_sd1d = DMP_SafeReadLast(sc, chart, vp_pvw, 13);
}

// ─────────────────────────────────────────────────────────────────────────────
// SESSION — IB, OHLC, Open Cash
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadSession(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart_b = d.is_nq ? DMP_Charts::NQ_BARRES : DMP_Charts::ES_BARRES;
    const int chart_v = d.is_nq ? DMP_Charts::NQ_VP     : DMP_Charts::ES_VP;

    // Open 8h30 ET — reference line → SafeReadLast
    const int open_id = d.is_nq ? DMP_Studies::NQ_BARRES::OPEN_830 : DMP_Studies::ES_BARRES::OPEN_830;
    d.open_830 = DMP_SafeReadLast(sc, chart_b, open_id, 0);

    // Session High / Low — reference lines → SafeReadLast
    const int hh_id = d.is_nq ? DMP_Studies::NQ_BARRES::HH_SESSION : DMP_Studies::ES_BARRES::HH_SESSION;
    const int ll_id = d.is_nq ? DMP_Studies::NQ_BARRES::LL_SESSION : DMP_Studies::ES_BARRES::LL_SESSION;
    d.sess_high = DMP_SafeReadLast(sc, chart_b, hh_id, 1);   // sg1 = High
    d.sess_low  = DMP_SafeReadLast(sc, chart_b, ll_id, 2);   // sg2 = Low

    // IB High / Low — Calculé dans DMP_Main.cpp via accumulateur progressif
    // ─────────────────────────────────────────────────────────────────────────────
    //  HISTORIQUE :
    //    Bug #18 (27/03) : scan backward sc.High[i] cassé sur charts footprint
    //    (sc.High[i] pour barres passées ne retourne pas le vrai high du prix).
    //
    //  FIX (30/03/2026) : Accumulateur progressif dans DMP_Main.cpp.
    //    A chaque barre fermée dans [09:30, 10:30] ET, on met à jour le running
    //    max(sc.High[sc.Index]) / min(sc.Low[sc.Index]) via PersistentFloat.
    //    sc.High[sc.Index] pour la barre COURANTE est toujours correct.
    //    Apres 10:30 ET, les valeurs sont figées pour le reste de la session.
    //
    //  d.ib_high / d.ib_low restent INVALID ici — écrits par DMP_Main.cpp.
    // ─────────────────────────────────────────────────────────────────────────────

    // Open Cash 9h30 ET — reference line → SafeReadLast
    const int ohlc_id = d.is_nq ? DMP_Studies::NQ_VP::OHLC_SESSION : DMP_Studies::ES_VP::OHLC_SESSION;
    d.open_cash = DMP_SafeReadLast(sc, chart_v, ohlc_id, 0);  // sg0 = Open session
}

// ─────────────────────────────────────────────────────────────────────────────
// OVERNIGHT HIGH/LOW
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadOVN(SCStudyInterfaceRef sc, DMP_RawData& d) {
    // Chart 30/31 Study 8 "OVN HIGH LOW" (High/Low for Time Period 18h→9h29 ET)
    // sg0=High, sg1=Low — confirmé scan 02/03/2026
    const int chart = d.is_nq ? DMP_Charts::NQ_COMPOSITE : DMP_Charts::ES_COMPOSITE;
    const int study = d.is_nq ? DMP_Studies::NQ_COMPOSITE::OVN_HL
                              : DMP_Studies::ES_COMPOSITE::OVN_HL;

    // OVN = "High/Low for Time Period" : peint SEULEMENT pendant 18h→9h29 ET.
    // Après 9h30, arr[last_bar]=0 car la dernière barre est hors fenêtre.
    // SafeReadLastValid scanne en arrière pour trouver la dernière valeur
    // réelle (= la barre 9h29, juste avant le RTH).
    d.ovn_high = DMP_SafeReadLastValid(sc, chart, study, 0); // sg0=High
    d.ovn_low  = DMP_SafeReadLastValid(sc, chart, study, 1); // sg1=Low

    // Validation cohérence par rapport au prix courant
    if (DMP_IsPriceValid(d.ovn_high) && DMP_IsPriceValid(d.price_close)) {
        float ratio = d.ovn_high / d.price_close;
        if (ratio < 0.8f || ratio > 1.2f) {
            // OVN aberrant (>20% d'écart) → invalider
            d.ovn_high = DMP_INVALID;
            d.ovn_low  = DMP_INVALID;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// DELTA DIVERGENCE — reconstruction fidele Sierra Chart Daily OHLC (17/04/2026)
// ─────────────────────────────────────────────────────────────────────────────
//
// Remplace le bug DMP_ReadExtensionLineCount (v3 07/04) qui retourne 100% a 1
// permanent sur marche trending (confirme empiriquement 20260416 ES+NQ
// 910 barres = 100% a 1). Cause : ExtensionLines persistent jusqu'a intersection
// prix -> jamais intersectees en trending -> count > 0 permanent.
//
// Formule SC identifiee (captures Jackson 17/04) :
//   Etude ID33 "LINKED TO DELTA DIVERGENCE" = "Daily OHLC" (SierraChartStudies_64)
//   SG2 (ACSIL sg1) = Daily High cumulatif (running max du jour)
//   SG3 (ACSIL sg2) = Daily Low  cumulatif (running min du jour)
//
//   DELTA DIV BUY  : AND(SG3 < SG3[-1], AV-BV >= 0)
//                  = nouveau Daily Low + delta bullish
//                  = new session low + buyers en embuscade -> rejection/bounce
//
//   DELTA DIV SELL : AND(SG2 > SG2[-1], AV-BV <= 0)
//                  = nouveau Daily High + delta bearish
//                  = new session high + sellers en embuscade -> false breakout
//
// AV-BV = ask_volume - bid_volume = fpbs_delta (= delta_bar feature en sortie).
// Verifie empiriquement : delta_bar == buy_vol - sell_vol exact match ES + NQ.
//
// Trading date CME : reset a 18:00 ET (session evening open).
// Validation Python 20260416 NQ : 2 triggers SELL (06:07, 06:10 UTC) matchent
// exactement les 2 triangles visibles sur Sierra Chart (confirme par Jackson).
// Fire rate empirique : 0.44% NQ / 0.22% ES = evenement rare et fort.
//
// PersistVars per-study-instance : chaque chart (ES, NQ) a son etat isole,
// donc pas besoin de separer _ES / _NQ. Indices 200-202 libres (scan exhaustif
// codebase : 50-74 HVN/LVN, 80-92 Writer/OpenType, 100-192 divers).
// ─────────────────────────────────────────────────────────────────────────────

constexpr int DMP_PERSIST_DIV_DAILY_HIGH  = 200;
constexpr int DMP_PERSIST_DIV_DAILY_LOW   = 201;
constexpr int DMP_PERSIST_DIV_SESSION_DAY = 202;

inline void DMP_ReadDeltaDivergenceClean(SCStudyInterfaceRef sc, DMP_RawData& d) {
    float& daily_high = sc.GetPersistentFloat(DMP_PERSIST_DIV_DAILY_HIGH);
    float& daily_low  = sc.GetPersistentFloat(DMP_PERSIST_DIV_DAILY_LOW);
    int&   last_day   = sc.GetPersistentInt(DMP_PERSIST_DIV_SESSION_DAY);

    // Reset explicite au debut d'un Full Recalc pour eviter toute pollution
    // d'etat persistant entre reloads DLL ou entre sessions.
    if (sc.IsFullRecalculation && sc.Index == 0) {
        daily_high = -1e30f;
        daily_low  = 1e30f;
        last_day   = 0;
    }

    // Calcul trading date CME (YYYYMMDD) en reutilisant la conversion ET
    // DST-aware deja presente dans DMP_ReadAll (lignes 2190-2243).
    time_t sec = (time_t)(d.timestamp_ms / 1000);
#ifdef _WIN32
    struct tm gm_val{};
    gmtime_s(&gm_val, &sec);
    struct tm* gm = &gm_val;
#else
    struct tm gm_buf{};
    struct tm* gm = gmtime_r(&sec, &gm_buf);
#endif
    int mo = gm->tm_mon + 1;
    int dy = gm->tm_mday;
    bool is_dst = false;
    if      (mo >= 4 && mo <= 10)    is_dst = true;
    else if (mo == 3 && dy >= 8)     is_dst = true;
    else if (mo == 11 && dy <= 7)    is_dst = true;
    int utc_offset = is_dst ? 4 : 5;
    int h_et = (gm->tm_hour - utc_offset + 24) % 24;

    // Trading date : si hour_ET >= 18, la session du LENDEMAIN a demarre
    time_t trading_sec = sec - (long)utc_offset * 3600L;  // local ET
    if (h_et >= 18) trading_sec += 86400L;                 // shift +1 day

#ifdef _WIN32
    struct tm tr_val{};
    gmtime_s(&tr_val, &trading_sec);
    struct tm* tr = &tr_val;
#else
    struct tm tr_buf{};
    struct tm* tr = gmtime_r(&trading_sec, &tr_buf);
#endif
    int trading_day = (tr->tm_year + 1900) * 10000
                    + (tr->tm_mon + 1) * 100
                    +  tr->tm_mday;

    // Reset session ?
    if (trading_day != last_day) {
        daily_high = -1e30f;
        daily_low  = 1e30f;
        last_day   = trading_day;
    }

    // Sauvegarder prev AVANT update
    const float prev_high = daily_high;
    const float prev_low  = daily_low;

    // Update running high/low avec fallback price_close si price_high/low invalides
    // (cas edge backfill pre-3.7.1 qui n'avait pas ces champs).
    // NOTE: struct DMP_RawData utilise price_high/price_low (cf ligne 343-344).
    // Transform.h ecrit ensuite bar_high/bar_low dans DMP_Features (JSONL output).
    const float bh = DMP_IsPriceValid(d.price_high) ? d.price_high : d.price_close;
    const float bl = DMP_IsPriceValid(d.price_low)  ? d.price_low  : d.price_close;
    if (DMP_IsPriceValid(bh) && bh > daily_high) daily_high = bh;
    if (DMP_IsPriceValid(bl) && bl < daily_low)  daily_low  = bl;

    // Formule SC exacte
    // fpbs_delta est le raw (AV-BV). Transform le copie dans f.delta_bar.
    const float db = DMP_IsValid(d.fpbs_delta) ? d.fpbs_delta : 0.0f;

    // Guard init_ok : skip la 1ere barre de session (prev encore a sentinel)
    const bool init_ok = (prev_high > -1e29f) && (prev_low < 1e29f);
    const bool buy_div  = init_ok && (daily_low  < prev_low)  && (db >= 0.0f);
    const bool sell_div = init_ok && (daily_high > prev_high) && (db <= 0.0f);

    d.delta_div_buy  = buy_div  ? 1.0f : 0.0f;
    d.delta_div_sell = sell_div ? 1.0f : 0.0f;
}

// ─────────────────────────────────────────────────────────────────────────────
// CVD & SWING HIGH/LOW
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadCVD(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart    = d.is_nq ? DMP_Charts::NQ_CVD : DMP_Charts::ES_CVD;
    const int cvd_id   = d.is_nq ? DMP_Studies::NQ_CVD::CVD   : DMP_Studies::ES_CVD::CVD;
    const int ohlc_id  = d.is_nq ? DMP_Studies::NQ_CVD::CVD_OHLC : DMP_Studies::ES_CVD::CVD_OHLC;
    const int swing_id = d.is_nq ? DMP_Studies::NQ_CVD::SWING : DMP_Studies::ES_CVD::SWING;
    const int vp_id    = d.is_nq ? DMP_Studies::NQ_CVD::VP_SESSION : DMP_Studies::ES_CVD::VP_SESSION;
    const int div_buy  = d.is_nq ? DMP_Studies::NQ_CVD::DELTA_DIV_BUY  : DMP_Studies::ES_CVD::DELTA_DIV_BUY;
    const int div_sell = d.is_nq ? DMP_Studies::NQ_CVD::DELTA_DIV_SELL : DMP_Studies::ES_CVD::DELTA_DIV_SELL;

    // CVD Close (valeur cumulée)
    d.cvd_close     = DMP_SafeRead(sc, chart, cvd_id, 3);   // sg3=Close CVD

    // CVD OHLC (contexte swing)
    // ⚠️ FIX 04/03/2026 BUG #4 : CVD OHLC = "OHLC CUMULATIVE DELTA (Daily OHLC)"
    //  C'est un résumé DAILY sur un chart intraday → ne peint que sur la dernière barre.
    //  DMP_SafeRead (arr[sc.Index]) retournait 0 sur les barres intermédiaires → range = 0.
    //  Fix : DMP_SafeReadLast (arr[size-1]) pour lire la valeur Daily courante.
    d.cvd_ohlc_open = DMP_SafeReadLast(sc, chart, ohlc_id, 0);
    d.cvd_ohlc_high = DMP_SafeReadLast(sc, chart, ohlc_id, 1);
    d.cvd_ohlc_low  = DMP_SafeReadLast(sc, chart, ohlc_id, 2);

    // Swing High/Low — reference lines, peint au pivot → SafeReadLast
    // Swing High/Low — peint SEULEMENT aux barres pivot (comme OVN).
    // Entre les pivots arr[i]=0. SafeReadLastValid scanne en arrière
    // pour trouver le dernier prix de pivot valide.
    d.swing_high = DMP_SafeReadLastValid(sc, chart, swing_id, 0);
    d.swing_low  = DMP_SafeReadLastValid(sc, chart, swing_id, 1);

    // VPOC session courante (chart CVD) — reference line → SafeReadLast
    d.vp_session_vpoc = DMP_SafeReadLast(sc, chart, vp_id, 1);

    // Divergences Delta — FIX v4 (17/04/2026)
    // v1: SumOfAlerts(sg2) → cumulatif, reste ON toute la session = BRUIT
    // v2: Trigger(sg0) → pulse 1 barre, considere "rate 99% des signaux"
    //     mais c'etait en fait le comportement attendu (evenement rare).
    // v3: Extension Lines → 100% a 1 permanent sur trending (jamais intersectees).
    // v4: Reconstruction Daily OHLC fidele a ID33 "LINKED TO DELTA DIVERGENCE"
    //     BUY : new daily_low + delta >= 0
    //     SELL: new daily_high + delta <= 0
    //     Fire rate empirique ~0.4% = evenement rare et fort au session extreme.
    //     Valide par match exact avec triangles Sierra Chart sur 20260416.
    (void)div_buy;   // studies ID ne sont plus lues (calcul C++ custom via PersistVars)
    (void)div_sell;
    DMP_ReadDeltaDivergenceClean(sc, d);  // ecrit d.delta_div_buy / d.delta_div_sell
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPOSITE PROFILES (contexte long terme)
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadComposite(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart  = d.is_nq ? DMP_Charts::NQ_COMPOSITE : DMP_Charts::ES_COMPOSITE;
    const int id_20d = d.is_nq ? DMP_Studies::NQ_COMPOSITE::COMP_20D : DMP_Studies::ES_COMPOSITE::COMP_20D;
    const int id_50d = d.is_nq ? DMP_Studies::NQ_COMPOSITE::COMP_50D : DMP_Studies::ES_COMPOSITE::COMP_50D;

    // Composites — profils fixes, "reference line" → SafeReadLast
    d.comp_20d_vpoc = DMP_SafeReadLast(sc, chart, id_20d, 1);
    d.comp_20d_vah  = DMP_SafeReadLast(sc, chart, id_20d, 2);
    d.comp_20d_val  = DMP_SafeReadLast(sc, chart, id_20d, 3);
    d.comp_20d_vwap = DMP_SafeReadLast(sc, chart, id_20d, 4);  // VWAP Composite 20J
    d.comp_50d_vpoc = DMP_SafeReadLast(sc, chart, id_50d, 1);
    d.comp_50d_vah  = DMP_SafeReadLast(sc, chart, id_50d, 2);
    d.comp_50d_val  = DMP_SafeReadLast(sc, chart, id_50d, 3);
    d.comp_50d_vwap = DMP_SafeReadLast(sc, chart, id_50d, 4);  // VWAP Composite 50J
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — FONCTION MAÎTRE : DMP_ReadAll()
// ═══════════════════════════════════════════════════════════════════════════════
// Remplit un DMP_RawData complet depuis la barre courante du chart hôte.
// Appeler une SEULE fois par barre (pattern Sierra Chart : if (sc.IsNewBar()) ).

inline void DMP_ReadAll(SCStudyInterfaceRef sc, DMP_RawData& d, bool is_nq) {

    // ── 0. Initialisation — TOUS les floats à DMP_INVALID ────────────────────
    // memset à 0 ne suffit pas : 0.0f est indistinguable d'une vraie valeur nulle.
    // Tous les floats prix/mesure → DMP_INVALID, booléens → 0 (BOOL_FALSE).
    // NON PAS memset : ça met les floats à 0.0f qui est une valeur valide.
    memset(&d, 0, sizeof(DMP_RawData));

    // Floats prix et mesures → DMP_INVALID (valeur sentinelle)
    d.atr_daily = d.ma_fast = d.ma_slow = DMP_INVALID;
    d.vwap_day = d.vwap_day_sd1u = d.vwap_day_sd1d = DMP_INVALID;
    d.vwap_day_sd2u = d.vwap_day_sd2d = DMP_INVALID;
    d.vwap_day_sd3u = d.vwap_day_sd3d = DMP_INVALID;
    d.vwap_slope_10 = d.vwap_slope_30 = DMP_INVALID;
    d.vwap_weekly = d.vwap_weekly_sd1u = d.vwap_weekly_sd1d = DMP_INVALID;
    d.vwap_monthly = d.vwap_monthly_sd1u = d.vwap_monthly_sd1d = DMP_INVALID;
    d.mq_call = d.mq_put = d.mq_hvl = DMP_INVALID;
    d.mq_1d_min = d.mq_1d_max = DMP_INVALID;
    d.mq_call_0dte = d.mq_put_0dte = d.mq_hvl_0dte = DMP_INVALID;
    d.vix_level = d.vix_call = d.vix_put = d.vix_hvl = DMP_INVALID;
    d.vix_call_0dte = d.vix_put_0dte = d.vix_hvl_0dte = DMP_INVALID;
    for (int i = 0; i < 10; i++) d.vix_gex[i] = DMP_INVALID;
    d.cur_vpoc = d.cur_vah = d.cur_val = d.cur_vwap_vp = DMP_INVALID;
    d.prev_vpoc = d.prev_vah = d.prev_val = d.prev_vwap = DMP_INVALID;
    d.prev_vwap_sd1u = d.prev_vwap_sd1d = DMP_INVALID;
    d.ib_high = d.ib_low = d.open_cash = DMP_INVALID;
    d.open_830 = d.sess_high = d.sess_low = DMP_INVALID;
    d.ovn_high = d.ovn_low = DMP_INVALID;
    d.cvd_close = d.cvd_ohlc_open = d.cvd_ohlc_high = d.cvd_ohlc_low = DMP_INVALID;
    d.swing_high = d.swing_low = d.vp_session_vpoc = DMP_INVALID;
    d.comp_20d_vpoc = d.comp_20d_vah = d.comp_20d_val = d.comp_20d_vwap = DMP_INVALID;
    d.comp_50d_vpoc = d.comp_50d_vah = d.comp_50d_val = d.comp_50d_vwap = DMP_INVALID;
    d.fpbs_delta = d.fpbs_delta_change = d.fpbs_poc_price = DMP_INVALID;
    d.fpbs_avg_size = d.fpbs_avg_bid_size = d.fpbs_avg_ask_size = DMP_INVALID;
    d.fpbs_bar_duration = d.fpbs_vol_per_sec = d.fpbs_hl_range = DMP_INVALID;
    d.fpbs_total_vol = d.fpbs_buy_vol = d.fpbs_sell_vol = DMP_INVALID;
    d.fpbs_delta_pct = d.fpbs_ticks = d.fpbs_finish_pct = DMP_INVALID;
    d.fpbs_high_pullback = d.fpbs_low_pullback = DMP_INVALID;
    d.fpbs_diag_pos_delta = d.fpbs_diag_neg_delta = DMP_INVALID;
    d.fpbs_low_bid_pct = d.fpbs_high_ask_pct = DMP_INVALID;
    d.rotation_value = d.rotation_zz_mid = d.rotation_zz_osc = DMP_INVALID;
    for (int i = 0; i < 10; i++) {
        d.mq_gex[i] = d.mq_blind[i] = DMP_INVALID;
    }
    // Big Orders + Cluster Volume arrays etendus a 20 slots (fix 13/04/2026)
    for (int i = 0; i < 20; i++) {
        d.bn_ask100[i] = d.bn_bid100[i] = DMP_INVALID;
        d.bn_ask_extra1[i] = d.bn_bid_extra1[i] = DMP_INVALID;
        d.bn_ask_extra2[i] = d.bn_bid_extra2[i] = DMP_INVALID;
        d.bn_ask_extra3[i] = d.bn_bid_extra3[i] = DMP_INVALID;
        d.cluster_prices[i] = DMP_INVALID;  // schema 3.7.3
    }
    // Booléens BN → 0 (BOOL_FALSE) — laissés à 0 par memset, correct.

    // ── 1. Identification ──────────────────────────────────────────────────
    d.is_nq      = is_nq;
    d.bar_index  = sc.Index;
    d.price_close = (float)sc.Close[sc.Index];
    d.price_open  = (float)sc.Open[sc.Index];
    d.price_high  = (float)sc.High[sc.Index];
    d.price_low   = (float)sc.Low[sc.Index];
    d.tick_size   = (float)sc.TickSize;

    // Contrat complet depuis sc.Symbol (ex: "ESH26-CME[M]" → "ESH26-CME")
    {
        const char* raw_sym = sc.Symbol.GetChars();
        int k = 0;
        for (; raw_sym[k] && raw_sym[k] != '[' && k < 30; ++k)
            d.contract[k] = raw_sym[k];
        d.contract[k] = '\0';
    }

    // Timestamp Unix ms — utiliser l'heure de la BARRE (données marché), pas l'heure PC
    // sc.BaseDateTimeIn[sc.Index] = datetime de la barre en cours
    // Timestamp Unix ms — OLE Date (days since 1899-12-30) → Unix seconds
    SCDateTime bar_time = sc.BaseDateTimeIn[sc.Index];
    d.timestamp_ms = (long long)((bar_time.GetAsDouble() - 25569.0) * 86400.0) * 1000LL;

    // ── Conversion UTC → ET (New York) ──────────────────────────────────────
    //  L'ancien dumper (MIA_Dumper_G3_Unifier.cpp ligne 2701-2703) faisait :
    //    gmtime_s(&gm, &sec);
    //    int ny_hour = (gm.tm_hour - 5 + 24) % 24;
    //
    //  On ne fait PAS confiance à GetTimeHMS() car son résultat dépend du
    //  timezone configuré dans SC (Global Settings → Time Zone).
    //  Le timestamp Unix est TOUJOURS UTC → conversion fiable.
    //
    //  NOTE: DST-aware — UTC-4 (EDT) du 2ème dimanche mars au 1er dimanche nov,
    //  UTC-5 (EST) le reste de l'année. Fix 11/03/2026.
    {
        time_t sec = (time_t)(d.timestamp_ms / 1000);
#ifdef _WIN32
        struct tm gm_val{};
        gmtime_s(&gm_val, &sec);
        struct tm* gm = &gm_val;
#else
        struct tm gm_buf{};
        struct tm* gm = gmtime_r(&sec, &gm_buf);
#endif
        int h_utc = gm->tm_hour;
        int m_utc = gm->tm_min;

        // ⚠️ FIX DST 11/03/2026 — UTC → ET (New York)
        //  L'ancien code hardcodait -5 (EST) toute l'année.
        //  Pendant DST (2ème dimanche mars → 1er dimanche nov), c'est -4 (EDT).
        //  Le décalage de 1h causait: ib_complete=0, open_type=0, session mal-labelée.
        //  Confirmé par audit des données du 11/03/2026.
        //
        //  Règle DST US: actif si :
        //    - Avr-Oct (mois 4-10) → toujours DST
        //    - Mars (mois 3) après le 7 → DST (2ème dimanche >= jour 8)
        //    - Nov (mois 11) avant le 8 → DST (1er dimanche <= jour 7)
        //  Approximation conservatrice (±1 jour autour du changement = acceptable).
        bool is_dst = false;
        {
            int mo = gm->tm_mon + 1;   // tm_mon = 0-11, on veut 1-12
            int dy = gm->tm_mday;
            if (mo >= 4 && mo <= 10)            is_dst = true;   // Avr-Oct = toujours DST
            else if (mo == 3 && dy >= 8)        is_dst = true;   // Mars après le 8
            else if (mo == 11 && dy <= 7)       is_dst = true;   // Nov avant le 8
        }
        int utc_offset = is_dst ? 4 : 5;
        int h_et = (h_utc - utc_offset + 24) % 24;
        int m_et = m_utc;
        int time_et = h_et * 60 + m_et;

        // RTH = 09:30–16:00 ET
        d.is_rth_session = (time_et >= 9 * 60 + 30) && (time_et < 16 * 60);
        // IB complété après 10:30 ET — SEULEMENT pendant RTH US (fix audit 09/04)
        // Avant: bug → ib_complete=1 en Asia/London apres 10:30 ET
        d.ib_complete    = d.is_rth_session && (time_et >= 10 * 60 + 30);

        // Session tag : Asia=0, London=1, US=2
        // Ancien dumper (ligne 2716-2723) :
        //   Asia:   18:00-03:00 NY
        //   London: 03:00-09:00 NY  (note: 09:00 pas 09:30)
        //   US:     09:00-18:00 NY
        if (h_et >= 18 || h_et < 3)
            d.session = 0;  // Asia
        else if (h_et >= 3 && h_et < 9)
            d.session = 1;  // London (03:00-09:00 comme l'ancien)
        else
            d.session = 2;  // US (09:00-18:00)
    }

    d.read_errors = 0;
    d.error_detail[0] = '\0';
    
    // 🆕 15/03/2026: Poor Highs/Lows — initialisés à 0, calculés dans DMP_Main.cpp
    d.excess_high_bars = 0;
    d.excess_low_bars  = 0;
    d.poor_high        = false;
    d.poor_low         = false;

    // ── 2. Lecture par sections ────────────────────────────────────────────
    DMP_ReadFPBS(sc, d);
    DMP_ReadRotation(sc, d);
    DMP_ReadBNSignals(sc, d);
    DMP_ReadBarSignals(sc, d);   // 🆕 BUG #8 — Signaux Chart Barres + Extension Lines
    DMP_ReadVWAPDay(sc, d);
    DMP_ReadDaily(sc, d);
    DMP_ReadMenthorQ(sc, d);
    DMP_ReadVIX(sc, d);
    DMP_ReadVolumeProfile(sc, d);
    DMP_ReadSession(sc, d);
    DMP_ReadOVN(sc, d);
    DMP_ReadCVD(sc, d);
    DMP_ReadComposite(sc, d);

    // ── 3. Validation ATR (critique — dénominateur de toutes les normes) ──
    if (!DMP_IsValid(d.atr_daily) || d.atr_daily < 1.0f) {
        // Fallback : ATR estimé comme 1% du prix
        d.atr_daily = d.price_close * 0.01f;
        d.read_errors++;
        snprintf(d.error_detail, sizeof(d.error_detail),
                 "WARN: ATR_DAILY invalide → fallback %.2f", d.atr_daily);
    }

    // ── 4. Validation prix courant ─────────────────────────────────────────
    if (!DMP_IsPriceValid(d.price_close)) {
        d.read_errors++;
        // Pas de fallback possible pour le prix courant
        snprintf(d.error_detail + strlen(d.error_detail),
                 sizeof(d.error_detail) - strlen(d.error_detail),
                 " | ERR: PRICE_CLOSE invalide %.2f", d.price_close);
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — DIAGNOSTIC (mode debug)
// ═══════════════════════════════════════════════════════════════════════════════

inline void DMP_LogStatus(SCStudyInterfaceRef sc, const DMP_RawData& d) {
    char msg[512];
    snprintf(msg, sizeof(msg),
        "[DMP_Reader] %s | Price=%.2f ATR=%.2f | "
        "VWAP_D=%s VWAP_W=%s VWAP_M=%s | "
        "PVPOC=%s PVAH=%s PVAL=%s | "
        "IB_H=%s IB_L=%s | OVN_H=%s OVN_L=%s | "
        "BN_UP=%.0f BN_DN=%.0f | DELTA=%.0f | Errors=%d",
        d.is_nq ? "NQ" : "ES",
        d.price_close,
        d.atr_daily,
        DMP_IsValid(d.vwap_day)     ? "OK" : "??",
        DMP_IsValid(d.vwap_weekly)  ? "OK" : "??",
        DMP_IsValid(d.vwap_monthly) ? "OK" : "??",
        DMP_IsValid(d.prev_vpoc)    ? "OK" : "??",
        DMP_IsValid(d.prev_vah)     ? "OK" : "??",
        DMP_IsValid(d.prev_val)     ? "OK" : "??",
        DMP_IsValid(d.ib_high)      ? "OK" : "??",
        DMP_IsValid(d.ib_low)       ? "OK" : "??",
        DMP_IsValid(d.ovn_high)     ? "OK" : "??",
        DMP_IsValid(d.ovn_low)      ? "OK" : "??",
        d.bn_color_up,
        d.bn_color_dn,
        DMP_IsValid(d.fpbs_delta) ? d.fpbs_delta : 0.0f,
        d.read_errors
    );
    sc.AddMessageToLog(msg, d.read_errors > 0 ? 1 : 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_Reader.h
// ═══════════════════════════════════════════════════════════════════════════════
