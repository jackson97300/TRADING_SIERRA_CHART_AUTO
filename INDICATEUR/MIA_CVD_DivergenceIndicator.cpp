// ═══════════════════════════════════════════════════════════════════════════════
// MIA_CVD_DivergenceIndicator.cpp
// ═══════════════════════════════════════════════════════════════════════════════
// Study visuel Sierra Chart ACSIL — Détection et affichage des divergences CVD
// Date: 13/02/2026
// Version: 1.0
//
// SE POSE SUR: Charts avec Cumulative Delta (ex: #28 ES, #29 NQ)
//
// LIT:
//   - Prix OHLC       → Base Data du chart
//   - CVD OHLC        → Study "CUMULATIVE DELTA" (ID configurable, défaut=1)
//   - Swing High/Low  → Study "SWING HIGH/LOW" (ID configurable, défaut=6)
//
// DESSINE:
//   - Flèches sur les barres de divergence (4 types × 2 directions)
//   - Lignes de tendance entre les swing points divergents
//   - Score CVD en sous-graphe optionnel
//
// ALERTE:
//   - Son configurable sur Classic Divergence (les plus fiables)
//
// COMPILATION:
//   Fichier standalone — compiler comme DLL séparée.
//   Ajouter au chart via "Add Custom Study" → "MIA CVD Divergence"
// ═══════════════════════════════════════════════════════════════════════════════

#include "sierrachart.h"

SCDLLName("MIA_CVD_DivergenceIndicator")

// ═══════════════════════════════════════════════════════════════════════════════
// CONSTANTES
// ═══════════════════════════════════════════════════════════════════════════════

const int CVD_LOOKBACK = 8;
const int CVD_MIN_BARS = 4;
const float CVD_DIV_MIN_RATIO = 0.15f;
const float CVD_ABSORB_CVD_MIN_MOVE = 300.0f;
const float CVD_FLIP_THRESHOLD = 50.0f;

// Couleurs par défaut (modifiables dans les Subgraph Settings)
// Classic Bearish   = Rouge vif
// Classic Bullish   = Vert vif
// Hidden Bullish    = Cyan
// Hidden Bearish    = Orange
// Absorption Buy    = Magenta
// Absorption Sell   = Jaune
// CVD Flip Bull     = Blanc
// CVD Flip Bear     = Gris clair

// ═══════════════════════════════════════════════════════════════════════════════
// ENUM pour les subgraphs
// ═══════════════════════════════════════════════════════════════════════════════

enum SubgraphIndex {
    SG_CLASSIC_BEARISH = 0,   // ▼ Flèche rouge au-dessus du high
    SG_CLASSIC_BULLISH = 1,   // ▲ Flèche verte en-dessous du low
    SG_HIDDEN_BULLISH  = 2,   // ● Point cyan en-dessous
    SG_HIDDEN_BEARISH  = 3,   // ● Point orange au-dessus
    SG_ABSORPTION_BUY  = 4,   // ◆ Losange magenta en-dessous
    SG_ABSORPTION_SELL = 5,   // ◆ Losange jaune au-dessus
    SG_FLIP_BULLISH    = 6,   // ★ Étoile blanche en-dessous
    SG_FLIP_BEARISH    = 7,   // ★ Étoile grise au-dessus
    SG_CVD_SCORE       = 8,   // Ligne score CVD [-1, +1] (sous-graphe séparé)
    SG_COUNT           = 9
};

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTIONS UTILITAIRES
// ═══════════════════════════════════════════════════════════════════════════════

// Trouver le High/Low/Max CVD/Min CVD dans une fenêtre de barres
struct WindowStats {
    float price_high;
    float price_low;
    float cvd_max;
    float cvd_min;
    int   price_high_idx;
    int   price_low_idx;
    int   cvd_max_idx;
    int   cvd_min_idx;
};

