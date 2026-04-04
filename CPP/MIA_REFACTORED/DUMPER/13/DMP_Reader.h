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

} // namespace DMP_Charts

// ─────────────────────────────────────────────────────────────────────────────

namespace DMP_Studies {

    // ── Chart 1 ES_FOOTPRINT ──────────────────────────────────────────────────
    struct ES_FP {
        constexpr static int FPBS         = 31;   // Footprint Bar Study
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
        constexpr static int FPBS         = 33;   // Footprint Bar Study
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
        constexpr static int HH_CASH      = 12;   // Higher High CASH session (sg1=High)
        constexpr static int LL_CASH      = 13;   // Lower Low CASH session   (sg2=Low)
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
        constexpr static int HH_CASH      = 12;   // Higher High CASH    (sg1)
        constexpr static int LL_CASH      = 13;   // Lower Low CASH      (sg2)
        constexpr static int OPEN_830     = 14;   // Open 08h30 ET
        // 🆕 BUG #8 — Signaux BN Chart Barres (04/03/2026)
        constexpr static int COLOR_UP     = 26;   // [AV] COLOR UP — sg0=prix, sg1=extension
        constexpr static int COLOR_DN     = 27;   // [AV] COLOR DOWN — sg0=prix, sg1=extension
        constexpr static int LONG_UP_BAR  = 18;   // [AV] LONG UP BAR (rectangle vert Edge Zone)
        constexpr static int LONG_DN_BAR  = 17;   // [AV] LONG DOWN BAR (rectangle rouge Edge Zone)
        constexpr static int LONG_DN_UP   = 23;   // [AV] LONG DOWN UP BAR (reversal bull)
        constexpr static int LONG_UP_DN   = 24;   // [AV] LONG UP DOWN BAR (reversal bear)
        constexpr static int EDGE_BUY     = 32;   // EDGE ZONES IMBALANCE BUY rev8 0DIAG
        constexpr static int EDGE_SELL    = 33;   // EDGE ZONES IMBALANCE SELL rev8 0DIAG
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
    float cluster_prices[10];            // CLUSTER sg0..9 — 10 prix cluster (0=inactif)
                                         // BUG #11 : étendu de 2 à 10 + ajout NQ (05/03/2026)

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
    float bn_ask100[10];                 // ASK_100 sg0..9 — 10 niveaux Ask +100 lots
    float bn_bid100[10];                 // BID_100 sg0..9 — 10 niveaux Bid +100 lots
    // 🆕 BUG #9 — Tous les seuils Big Orders (04/03/2026)
    // NQ: +10, +30 (fire souvent) | ES: +150, +400, +1000 (seuils progressifs)
    float bn_ask_extra1[10];             // NQ: ASK+10  | ES: ASK+150
    float bn_bid_extra1[10];             // NQ: BID+10  | ES: BID+150
    float bn_ask_extra2[10];             // NQ: ASK+30  | ES: ASK+400
    float bn_bid_extra2[10];             // NQ: BID+30  | ES: BID+400
    float bn_ask_extra3[10];             // ES: ASK+1000 | NQ: unused (INVALID)
    float bn_bid_extra3[10];             // ES: BID+1000 | NQ: unused (INVALID)

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
    float delta_div_buy;                 // DELTA_DIV_BUY sg0 — Divergence delta bullish
    float delta_div_sell;                // DELTA_DIV_SELL sg0 — Divergence delta bearish
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
    const int chart = d.is_nq ? DMP_Charts::NQ_FP  : DMP_Charts::ES_FP;
    const int study = d.is_nq ? DMP_Studies::NQ_FP::FPBS : DMP_Studies::ES_FP::FPBS;

    d.fpbs_delta         = DMP_SafeRead(sc, chart, study,  0);
    d.fpbs_delta_change  = DMP_SafeRead(sc, chart, study,  2);
    d.fpbs_pos_delta     = DMP_SafeRead(sc, chart, study,  3);
    d.fpbs_neg_delta     = DMP_SafeRead(sc, chart, study,  4);
    d.fpbs_max_delta     = DMP_SafeRead(sc, chart, study,  7);
    d.fpbs_min_delta     = DMP_SafeRead(sc, chart, study,  8);
    d.fpbs_delta_day     = DMP_SafeRead(sc, chart, study,  9);
    d.fpbs_volume        = DMP_SafeRead(sc, chart, study, 12);
    d.fpbs_avg_size      = DMP_SafeRead(sc, chart, study, 14);
    d.fpbs_ask_pct       = DMP_SafeRead(sc, chart, study, 16);
    d.fpbs_bid_pct       = DMP_SafeRead(sc, chart, study, 17);
    d.fpbs_cvd_day       = DMP_SafeRead(sc, chart, study, 18);
    d.fpbs_poc_vol       = DMP_SafeRead(sc, chart, study, 19);
    d.fpbs_cvd_high      = DMP_SafeRead(sc, chart, study, 20);
    d.fpbs_cvd_low       = DMP_SafeRead(sc, chart, study, 21);
    d.fpbs_bar_duration  = DMP_SafeRead(sc, chart, study, 29);
    d.fpbs_finish        = DMP_SafeRead(sc, chart, study, 33);
    d.fpbs_vol_per_sec   = DMP_SafeRead(sc, chart, study, 35);
    d.fpbs_hl_range      = DMP_SafeRead(sc, chart, study, 40);
    d.fpbs_poc_price     = DMP_SafeRead(sc, chart, study, 41);
    d.fpbs_avg_bid_size  = DMP_SafeRead(sc, chart, study, 50);
    d.fpbs_avg_ask_size  = DMP_SafeRead(sc, chart, study, 51);

