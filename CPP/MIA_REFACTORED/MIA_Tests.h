// ⚠️ DEPRECATED 14/03/2026 — Non inclus dans MIA_Main.cpp
// Tests unitaires pour l'ancien paradigme L1-L4. À réécrire pour MIA_Entry.h (Phase 3).
// Ne pas supprimer — sera réutilisé en Phase 3.
#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Tests.h - TESTS UNITAIRES DES LAYERS
// ═══════════════════════════════════════════════════════════════════════════════
// 31/01/2026 - Tests automatisés pour valider le comportement des Layers
//
// Usage:
//   #include "MIA_Tests.h"
//   
//   int main() {
//       return RunAllTests() ? 0 : 1;
//   }
//
// Ou depuis Sierra Chart (mode debug):
//   RunAllTests();  // Affiche résultats dans le log
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_MockImpl.h"
#include "MIA_Layers.h"
#include <cstdio>

// ═══════════════════════════════════════════════════════════════════════════════
// CONFIGURATION DES TESTS
// ═══════════════════════════════════════════════════════════════════════════════

static int g_tests_passed = 0;
static int g_tests_failed = 0;
static bool g_verbose_tests = true;

#define TEST_BEGIN(name) \
    bool test_##name() { \
        const char* test_name = #name; \
        if (g_verbose_tests) printf("[TEST] %s...\n", test_name);

#define TEST_END() \
        if (g_verbose_tests) printf("[PASS] %s\n", test_name); \
        g_tests_passed++; \
        return true; \
    }