inline WindowStats CalculateWindowStats(
    SCBaseDataRef BaseData,
    SCFloatArrayRef cvd_close,
    int start_idx,
    int end_idx)
{
    WindowStats w;
    w.price_high = BaseData[SC_HIGH][start_idx];
    w.price_low  = BaseData[SC_LOW][start_idx];
    w.cvd_max    = cvd_close[start_idx];
    w.cvd_min    = cvd_close[start_idx];
    w.price_high_idx = start_idx;
    w.price_low_idx  = start_idx;
    w.cvd_max_idx    = start_idx;
    w.cvd_min_idx    = start_idx;
    
    for (int i = start_idx + 1; i <= end_idx; i++) {
        if (BaseData[SC_HIGH][i] > w.price_high) {
            w.price_high = BaseData[SC_HIGH][i];
            w.price_high_idx = i;
        }
        if (BaseData[SC_LOW][i] < w.price_low) {
            w.price_low = BaseData[SC_LOW][i];
            w.price_low_idx = i;
        }
        if (cvd_close[i] > w.cvd_max) {
            w.cvd_max = cvd_close[i];
            w.cvd_max_idx = i;
        }
        if (cvd_close[i] < w.cvd_min) {
            w.cvd_min = cvd_close[i];
            w.cvd_min_idx = i;
        }
    }
    return w;
}

// ═══════════════════════════════════════════════════════════════════════════════
// GESTION DES LIGNES DE DIVERGENCE (Tool Drawings)
// ═══════════════════════════════════════════════════════════════════════════════

// Dessiner une ligne entre deux points sur le graphe prix
inline void DrawDivergenceLine_Price(
    SCStudyInterfaceRef sc,
    int bar_a, float price_a,
    int bar_b, float price_b,
    COLORREF color,
    int line_id_base,
    int width = 2)
{
    s_UseTool tool;
    memset(&tool, 0, sizeof(tool));
    
    tool.ChartNumber = sc.ChartNumber;
    tool.DrawingType = DRAWING_LINE;
    tool.LineNumber = line_id_base;
    tool.AddMethod = UTAM_ADD_OR_ADJUST;
    
    tool.BeginIndex = bar_a;
    tool.BeginValue = price_a;
    tool.EndIndex = bar_b;
    tool.EndValue = price_b;
    
    tool.Color = color;
    tool.LineWidth = (unsigned short)width;
    tool.LineStyle = LINESTYLE_SOLID;
    tool.AddAsUserDrawnDrawing = 0;  // Géré par le study, pas par l'user
    
    sc.UseTool(tool);
}