    // 12 subgraphs ajoutés — 02/03/2026
    d.fpbs_total_vol     = DMP_SafeRead(sc, chart, study,  1); // Ask+Bid total
    d.fpbs_buy_vol       = DMP_SafeRead(sc, chart, study,  5); // BUY VOL
    d.fpbs_sell_vol      = DMP_SafeRead(sc, chart, study,  6); // SELL VOL
    d.fpbs_delta_pct     = DMP_SafeRead(sc, chart, study, 10); // Delta %
    d.fpbs_ticks         = DMP_SafeRead(sc, chart, study, 11); // Ticks count
    d.fpbs_finish_pct    = DMP_SafeRead(sc, chart, study, 34); // Finish delta %
    d.fpbs_high_pullback = DMP_SafeRead(sc, chart, study, 36); // High pullback
    d.fpbs_low_pullback  = DMP_SafeRead(sc, chart, study, 37); // Low pullback
    d.fpbs_diag_pos_delta= DMP_SafeRead(sc, chart, study, 42); // Diag+ delta
    d.fpbs_diag_neg_delta= DMP_SafeRead(sc, chart, study, 43); // Diag- delta
    d.fpbs_low_bid_pct   = DMP_SafeRead(sc, chart, study, 44); // Low bid vol %
    d.fpbs_high_ask_pct  = DMP_SafeRead(sc, chart, study, 45); // High ask vol %
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
    d.rotation_up_signal = DMP_ReadBN_SumOfAlerts(sc, chart, rup_id);
    d.rotation_dn_signal = DMP_ReadBN_SumOfAlerts(sc, chart, rdn_id);

    // Cluster Volume — BUG #11 : ajout NQ (ID:12) + étendu à 10 niveaux (05/03/2026)
    // Même pattern que Big Orders : sg0-59 = prix triggers, arr[size-1] = état courant
    {
        const int cluster_id = d.is_nq ? DMP_Studies::NQ_FP::CLUSTER : DMP_Studies::ES_FP::CLUSTER;
        const float min_price = d.is_nq ? 15000.0f : 5000.0f;
        int count = 0;
        for (int sg = 0; sg <= 59 && count < 10; sg++) {
            SCFloatArray arr;
            sc.GetStudyArrayFromChartUsingID(chart, cluster_id, sg, arr);
            int sz = (int)arr.GetArraySize();
            if (sz > 0) {
                float v = arr[sz - 1];
                if (std::isfinite(v) && v > min_price)
                    d.cluster_prices[count++] = v;
            }
        }
        for (int i = count; i < 10; i++) d.cluster_prices[i] = DMP_INVALID;
    }
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
    d.bn_color_up   = DMP_ReadExtensionLineCount(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_UP   : DMP_Studies::ES_FP::COLOR_UP);
    d.bn_color_dn   = DMP_ReadExtensionLineCount(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_DN   : DMP_Studies::ES_FP::COLOR_DN);
    // 🆕 10/03/2026 : COLOR_UP_2 = double stacké (continuation), séparé de COLOR simple
    d.bn_color_up_2 = DMP_ReadExtensionLineCount(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_UP_2 : DMP_Studies::ES_FP::COLOR_UP_2);
    d.bn_color_dn_2 = DMP_ReadExtensionLineCount(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_DN_2 : DMP_Studies::ES_FP::COLOR_DN_2);
    d.bn_absorb_ask = DMP_ReadExtensionLineCount(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::ABSORB_ASK : DMP_Studies::ES_FP::ABSORB_ASK);
    d.bn_absorb_bid = DMP_ReadExtensionLineCount(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::ABSORB_BID : DMP_Studies::ES_FP::ABSORB_BID);
    d.bn_long_up    = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::LONG_UP    : DMP_Studies::ES_FP::LONG_UP);
    d.bn_long_dn    = DMP_ReadBN_Trigger(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::LONG_DN    : DMP_Studies::ES_FP::LONG_DN);