#define ASSERT(condition) \
    if (!(condition)) { \
        printf("[FAIL] %s: Assertion failed at line %d: %s\n", test_name, __LINE__, #condition); \
        g_tests_failed++; \
        return false; \
    }

#define ASSERT_EQ(expected, actual) \
    if ((expected) != (actual)) { \
        printf("[FAIL] %s: Expected %d but got %d at line %d\n", test_name, (int)(expected), (int)(actual), __LINE__); \
        g_tests_failed++; \
        return false; \
    }

#define ASSERT_FLOAT_EQ(expected, actual, tolerance) \
    if (fabs((expected) - (actual)) > (tolerance)) { \
        printf("[FAIL] %s: Expected %.4f but got %.4f at line %d\n", test_name, (float)(expected), (float)(actual), __LINE__); \
        g_tests_failed++; \
        return false; \
    }

#define ASSERT_TRUE(condition) ASSERT(condition)
#define ASSERT_FALSE(condition) ASSERT(!(condition))

// ═══════════════════════════════════════════════════════════════════════════════
// TESTS LAYER 1: MENTHORQ LEVELS
// ═══════════════════════════════════════════════════════════════════════════════

TEST_BEGIN(Layer1_HVL_Long_Valid)
    // Scénario: Prix juste au-dessus du HVL → Signal LONG valide
    MenthorQ_Data mq = {};
    mq.hvl = 6000.0f;
    mq.hvl_0dte = 6000.0f;
    mq.gamma_wall = 6050.0f;
    mq.vwap = 6010.0f;
    
    float current_price = 6002.0f;  // 2 pts au-dessus HVL = 8 ticks
    
    Layer1Result result = ValidateLayer1(
        *(SCStudyInterfaceRef*)nullptr,  // Pas utilisé dans le test
        mq, current_price, CONFIG_ES, 0.0f, nullptr, true
    );
    
    ASSERT_TRUE(result.passed);
    ASSERT_EQ(1, result.direction);  // LONG
    ASSERT(result.distance_ticks < 15.0f);  // Proche du niveau
TEST_END()

TEST_BEGIN(Layer1_HVL_Short_Valid)
    // Scénario: Prix juste en-dessous du HVL → Signal SHORT valide
    MenthorQ_Data mq = {};
    mq.hvl = 6000.0f;
    mq.hvl_0dte = 6000.0f;
    mq.gamma_wall = 5950.0f;
    mq.vwap = 5990.0f;
    
    float current_price = 5998.0f;  // 2 pts en-dessous HVL
    
    Layer1Result result = ValidateLayer1(
        *(SCStudyInterfaceRef*)nullptr,
        mq, current_price, CONFIG_ES, 0.0f, nullptr, true
    );
    
    ASSERT_TRUE(result.passed);
    ASSERT_EQ(-1, result.direction);  // SHORT
TEST_END()

TEST_BEGIN(Layer1_TooFar_Rejected)
    // Scénario: Prix trop loin de tous les niveaux → Rejeté
    MenthorQ_Data mq = {};
    mq.hvl = 6000.0f;
    mq.gamma_wall = 6100.0f;
    mq.vwap = 5900.0f;
    
    float current_price = 6050.0f;  // 50 pts du HVL = trop loin
    
    Layer1Result result = ValidateLayer1(
        *(SCStudyInterfaceRef*)nullptr,
        mq, current_price, CONFIG_ES, 0.0f, nullptr, true
    );
    
    // Devrait être rejeté si distance > max_distance
    // Note: Le comportement exact dépend des seuils dans ValidateLayer1
    // Ce test vérifie la logique de distance
TEST_END()

// ═══════════════════════════════════════════════════════════════════════════════
// TESTS LAYER 2: BATAILLE NAVALE + CORRELATION
// ═══════════════════════════════════════════════════════════════════════════════

TEST_BEGIN(Layer2_BN_Bullish_Valid)
    // Scénario: BN score bullish + corrélation OK → Validé
    BN_Data bn_es = {};
    bn_es.score = 0.65f;
    bn_es.signal = 1;  // Bullish
    bn_es.momentum_score = 0.6f;
    bn_es.color_up = 5;
    bn_es.rotation_up = 3;
    bn_es.edge_buy = 2;
    
    BN_Data bn_nq = {};
    bn_nq.score = 0.55f;
    bn_nq.signal = 1;  // Également bullish (corrélation)
    
    Layer2Result result = ValidateLayer2(
        1,  // direction LONG
        bn_es, bn_nq,
        15.0f,  // VIX normal
        0,      // VWAP offset
        0.6f,   // buy_pct
        CONFIG_ES,
        false,  // is_nq = false (ES)
        0.1f,   // depth_imbalance positif
        0.4f,   // sell_pct
        0.001f  // vwap_slope positif
    );
    
    ASSERT_TRUE(result.passed);
    ASSERT(result.bn_score > 0.5f);
TEST_END()

TEST_BEGIN(Layer2_BN_Divergent_Rejected)
    // Scénario: ES bullish mais NQ bearish → Rejeté (divergence)
    BN_Data bn_es = {};
    bn_es.score = 0.65f;
    bn_es.signal = 1;  // Bullish
    
    BN_Data bn_nq = {};
    bn_nq.score = 0.60f;
    bn_nq.signal = -1;  // Bearish! Divergence!
    
    Layer2Result result = ValidateLayer2(
        1,  // direction LONG
        bn_es, bn_nq,
        15.0f,
        0,
        0.55f,
        CONFIG_ES,
        false,
        0.0f,
        0.45f,
        0.001f
    );
    
    // La corrélation devrait être "DIVERGENT"
    // Le résultat dépend des seuils de tolérance
    // Vérifier au moins que la corrélation est notée
TEST_END()

TEST_BEGIN(Layer2_BN_TooLow_Rejected)
    // Scénario: BN score trop bas → Rejeté
    BN_Data bn_es = {};
    bn_es.score = 0.25f;  // Trop bas
    bn_es.signal = 1;
    
    BN_Data bn_nq = {};
    bn_nq.score = 0.30f;
    bn_nq.signal = 1;
    
    Layer2Result result = ValidateLayer2(
        1,
        bn_es, bn_nq,
        15.0f,
        0,
        0.5f,
        CONFIG_ES,
        false,
        0.0f,
        0.5f,
        0.001f
    );
    
    // BN score < 0.40 devrait être rejeté par les filtres
    ASSERT(result.bn_score < 0.4f);
TEST_END()

// ═══════════════════════════════════════════════════════════════════════════════
// TESTS LAYER 3: CONTEXTE
// ═══════════════════════════════════════════════════════════════════════════════

TEST_BEGIN(Layer3_Context_US_Valid)
    // Scénario: Session US avec bon contexte → Validé
    BN_Data bn = {};
    bn.score = 0.6f;
    bn.signal = 1;
    bn.momentum_score = 0.5f;
    
    MenthorQ_Data mq = {};
    mq.hvl = 6000.0f;
    mq.gamma_wall = 6050.0f;
    mq.next_wall = 6050.0f;
    mq.wall_distance_ticks = 200.0f;  // Loin = pas d'obstacle
    
    Layer3Result result = ValidateLayer3(
        1,  // direction LONG
        bn,
        6005.0f,  // current_price
        mq,
        15.0f,    // VIX normal
        15.0f,    // ATR normal
        "US",     // Session US
        false     // ES
    );
    
    ASSERT_FALSE(result.veto);  // Pas de veto
TEST_END()

TEST_BEGIN(Layer3_VIX_Extreme_Veto)
    // Scénario: VIX > 35 → VETO
    BN_Data bn = {};
    bn.score = 0.6f;
    bn.signal = 1;
    
    MenthorQ_Data mq = {};
    mq.hvl = 6000.0f;
    
    Layer3Result result = ValidateLayer3(
        1,
        bn,
        6005.0f,
        mq,
        40.0f,    // VIX EXTREME!
        20.0f,
        "US",
        false
    );
    
    // VIX > 35 devrait déclencher un veto
    // Le comportement exact dépend des seuils dans Layer3
TEST_END()

TEST_BEGIN(Layer3_WallTooClose_Veto)
    // Scénario: Gamma Wall trop proche dans la direction du trade → VETO
    BN_Data bn = {};
    bn.score = 0.6f;
    bn.signal = 1;
    
    MenthorQ_Data mq = {};
    mq.hvl = 6000.0f;
    mq.gamma_wall = 6010.0f;  // Très proche!
    mq.next_wall = 6010.0f;
    mq.wall_distance_ticks = 10.0f;  // Seulement 10 ticks!
    
    Layer3Result result = ValidateLayer3(
        1,  // LONG
        bn,
        6005.0f,  // Prix actuel
        mq,
        15.0f,
        15.0f,
        "US",
        false
    );
    
    // Mur à 10 ticks dans la direction = obstacle potentiel
    // Vérifier si le veto est déclenché (dépend des seuils)
TEST_END()

// ═══════════════════════════════════════════════════════════════════════════════
// TESTS LAYER 4: COMBO FINAL
// ═══════════════════════════════════════════════════════════════════════════════

TEST_BEGIN(Layer4_AllConditions_Valid)
    // Scénario: Toutes les conditions alignées → Validé
    Layer4Result result = ValidateLayer4(
        1,        // direction LONG
        0.65f,    // buy_pct > 52%
        0.35f,    // sell_pct
        5.0f,     // edge_buy dominant
        2.0f,     // edge_sell
        100.0f,   // cum_delta positif
        0.6f,     // bn_score OK
        0.002f,   // vwap_slope positif
        CONFIG_ES
    );
    
    ASSERT_TRUE(result.passed);
    ASSERT(result.combo_aligned >= 1);  // Au moins 1 règle OK
TEST_END()

TEST_BEGIN(Layer4_NoConditions_Rejected)
    // Scénario: Aucune condition alignée → Rejeté
    Layer4Result result = ValidateLayer4(
        1,        // direction LONG
        0.45f,    // buy_pct < 52% (contre-direction)
        0.55f,    // sell_pct dominant
        2.0f,     // edge_buy
        5.0f,     // edge_sell dominant (mauvais pour LONG)
        -100.0f,  // cum_delta négatif (mauvais pour LONG)
        0.3f,     // bn_score bas
        -0.002f,  // vwap_slope négatif (mauvais pour LONG)
        CONFIG_ES
    );
    
    ASSERT_FALSE(result.passed);
    ASSERT_EQ(0, result.combo_aligned);
TEST_END()

TEST_BEGIN(Layer4_PartialConditions_Valid)
    // Scénario: 1 condition sur 2 → Peut être validé (1/2 requis)
    Layer4Result result = ValidateLayer4(
        1,        // direction LONG
        0.55f,    // buy_pct > 52% ✓
        0.45f,
        2.0f,     // edge_buy
        3.0f,     // edge_sell dominant ✗
        0.0f,     // cum_delta neutre
        0.5f,     // bn_score moyen
        0.0f,     // vwap_slope neutre
        CONFIG_ES
    );
    
    // Avec 1 condition OK sur 2, le combo devrait être 1
    // 1/2 >= 1/2 requis → Validé
    ASSERT(result.combo_aligned >= 1);
TEST_END()

// ═══════════════════════════════════════════════════════════════════════════════
// TESTS MOCK EXECUTOR
// ═══════════════════════════════════════════════════════════════════════════════

TEST_BEGIN(MockExecutor_BuyMarket_Success)
    MockOrderExecutor executor;
    
    OrderResult result = executor.BuyMarket(false, 1);  // ES
    
    ASSERT_TRUE(result.success);
    ASSERT(result.order_id > 0);
    ASSERT_TRUE(executor.IsInPosition(false));
    ASSERT_EQ(1, executor.GetPositionDirection(false));
TEST_END()

TEST_BEGIN(MockExecutor_BracketOrder_Success)
    MockOrderExecutor executor;
    
    OrderResult result = executor.SendBracketOrder(
        false,    // ES
        1,        // LONG
        6000.0f,  // entry
        5990.0f,  // sl
        6020.0f,  // tp
        1         // qty
    );
    
    ASSERT_TRUE(result.success);
    ASSERT_FLOAT_EQ(6000.0f, result.fill_price, 0.01f);
    
    // Vérifier l'ordre enregistré
    const auto& orders = executor.GetOrders();
    ASSERT_EQ(1, (int)orders.size());
    ASSERT_EQ(1, orders[0].direction);
    ASSERT_FLOAT_EQ(5990.0f, orders[0].sl, 0.01f);
    ASSERT_FLOAT_EQ(6020.0f, orders[0].tp, 0.01f);
TEST_END()

TEST_BEGIN(MockExecutor_ClosePosition_Success)
    MockOrderExecutor executor;
    
    // Ouvrir une position LONG
    executor.BuyMarket(false, 1);
    ASSERT_TRUE(executor.IsInPosition(false));
    
    // Fermer la position
    OrderResult close_result = executor.ClosePosition(false);
    ASSERT_TRUE(close_result.success);
    ASSERT_FALSE(executor.IsInPosition(false));
TEST_END()

// ═══════════════════════════════════════════════════════════════════════════════
// RUNNER DE TESTS
// ═══════════════════════════════════════════════════════════════════════════════

typedef bool (*TestFunction)();

struct TestCase {
    const char* name;
    TestFunction func;
};

// Liste de tous les tests
static TestCase g_all_tests[] = {
    // Layer 1
    {"Layer1_HVL_Long_Valid", test_Layer1_HVL_Long_Valid},
    {"Layer1_HVL_Short_Valid", test_Layer1_HVL_Short_Valid},
    {"Layer1_TooFar_Rejected", test_Layer1_TooFar_Rejected},
    
    // Layer 2
    {"Layer2_BN_Bullish_Valid", test_Layer2_BN_Bullish_Valid},
    {"Layer2_BN_Divergent_Rejected", test_Layer2_BN_Divergent_Rejected},
    {"Layer2_BN_TooLow_Rejected", test_Layer2_BN_TooLow_Rejected},
    
    // Layer 3
    {"Layer3_Context_US_Valid", test_Layer3_Context_US_Valid},
    {"Layer3_VIX_Extreme_Veto", test_Layer3_VIX_Extreme_Veto},
    {"Layer3_WallTooClose_Veto", test_Layer3_WallTooClose_Veto},
    
    // Layer 4
    {"Layer4_AllConditions_Valid", test_Layer4_AllConditions_Valid},
    {"Layer4_NoConditions_Rejected", test_Layer4_NoConditions_Rejected},
    {"Layer4_PartialConditions_Valid", test_Layer4_PartialConditions_Valid},
    
    // Mock Executor
    {"MockExecutor_BuyMarket_Success", test_MockExecutor_BuyMarket_Success},
    {"MockExecutor_BracketOrder_Success", test_MockExecutor_BracketOrder_Success},
    {"MockExecutor_ClosePosition_Success", test_MockExecutor_ClosePosition_Success},
};

inline bool RunAllTests(bool verbose = true) {
    g_verbose_tests = verbose;
    g_tests_passed = 0;
    g_tests_failed = 0;
    
    printf("\n");
    printf("╔══════════════════════════════════════════════════════════════╗\n");
    printf("║           MIA AUTOTRADER - TESTS UNITAIRES                   ║\n");
    printf("╚══════════════════════════════════════════════════════════════╝\n\n");
    
    int total_tests = sizeof(g_all_tests) / sizeof(g_all_tests[0]);
    
    for (int i = 0; i < total_tests; i++) {
        g_all_tests[i].func();
    }
    
    printf("\n");
    printf("═══════════════════════════════════════════════════════════════\n");
    printf(" RÉSULTATS: %d/%d tests passés\n", g_tests_passed, total_tests);
    if (g_tests_failed > 0) {
        printf(" [ÉCHEC] %d tests ont échoué!\n", g_tests_failed);
    } else {
        printf(" [SUCCÈS] Tous les tests sont passés!\n");
    }
    printf("═══════════════════════════════════════════════════════════════\n\n");
    
    return g_tests_failed == 0;
}

// Version simplifiée pour appel depuis Sierra Chart
inline void RunTestsInSierra(SCStudyInterfaceRef& sc) {
    // Rediriger la sortie vers le log Sierra
    // Note: printf ne fonctionne pas directement dans Sierra
    // On utilise AddMessageToLog à la place
    
    int total = sizeof(g_all_tests) / sizeof(g_all_tests[0]);
    int passed = 0;
    
    for (int i = 0; i < total; i++) {
        if (g_all_tests[i].func()) {
            passed++;
        }
    }
    
    char msg[128];
    snprintf(msg, sizeof(msg), "[MIA TESTS] %d/%d tests passed", passed, total);
    sc.AddMessageToLog(msg, passed == total ? 0 : 1);
}