// Supprimer toutes les lignes dessinées par notre study
inline void ClearAllDivergenceLines(SCStudyInterfaceRef sc, int base_id, int count) {
    for (int i = 0; i < count; i++) {
        s_UseTool tool;
        memset(&tool, 0, sizeof(tool));
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_LINE;
        tool.LineNumber = base_id + i;
        tool.AddMethod = UTAM_ADD_OR_ADJUST;
        // Mettre la ligne hors écran pour la "supprimer"
        tool.BeginIndex = 0;
        tool.BeginValue = 0;
        tool.EndIndex = 0;
        tool.EndValue = 0;
        tool.Color = RGB(0, 0, 0);
        tool.LineWidth = 0;
        tool.AddAsUserDrawnDrawing = 0;
        sc.UseTool(tool);
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// STUDY PRINCIPAL
// ═══════════════════════════════════════════════════════════════════════════════

SCSFExport scsf_MIA_CVD_Divergence(SCStudyInterfaceRef sc)
{
    // ─────────────────────────────────────────────────────────────────────────
    // SUBGRAPHS
    // ─────────────────────────────────────────────────────────────────────────
    SCSubgraphRef sg_ClassicBearish = sc.Subgraph[SG_CLASSIC_BEARISH];
    SCSubgraphRef sg_ClassicBullish = sc.Subgraph[SG_CLASSIC_BULLISH];
    SCSubgraphRef sg_HiddenBullish  = sc.Subgraph[SG_HIDDEN_BULLISH];
    SCSubgraphRef sg_HiddenBearish  = sc.Subgraph[SG_HIDDEN_BEARISH];
    SCSubgraphRef sg_AbsorptionBuy  = sc.Subgraph[SG_ABSORPTION_BUY];
    SCSubgraphRef sg_AbsorptionSell = sc.Subgraph[SG_ABSORPTION_SELL];
    SCSubgraphRef sg_FlipBullish    = sc.Subgraph[SG_FLIP_BULLISH];
    SCSubgraphRef sg_FlipBearish    = sc.Subgraph[SG_FLIP_BEARISH];
    SCSubgraphRef sg_CVDScore       = sc.Subgraph[SG_CVD_SCORE];
    
    // ─────────────────────────────────────────────────────────────────────────
    // INPUTS
    // ─────────────────────────────────────────────────────────────────────────
    SCInputRef Input_CVD_StudyID    = sc.Input[0];
    SCInputRef Input_CVD_Subgraph   = sc.Input[1];
    SCInputRef Input_Lookback       = sc.Input[2];
    SCInputRef Input_MinRatio       = sc.Input[3];
    SCInputRef Input_DrawLines      = sc.Input[4];
    SCInputRef Input_AlertClassic   = sc.Input[5];
    SCInputRef Input_AbsorbPriceTicks = sc.Input[6];
    SCInputRef Input_AbsorbCVDMin   = sc.Input[7];
    SCInputRef Input_ShowHidden     = sc.Input[8];
    SCInputRef Input_ShowAbsorption = sc.Input[9];
    SCInputRef Input_ShowFlip       = sc.Input[10];
    SCInputRef Input_LineWidth      = sc.Input[11];
    SCInputRef Input_MarkerOffset   = sc.Input[12];
    
    // ─────────────────────────────────────────────────────────────────────────
    // DEFAULTS
    // ─────────────────────────────────────────────────────────────────────────
    if (sc.SetDefaults)
    {
        sc.GraphName = "MIA CVD Divergence";
        sc.StudyDescription = "Detecte et affiche les divergences CVD avancees "
                              "(classique, cachee, absorption, flip) avec lignes de connexion.";
        sc.AutoLoop = 1;
        sc.GraphRegion = 0;  // Overlay sur le prix
        sc.UpdateAlways = 0; // Calcule uniquement quand les données changent
        
        // --- Subgraphs ---
        
        // Classic Bearish ▼
        sg_ClassicBearish.Name = "Classic Bearish (VETO Long)";
        sg_ClassicBearish.DrawStyle = DRAWSTYLE_ARROWDOWN;
        sg_ClassicBearish.PrimaryColor = RGB(255, 50, 50);     // Rouge vif
        sg_ClassicBearish.LineWidth = 3;
        sg_ClassicBearish.DrawZeros = false;
        
        // Classic Bullish ▲
        sg_ClassicBullish.Name = "Classic Bullish (VETO Short)";
        sg_ClassicBullish.DrawStyle = DRAWSTYLE_ARROWUP;
        sg_ClassicBullish.PrimaryColor = RGB(50, 255, 50);     // Vert vif
        sg_ClassicBullish.LineWidth = 3;
        sg_ClassicBullish.DrawZeros = false;
        
        // Hidden Bullish ●
        sg_HiddenBullish.Name = "Hidden Bullish (Continuation)";
        sg_HiddenBullish.DrawStyle = DRAWSTYLE_POINT_ON_LOW;
        sg_HiddenBullish.PrimaryColor = RGB(0, 220, 255);      // Cyan
        sg_HiddenBullish.LineWidth = 4;
        sg_HiddenBullish.DrawZeros = false;
        
        // Hidden Bearish ●
        sg_HiddenBearish.Name = "Hidden Bearish (Continuation)";
        sg_HiddenBearish.DrawStyle = DRAWSTYLE_POINT_ON_HIGH;
        sg_HiddenBearish.PrimaryColor = RGB(255, 165, 0);      // Orange
        sg_HiddenBearish.LineWidth = 4;
        sg_HiddenBearish.DrawZeros = false;
        
        // Absorption Buy ◆
        sg_AbsorptionBuy.Name = "Absorption Buy (Pre-Breakout)";
        sg_AbsorptionBuy.DrawStyle = DRAWSTYLE_DIAMOND;
        sg_AbsorptionBuy.PrimaryColor = RGB(200, 50, 255);     // Magenta
        sg_AbsorptionBuy.LineWidth = 4;
        sg_AbsorptionBuy.DrawZeros = false;
        
        // Absorption Sell ◆
        sg_AbsorptionSell.Name = "Absorption Sell (Pre-Breakout)";
        sg_AbsorptionSell.DrawStyle = DRAWSTYLE_DIAMOND;
        sg_AbsorptionSell.PrimaryColor = RGB(255, 255, 0);     // Jaune
        sg_AbsorptionSell.LineWidth = 4;
        sg_AbsorptionSell.DrawZeros = false;
        
        // CVD Flip Bullish ★
        sg_FlipBullish.Name = "CVD Flip Bullish";
        sg_FlipBullish.DrawStyle = DRAWSTYLE_STAR;
        sg_FlipBullish.PrimaryColor = RGB(255, 255, 255);      // Blanc
        sg_FlipBullish.LineWidth = 3;
        sg_FlipBullish.DrawZeros = false;
        
        // CVD Flip Bearish ★
        sg_FlipBearish.Name = "CVD Flip Bearish";
        sg_FlipBearish.DrawStyle = DRAWSTYLE_STAR;
        sg_FlipBearish.PrimaryColor = RGB(180, 180, 180);      // Gris clair
        sg_FlipBearish.LineWidth = 3;
        sg_FlipBearish.DrawZeros = false;
        
        // Score CVD (sous-graphe séparé)
        sg_CVDScore.Name = "CVD Divergence Score";
        sg_CVDScore.DrawStyle = DRAWSTYLE_LINE;
        sg_CVDScore.PrimaryColor = RGB(100, 200, 255);
        sg_CVDScore.LineWidth = 2;
        sg_CVDScore.DrawZeros = true;
        // GraphRegion non disponible sur Subgraph dans cette version SC; le score s'affiche en overlay ou via région étude.
        
        // --- Inputs ---
        Input_CVD_StudyID.Name = "CVD Study ID (Cumulative Delta)";
        Input_CVD_StudyID.SetInt(1);
        Input_CVD_StudyID.SetIntLimits(1, 200);
        
        Input_CVD_Subgraph.Name = "CVD Subgraph (0=Open,1=High,2=Low,3=Close)";
        Input_CVD_Subgraph.SetInt(3);  // Close = valeur CVD à la clôture
        Input_CVD_Subgraph.SetIntLimits(0, 7);
        
        Input_Lookback.Name = "Lookback (barres)";
        Input_Lookback.SetInt(CVD_LOOKBACK);
        Input_Lookback.SetIntLimits(4, 20);
        
        Input_MinRatio.Name = "Min Divergence Ratio (%)";
        Input_MinRatio.SetFloat(CVD_DIV_MIN_RATIO * 100.0f);
        Input_MinRatio.SetFloatLimits(5.0f, 50.0f);
        
        Input_DrawLines.Name = "Dessiner lignes de divergence";
        Input_DrawLines.SetYesNo(1);
        
        Input_AlertClassic.Name = "Alerte sonore (Classic Divergence)";
        Input_AlertClassic.SetYesNo(1);
        
        Input_AbsorbPriceTicks.Name = "Absorption: Max price range (ticks)";
        Input_AbsorbPriceTicks.SetFloat(4.0f);
        Input_AbsorbPriceTicks.SetFloatLimits(2.0f, 10.0f);
        
        Input_AbsorbCVDMin.Name = "Absorption: Min CVD move";
        Input_AbsorbCVDMin.SetFloat(CVD_ABSORB_CVD_MIN_MOVE);
        Input_AbsorbCVDMin.SetFloatLimits(100.0f, 1000.0f);
        
        Input_ShowHidden.Name = "Afficher Hidden Divergences";
        Input_ShowHidden.SetYesNo(1);
        
        Input_ShowAbsorption.Name = "Afficher Absorption";
        Input_ShowAbsorption.SetYesNo(1);
        
        Input_ShowFlip.Name = "Afficher CVD Flip";
        Input_ShowFlip.SetYesNo(1);
        
        Input_LineWidth.Name = "Epaisseur lignes divergence";
        Input_LineWidth.SetInt(2);
        Input_LineWidth.SetIntLimits(1, 5);
        
        Input_MarkerOffset.Name = "Offset marqueurs (ticks)";
        Input_MarkerOffset.SetFloat(3.0f);
        Input_MarkerOffset.SetFloatLimits(1.0f, 20.0f);
        
        return;
    }
    
    // ─────────────────────────────────────────────────────────────────────────
    // LECTURE DES PARAMÈTRES
    // ─────────────────────────────────────────────────────────────────────────
    
    int cvd_study_id    = Input_CVD_StudyID.GetInt();
    int cvd_subgraph    = Input_CVD_Subgraph.GetInt();
    int lookback        = Input_Lookback.GetInt();
    float min_ratio     = Input_MinRatio.GetFloat() / 100.0f;
    bool draw_lines     = Input_DrawLines.GetYesNo() != 0;
    bool alert_classic  = Input_AlertClassic.GetYesNo() != 0;
    float absorb_ticks  = Input_AbsorbPriceTicks.GetFloat();
    float absorb_cvd    = Input_AbsorbCVDMin.GetFloat();
    bool show_hidden    = Input_ShowHidden.GetYesNo() != 0;
    bool show_absorb    = Input_ShowAbsorption.GetYesNo() != 0;
    bool show_flip      = Input_ShowFlip.GetYesNo() != 0;
    int line_width      = Input_LineWidth.GetInt();
    float marker_offset = Input_MarkerOffset.GetFloat() * sc.TickSize;
    
    // ─────────────────────────────────────────────────────────────────────────
    // LIRE LE CVD DEPUIS LE STUDY EXISTANT
    // ─────────────────────────────────────────────────────────────────────────
    
    SCFloatArray cvd_close;
    sc.GetStudyArrayUsingID(cvd_study_id, cvd_subgraph, cvd_close);
    
    if (cvd_close.GetArraySize() == 0) {
        // CVD study pas encore chargé
        return;
    }
    
    // Aussi lire CVD High et Low pour l'absorption
    SCFloatArray cvd_high, cvd_low;
    sc.GetStudyArrayUsingID(cvd_study_id, 1, cvd_high);  // Subgraph 1 = High
    sc.GetStudyArrayUsingID(cvd_study_id, 2, cvd_low);   // Subgraph 2 = Low
    
    // ─────────────────────────────────────────────────────────────────────────
    // CALCUL POUR LA BARRE COURANTE (AutoLoop)
    // ─────────────────────────────────────────────────────────────────────────
    
    int idx = sc.Index;  // Barre courante (AutoLoop)
    
    // Pas assez de barres en arrière (on a besoin de lookback barres: [idx-lookback+1 .. idx])
    if (idx < lookback - 1) return;
    
    // Initialiser tous les subgraphs à 0 pour cette barre
    sg_ClassicBearish[idx] = 0;
    sg_ClassicBullish[idx] = 0;
    sg_HiddenBullish[idx] = 0;
    sg_HiddenBearish[idx] = 0;
    sg_AbsorptionBuy[idx] = 0;
    sg_AbsorptionSell[idx] = 0;
    sg_FlipBullish[idx] = 0;
    sg_FlipBearish[idx] = 0;
    sg_CVDScore[idx] = 0;
    
    // ─────────────────────────────────────────────────────────────────────────
    // ANALYSE FENÊTRE A vs B (comme le module bot)
    // ─────────────────────────────────────────────────────────────────────────
    
    int start = idx - lookback + 1;  // Première barre du lookback
    int mid = start + lookback / 2;  // Milieu
    int end = idx;                    // Barre courante
    
    // Calculer les stats de chaque fenêtre
    WindowStats wA = CalculateWindowStats(sc.BaseData, cvd_close, start, mid - 1);
    WindowStats wB = CalculateWindowStats(sc.BaseData, cvd_close, mid, end);
    
    // CVD range global
    float cvd_highest = (wA.cvd_max > wB.cvd_max) ? wA.cvd_max : wB.cvd_max;
    float cvd_lowest  = (wA.cvd_min < wB.cvd_min) ? wA.cvd_min : wB.cvd_min;
    float cvd_range = cvd_highest - cvd_lowest;
    
    float price_highest = (wA.price_high > wB.price_high) ? wA.price_high : wB.price_high;
    float price_lowest  = (wA.price_low < wB.price_low) ? wA.price_low : wB.price_low;
    
    // Seuil minimum de divergence
    float cvd_threshold = cvd_range * min_ratio;
    if (cvd_threshold < 20.0f) cvd_threshold = 20.0f;
    
    // Score composite
    float score = 0.0f;
    bool has_classic = false;
    bool has_hidden = false;
    bool classic_bearish = false;
    bool classic_bullish = false;
    
    // ═════════════════════════════════════════════════════════════════════════
    // 1. DIVERGENCE CLASSIQUE BEARISH
    //    Prix Higher High + CVD Lower High → essoufflement acheteurs
    // ═════════════════════════════════════════════════════════════════════════
    
    if (wB.price_high > wA.price_high && 
        wB.cvd_max < (wA.cvd_max - cvd_threshold)) {
        
        has_classic = true;
        classic_bearish = true;
        float strength = (wA.cvd_max - wB.cvd_max) / fmax(cvd_range, 1.0f);
        score -= strength * 0.40f;
        
        // ▼ Flèche rouge au-dessus du high de la barre courante
        sg_ClassicBearish[idx] = sc.BaseData[SC_HIGH][idx] + marker_offset;
        
        // Dessiner les lignes de divergence
        if (draw_lines) {
            // Ligne prix: de High A vers High B (montante)
            DrawDivergenceLine_Price(sc,
                wA.price_high_idx, wA.price_high,
                wB.price_high_idx, wB.price_high,
                sg_ClassicBearish.PrimaryColor,
                50000 + idx % 500,  // Line ID unique
                line_width);
        }
        
        // Alerte
        if (alert_classic && idx == sc.ArraySize - 1) {
            sc.SetAlert(1, "CVD Classic BEARISH Divergence!");
        }
    }
    
    // ═════════════════════════════════════════════════════════════════════════
    // 2. DIVERGENCE CLASSIQUE BULLISH
    //    Prix Lower Low + CVD Higher Low → essoufflement vendeurs
    // ═════════════════════════════════════════════════════════════════════════
    
    if (wB.price_low < wA.price_low && 
        wB.cvd_min > (wA.cvd_min + cvd_threshold)) {
        
        has_classic = true;
        classic_bullish = true;
        float strength = (wB.cvd_min - wA.cvd_min) / fmax(cvd_range, 1.0f);
        score += strength * 0.40f;
        
        // ▲ Flèche verte en-dessous du low
        sg_ClassicBullish[idx] = sc.BaseData[SC_LOW][idx] - marker_offset;
        
        if (draw_lines) {
            // Ligne prix: de Low A vers Low B (descendante)
            DrawDivergenceLine_Price(sc,
                wA.price_low_idx, wA.price_low,
                wB.price_low_idx, wB.price_low,
                sg_ClassicBullish.PrimaryColor,
                51000 + idx % 500,
                line_width);
        }
        
        if (alert_classic && idx == sc.ArraySize - 1) {
            sc.SetAlert(2, "CVD Classic BULLISH Divergence!");
        }
    }
    
    // ═════════════════════════════════════════════════════════════════════════
    // 3. DIVERGENCE CACHÉE BULLISH (avec exclusion mutuelle)
    //    Higher Low prix + Lower Low CVD → continuation haussière
    // ═════════════════════════════════════════════════════════════════════════
    
    if (show_hidden && !classic_bearish &&
        wB.price_low > wA.price_low && 
        wB.cvd_min < (wA.cvd_min - cvd_threshold)) {
        
        has_hidden = true;
        float strength = (wA.cvd_min - wB.cvd_min) / fmax(cvd_range, 1.0f);
        score += strength * 0.25f;
        
        sg_HiddenBullish[idx] = sc.BaseData[SC_LOW][idx] - marker_offset;
        
        if (draw_lines) {
            DrawDivergenceLine_Price(sc,
                wA.price_low_idx, wA.price_low,
                wB.price_low_idx, wB.price_low,
                sg_HiddenBullish.PrimaryColor,
                52000 + idx % 500,
                line_width);
        }
    }
    
    // ═════════════════════════════════════════════════════════════════════════
    // 4. DIVERGENCE CACHÉE BEARISH (avec exclusion mutuelle)
    //    Lower High prix + Higher High CVD → continuation baissière
    // ═════════════════════════════════════════════════════════════════════════
    
    if (show_hidden && !classic_bullish &&
        wB.price_high < wA.price_high && 
        wB.cvd_max > (wA.cvd_max + cvd_threshold)) {
        
        has_hidden = true;
        float strength = (wB.cvd_max - wA.cvd_max) / fmax(cvd_range, 1.0f);
        score -= strength * 0.25f;
        
        sg_HiddenBearish[idx] = sc.BaseData[SC_HIGH][idx] + marker_offset;
        
        if (draw_lines) {
            DrawDivergenceLine_Price(sc,
                wA.price_high_idx, wA.price_high,
                wB.price_high_idx, wB.price_high,
                sg_HiddenBearish.PrimaryColor,
                53000 + idx % 500,
                line_width);
        }
    }
    
    // ═════════════════════════════════════════════════════════════════════════
    // 5. ABSORPTION (prix flat + CVD bouge fort, 3 dernières barres)
    // ═════════════════════════════════════════════════════════════════════════
    
    if (show_absorb && idx >= 3) {
        float recent_high = sc.BaseData[SC_HIGH][idx];
        float recent_low  = sc.BaseData[SC_LOW][idx];
        float recent_cvd_start = cvd_close[idx - 2];
        float recent_cvd_end   = cvd_close[idx];
        
        for (int i = idx - 2; i <= idx; i++) {
            if (sc.BaseData[SC_HIGH][i] > recent_high) recent_high = sc.BaseData[SC_HIGH][i];
            if (sc.BaseData[SC_LOW][i] < recent_low) recent_low = sc.BaseData[SC_LOW][i];
        }
        
        float price_range_ticks = (recent_high - recent_low) / sc.TickSize;
        float cvd_move = recent_cvd_end - recent_cvd_start;
        
        // Absorption non conflictuelle avec hidden de direction opposée
        if (price_range_ticks < absorb_ticks && fabs(cvd_move) > absorb_cvd) {
            bool absorb_conflicts = false;
            
            if (cvd_move > 0) {
                // Absorption BUY — conflit si hidden bearish sur même barre
                absorb_conflicts = (sg_HiddenBearish[idx] != 0);
                if (!absorb_conflicts) {
                    sg_AbsorptionBuy[idx] = sc.BaseData[SC_LOW][idx] - marker_offset * 1.5f;
                    float str = fmin(fabs(cvd_move) / 1000.0f, 1.0f);
                    score += str * 0.20f;
                }
            } else {
                // Absorption SELL — conflit si hidden bullish
                absorb_conflicts = (sg_HiddenBullish[idx] != 0);
                if (!absorb_conflicts) {
                    sg_AbsorptionSell[idx] = sc.BaseData[SC_HIGH][idx] + marker_offset * 1.5f;
                    float str = fmin(fabs(cvd_move) / 1000.0f, 1.0f);
                    score -= str * 0.20f;
                }
            }
        }
    }
    
    // ═════════════════════════════════════════════════════════════════════════
    // 6. CVD FLIP (changement de régime)
    // ═════════════════════════════════════════════════════════════════════════
    
    if (show_flip) {
        float cvd_oldest = cvd_close[start];
        float cvd_newest = cvd_close[end];
        
        if (cvd_oldest < -CVD_FLIP_THRESHOLD && cvd_newest > CVD_FLIP_THRESHOLD) {
            sg_FlipBullish[idx] = sc.BaseData[SC_LOW][idx] - marker_offset * 2.0f;
            float mag = (cvd_newest - cvd_oldest) / fmax(cvd_range, 1.0f);
            score += mag * 0.15f;
        }
        else if (cvd_oldest > CVD_FLIP_THRESHOLD && cvd_newest < -CVD_FLIP_THRESHOLD) {
            sg_FlipBearish[idx] = sc.BaseData[SC_HIGH][idx] + marker_offset * 2.0f;
            float mag = (cvd_oldest - cvd_newest) / fmax(cvd_range, 1.0f);
            score -= mag * 0.15f;
        }
    }
    
    // ═════════════════════════════════════════════════════════════════════════
    // 7. SCORE FINAL
    // ═════════════════════════════════════════════════════════════════════════
    
    // Clamp
    if (score > 1.0f) score = 1.0f;
    if (score < -1.0f) score = -1.0f;
    
    sg_CVDScore[idx] = score;
}