    // ES = Double Ask/Bid — NQ = Triple Ask/Bid → Extension Lines
    if (!d.is_nq) {
        d.bn_double_ask  = DMP_ReadExtensionLineCount(sc, chart, DMP_Studies::ES_FP::DOUBLE_ASK);
        d.bn_double_bid  = DMP_ReadExtensionLineCount(sc, chart, DMP_Studies::ES_FP::DOUBLE_BID);
        d.bn_triple_ask  = DMP_BOOL_FALSE;
        d.bn_triple_bid  = DMP_BOOL_FALSE;
    } else {
        d.bn_double_ask  = DMP_BOOL_FALSE;
        d.bn_double_bid  = DMP_BOOL_FALSE;
        d.bn_triple_ask  = DMP_ReadExtensionLineCount(sc, chart, DMP_Studies::NQ_FP::TRIPLE_ASK);
        d.bn_triple_bid  = DMP_ReadExtensionLineCount(sc, chart, DMP_Studies::NQ_FP::TRIPLE_BID);
    }

    // 🆕 BUG #10 — Volume UP/DOWN + Edge Zones Footprint (05/03/2026)
    // 🆕 FIX 12/03/2026 — ES VOLUME UP/DOWN ajoutés (ID:2, ID:4)
    if (!d.is_nq) {
        d.bn_volume_up   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::ES_FP::VOLUME_UP);
        d.bn_volume_dn   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::ES_FP::VOLUME_DN);
        d.fp_edge_buy    = DMP_ReadBN_SumOfAlerts(sc, chart, DMP_Studies::ES_FP::EDGE_BUY);
        d.fp_edge_sell   = DMP_ReadBN_SumOfAlerts(sc, chart, DMP_Studies::ES_FP::EDGE_SELL);
        d.fp_edge_buy_2  = DMP_ReadBN_SumOfAlerts(sc, chart, DMP_Studies::ES_FP::EDGE_BUY_R1);
        d.fp_edge_sell_2 = DMP_ReadBN_SumOfAlerts(sc, chart, DMP_Studies::ES_FP::EDGE_SELL_R1);
    } else {
        // 🆕 FIX : Trigger(sg0) au lieu de SumOfAlerts(sg2)
        // Volume spike = événement ponctuel, pas zone permanente
        d.bn_volume_up   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::NQ_FP::VOLUME_UP);
        d.bn_volume_dn   = DMP_ReadBN_Trigger(sc, chart, DMP_Studies::NQ_FP::VOLUME_DN);
        d.fp_edge_buy    = DMP_ReadBN_SumOfAlerts(sc, chart, DMP_Studies::NQ_FP::EDGE_BUY);
        d.fp_edge_sell   = DMP_ReadBN_SumOfAlerts(sc, chart, DMP_Studies::NQ_FP::EDGE_SELL);
        d.fp_edge_buy_2  = DMP_ReadBN_SumOfAlerts(sc, chart, DMP_Studies::NQ_FP::EDGE_BUY_2);
        d.fp_edge_sell_2 = DMP_ReadBN_SumOfAlerts(sc, chart, DMP_Studies::NQ_FP::EDGE_SELL_2);
    }

    // Big Orders — TOUS LES SEUILS (BUG #9 : +10/+30/+100 NQ, +100/+150/+400/+1000 ES)
    // ⚠️ FIX 04/03/2026 BUG #1 : sg0-46, arr[size-1] (même méthode que ancien BN_ReadTriggerPrices)
    // ⚠️ FIX 05/03/2026 BUG #9 : ajout TOUS les seuils — seul +100 était lu, +10/+30 ignorés
    {
        const float min_price = d.is_nq ? 15000.0f : 5000.0f;

        // Seuil principal : +100 (les deux symboles)
        DMP_ReadBigOrderThreshold(sc, chart,
            d.is_nq ? DMP_Studies::NQ_FP::ASK_100 : DMP_Studies::ES_FP::ASK_100,
            d.is_nq ? DMP_Studies::NQ_FP::BID_100 : DMP_Studies::ES_FP::BID_100,
            min_price, d.bn_ask100, d.bn_bid100);

        // Seuils supplémentaires — NQ: +10, +30 | ES: +150, +400, +1000
        if (d.is_nq) {
            DMP_ReadBigOrderThreshold(sc, chart,
                DMP_Studies::NQ_FP::ASK_10, DMP_Studies::NQ_FP::BID_10,
                min_price, d.bn_ask_extra1, d.bn_bid_extra1);
            DMP_ReadBigOrderThreshold(sc, chart,
                DMP_Studies::NQ_FP::ASK_30, DMP_Studies::NQ_FP::BID_30,
                min_price, d.bn_ask_extra2, d.bn_bid_extra2);
            for (int i = 0; i < 10; i++) { d.bn_ask_extra3[i] = DMP_INVALID; d.bn_bid_extra3[i] = DMP_INVALID; }
        } else {
            DMP_ReadBigOrderThreshold(sc, chart,
                DMP_Studies::ES_FP::ASK_150, DMP_Studies::ES_FP::BID_150,
                min_price, d.bn_ask_extra1, d.bn_bid_extra1);
            DMP_ReadBigOrderThreshold(sc, chart,
                DMP_Studies::ES_FP::ASK_400, DMP_Studies::ES_FP::BID_400,
                min_price, d.bn_ask_extra2, d.bn_bid_extra2);
            DMP_ReadBigOrderThreshold(sc, chart,
                DMP_Studies::ES_FP::ASK_1000, DMP_Studies::ES_FP::BID_1000,
                min_price, d.bn_ask_extra3, d.bn_bid_extra3);
        }
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
    // COLOR = Extension Lines (même fix que FP)
    // LONG/EDGE = per-bar → sg0 correct
    // PRESSURE (DOUBLE/TRIPLE) = Extension Lines
    d.bar_color_up    = DMP_ReadExtensionLineCount(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_BARRES::COLOR_UP    : DMP_Studies::ES_BARRES::COLOR_UP);
    d.bar_color_dn    = DMP_ReadExtensionLineCount(sc, chart,
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

    // ES = Double Ask/Bid, NQ = Triple Ask/Bid → Extension Lines
    if (!d.is_nq) {
        d.bar_pressure_ask = DMP_ReadExtensionLineCount(sc, chart, DMP_Studies::ES_BARRES::DOUBLE_ASK);
        d.bar_pressure_bid = DMP_ReadExtensionLineCount(sc, chart, DMP_Studies::ES_BARRES::DOUBLE_BID);
    } else {
        d.bar_pressure_ask = DMP_ReadExtensionLineCount(sc, chart, DMP_Studies::NQ_BARRES::TRIPLE_ASK);
        d.bar_pressure_bid = DMP_ReadExtensionLineCount(sc, chart, DMP_Studies::NQ_BARRES::TRIPLE_BID);
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

    // IB = HIGHER HIGH / LOWER LOW CASH SESSION (9h30-10h30) — reference lines
    const int hh_cash = d.is_nq ? DMP_Studies::NQ_BARRES::HH_CASH : DMP_Studies::ES_BARRES::HH_CASH;
    const int ll_cash = d.is_nq ? DMP_Studies::NQ_BARRES::LL_CASH : DMP_Studies::ES_BARRES::LL_CASH;
    d.ib_high = DMP_SafeReadLast(sc, chart_b, hh_cash, 1);   // sg1 = High
    d.ib_low  = DMP_SafeReadLast(sc, chart_b, ll_cash, 2);   // sg2 = Low

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

    // Divergences Delta — BUG #12 FIX v2 (05/03/2026)
    // v1: SumOfAlerts(sg2) → cumulatif, reste ON toute la session = BRUIT
    // v2: Trigger(sg0) arr[size-1] → pulse ~30min (durée barre source)
    //     Retourne prix quand fire sur la barre courante du chart source,
    //     0 quand la barre source suivante n'a pas de fire.
    //     Fonctionne en cross-timeframe (NQ #29 = 30min, ES #28 = 1min)
    d.delta_div_buy  = DMP_ReadBN_Trigger(sc, chart, div_buy);
    d.delta_div_sell = DMP_ReadBN_Trigger(sc, chart, div_sell);
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
    d.vwap_slope_10 = d.vwap_slope_30 = DMP_INVALID;
    d.vwap_weekly = d.vwap_weekly_sd1u = d.vwap_weekly_sd1d = DMP_INVALID;
    d.vwap_monthly = d.vwap_monthly_sd1u = d.vwap_monthly_sd1d = DMP_INVALID;
    d.mq_call = d.mq_put = d.mq_hvl = DMP_INVALID;
    d.mq_1d_min = d.mq_1d_max = DMP_INVALID;
    d.mq_call_0dte = d.mq_put_0dte = d.mq_hvl_0dte = DMP_INVALID;
    d.vix_level = d.vix_call = d.vix_put = d.vix_hvl = DMP_INVALID;
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
    for (int i = 0; i < 10; i++) d.cluster_prices[i] = DMP_INVALID;
    for (int i = 0; i < 10; i++) {
        d.mq_gex[i] = d.mq_blind[i] = DMP_INVALID;
        d.bn_ask100[i] = d.bn_bid100[i] = DMP_INVALID;
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
        // IB complété après 10:30 ET
        d.ib_complete    = (time_et >= 10 * 60 + 30);

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
