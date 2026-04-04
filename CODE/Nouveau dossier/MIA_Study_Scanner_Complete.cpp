// =============================================================================
// MIA_Study_Scanner_Complete.cpp - Scanner COMPLET unifié
// =============================================================================
// FONCTIONNALITÉS:
//   1. Liste toutes les études avec leurs noms (comme MIA_Study_Inspector)
//   2. Scanne toutes les valeurs des subgraphs (comme TEST_Scan_All)
//   3. Sortie en JSON pour faciliter l'analyse Python
//   4. Fichier de sortie à la racine D:\MIA_IA_system
// =============================================================================
// USAGE: Ajouter sur le chart à scanner, ou spécifier un numéro de chart
// =============================================================================

#include "sierrachart.h"
#include <ctime>
#include <cstdio>

SCDLLName("MIA_Study_Scanner_Complete")

// =============================================================================
// HELPERS
// =============================================================================

static void EnsureDirectory(const char* path) {
#ifdef _WIN32
    CreateDirectoryA(path, NULL);
#endif
}

static SCString GetTimestamp() {
    time_t now = time(nullptr);
    struct tm* t = localtime(&now);
    char buf[32];
    snprintf(buf, sizeof(buf), "%04d%02d%02d_%02d%02d%02d",
             t ? t->tm_year + 1900 : 1970,
             t ? t->tm_mon + 1 : 1,
             t ? t->tm_mday : 1,
             t ? t->tm_hour : 0,
             t ? t->tm_min : 0,
             t ? t->tm_sec : 0);
    return SCString(buf);
}

static SCString GetDateOnly() {
    time_t now = time(nullptr);
    struct tm* t = localtime(&now);
    char buf[16];
    snprintf(buf, sizeof(buf), "%04d%02d%02d",
             t ? t->tm_year + 1900 : 1970,
             t ? t->tm_mon + 1 : 1,
             t ? t->tm_mday : 1);
    return SCString(buf);
}

// Escape les guillemets pour JSON
static SCString EscapeJSON(const SCString& input) {
    SCString result;
    const char* s = input.GetChars();
    while (*s) {
        if (*s == '"') result += "\\\"";
        else if (*s == '\\') result += "\\\\";
        else if (*s == '\n') result += "\\n";
        else if (*s == '\r') result += "\\r";
        else if (*s == '\t') result += "\\t";
        else result += *s;
        s++;
    }
    return result;
}

// =============================================================================
// MAIN STUDY FUNCTION
// =============================================================================

SCSFExport scsf_MIA_Study_Scanner_Complete(SCStudyInterfaceRef sc)
{
    // --- INPUTS ---
    SCInputRef Input_ChartToScan = sc.Input[0];
    SCInputRef Input_MaxStudyIndex = sc.Input[1];
    SCInputRef Input_MaxSubgraph = sc.Input[2];
    SCInputRef Input_ForceRescan = sc.Input[3];
    SCInputRef Input_OutputMode = sc.Input[4];
    SCInputRef Input_ScanOtherCharts = sc.Input[5];
    SCInputRef Input_OtherChart1 = sc.Input[6];
    SCInputRef Input_OtherChart2 = sc.Input[7];
    SCInputRef Input_OtherChart3 = sc.Input[8];
    SCInputRef Input_OtherChart4 = sc.Input[9];

    if (sc.SetDefaults) {
        sc.GraphName = "MIA - Study Scanner Complete";
        sc.StudyDescription = "Scanner complet: liste études + valeurs subgraphs. Output: D:\\MIA_IA_system";
        sc.AutoLoop = 0;
        sc.UpdateAlways = 1;

        Input_ChartToScan.Name = "Chart to Scan (0 = current)";
        Input_ChartToScan.SetInt(0);

        Input_MaxStudyIndex.Name = "Max Study Index";
        Input_MaxStudyIndex.SetInt(100);

        Input_MaxSubgraph.Name = "Max Subgraph Index";
        Input_MaxSubgraph.SetInt(100);

        Input_ForceRescan.Name = "Force Rescan (toggle to rescan)";
        Input_ForceRescan.SetInt(0);

        Input_OutputMode.Name = "Output Mode (0=JSON, 1=TXT, 2=Both)";
        Input_OutputMode.SetInt(0);

        Input_ScanOtherCharts.Name = "Also Scan Other Charts?";
        Input_ScanOtherCharts.SetYesNo(0);

        Input_OtherChart1.Name = "Other Chart #1 (0=skip)";
        Input_OtherChart1.SetInt(0);

        Input_OtherChart2.Name = "Other Chart #2 (0=skip)";
        Input_OtherChart2.SetInt(0);

        Input_OtherChart3.Name = "Other Chart #3 (0=skip)";
        Input_OtherChart3.SetInt(0);

        Input_OtherChart4.Name = "Other Chart #4 (0=skip)";
        Input_OtherChart4.SetInt(0);

        return;
    }

    // --- PERSISTENT STATE ---
    int& done = sc.GetPersistentInt(1);
    int& lastRescanValue = sc.GetPersistentInt(2);

    // Reset si toggle rescan
    if (Input_ForceRescan.GetInt() != lastRescanValue) {
        lastRescanValue = Input_ForceRescan.GetInt();
        done = 0;
    }

    if (done == 1) return;
    done = 1;

    // --- PARAMETERS ---
    const int maxStudy = Input_MaxStudyIndex.GetInt() > 0 ? Input_MaxStudyIndex.GetInt() : 100;
    const int maxSG = Input_MaxSubgraph.GetInt() > 0 ? Input_MaxSubgraph.GetInt() : 100;
    const int outputMode = Input_OutputMode.GetInt();

    // --- BUILD LIST OF CHARTS TO SCAN ---
    int chartsToScan[10];
    int numCharts = 0;

    // Chart principal
    int mainChart = Input_ChartToScan.GetInt();
    if (mainChart <= 0) mainChart = sc.ChartNumber;
    chartsToScan[numCharts++] = mainChart;

    // Autres charts si activé
    if (Input_ScanOtherCharts.GetYesNo()) {
        if (Input_OtherChart1.GetInt() > 0) chartsToScan[numCharts++] = Input_OtherChart1.GetInt();
        if (Input_OtherChart2.GetInt() > 0) chartsToScan[numCharts++] = Input_OtherChart2.GetInt();
        if (Input_OtherChart3.GetInt() > 0) chartsToScan[numCharts++] = Input_OtherChart3.GetInt();
        if (Input_OtherChart4.GetInt() > 0) chartsToScan[numCharts++] = Input_OtherChart4.GetInt();
    }

    // --- ENSURE OUTPUT DIRECTORY ---
    EnsureDirectory("D:\\MIA_IA_system");

    SCString timestamp = GetTimestamp();
    SCString dateOnly = GetDateOnly();

    // --- SCAN EACH CHART ---
    for (int c = 0; c < numCharts; c++) {
        int chartNum = chartsToScan[c];

        // === FICHIER JSON ===
        FILE* fjson = nullptr;
        if (outputMode == 0 || outputMode == 2) {
            SCString jsonPath;
            jsonPath.Format("D:\\MIA_IA_system\\SCAN_chart%d_%s.json", chartNum, timestamp.GetChars());
            fjson = fopen(jsonPath.GetChars(), "w");
            if (fjson) {
                fprintf(fjson, "{\n");
                fprintf(fjson, "  \"scan_info\": {\n");
                fprintf(fjson, "    \"chart\": %d,\n", chartNum);
                fprintf(fjson, "    \"timestamp\": \"%s\",\n", timestamp.GetChars());
                fprintf(fjson, "    \"max_study\": %d,\n", maxStudy);
                fprintf(fjson, "    \"max_subgraph\": %d\n", maxSG);
                fprintf(fjson, "  },\n");
                fprintf(fjson, "  \"studies\": [\n");
            }
        }

        // === FICHIER TXT ===
        FILE* ftxt = nullptr;
        if (outputMode == 1 || outputMode == 2) {
            SCString txtPath;
            txtPath.Format("D:\\MIA_IA_system\\SCAN_chart%d_%s.txt", chartNum, timestamp.GetChars());
            ftxt = fopen(txtPath.GetChars(), "w");
            if (ftxt) {
                fprintf(ftxt, "=======================================================================\n");
                fprintf(ftxt, "  MIA STUDY SCANNER - CHART %d\n", chartNum);
                fprintf(ftxt, "  Timestamp: %s\n", timestamp.GetChars());
                fprintf(ftxt, "  Scanning Studies 1-%d, Subgraphs 0-%d\n", maxStudy, maxSG);
                fprintf(ftxt, "=======================================================================\n\n");
            }
        }

        int totalStudies = 0;
        int totalValues = 0;
        bool firstStudyJson = true;

        // --- SCAN PAR ÉTUDE ---
        for (int studyIdx = 1; studyIdx <= maxStudy; studyIdx++) {
            
            // Essayer de récupérer l'ID de l'étude
            int studyID = sc.GetStudyIDByIndex(chartNum, studyIdx);
            
            // Récupérer nom de l'étude (même si ID = 0, on peut avoir des données)
            SCString studyName = "";
            SCString shortName = "";
            int nSubgraphs = 0;

            if (studyID > 0) {
                studyName = sc.GetStudyNameFromChart(chartNum, studyID);
                sc.GetChartStudyShortName(chartNum, studyID, shortName);
                
                SCGraphData studyGraphData;
                sc.GetStudyArraysFromChartUsingID(chartNum, studyID, studyGraphData);
                nSubgraphs = studyGraphData.GetArraySize();
            }

            // --- SCANNER TOUS LES SUBGRAPHS (même si studyID = 0) ---
            bool hasData = false;
            SCString subgraphsJson = "";
            SCString subgraphsTxt = "";
            int sgCount = 0;

            for (int sg = 0; sg <= maxSG; sg++) {
                SCFloatArray arr;
                
                // Utiliser studyIdx directement (certains charts n'ont pas d'ID mais ont des données)
                sc.GetStudyArrayFromChartUsingID(chartNum, studyIdx, sg, arr);

                if (arr.GetArraySize() > 0) {
                    int lastIdx = arr.GetArraySize() - 1;
                    float val = arr[lastIdx];

                    // Valeur valide et non-nulle?
                    if (val != 0 && val == val && val < 1e10 && val > -1e10) {
                        hasData = true;
                        sgCount++;
                        totalValues++;

                        // Récupérer nom du subgraph si possible
                        SCString sgName = "";
                        if (studyID > 0) {
                            sc.GetStudySubgraphNameFromChart(chartNum, studyID, sg, sgName);
                        }

                        // JSON format
                        if (sgCount > 1) subgraphsJson += ",\n";
                        SCString sgJson;
                        sgJson.Format("        {\"sg\": %d, \"value\": %.4f, \"name\": \"%s\"}",
                                      sg, val, EscapeJSON(sgName).GetChars());
                        subgraphsJson += sgJson;

                        // TXT format
                        SCString sgTxt;
                        if (sgName.GetLength() > 0) {
                            sgTxt.Format("    sg%d = %.4f  [%s]\n", sg, val, sgName.GetChars());
                        } else {
                            sgTxt.Format("    sg%d = %.4f\n", sg, val);
                        }
                        subgraphsTxt += sgTxt;
                    }
                }
            }

            // --- ÉCRIRE SI DONNÉES TROUVÉES ---
            if (hasData) {
                totalStudies++;

                // JSON
                if (fjson) {
                    if (!firstStudyJson) fprintf(fjson, ",\n");
                    firstStudyJson = false;

                    fprintf(fjson, "    {\n");
                    fprintf(fjson, "      \"study_index\": %d,\n", studyIdx);
                    fprintf(fjson, "      \"study_id\": %d,\n", studyID);
                    fprintf(fjson, "      \"name\": \"%s\",\n", EscapeJSON(studyName).GetChars());
                    fprintf(fjson, "      \"short_name\": \"%s\",\n", EscapeJSON(shortName).GetChars());
                    fprintf(fjson, "      \"n_subgraphs_declared\": %d,\n", nSubgraphs);
                    fprintf(fjson, "      \"n_values_found\": %d,\n", sgCount);
                    fprintf(fjson, "      \"subgraphs\": [\n");
                    fprintf(fjson, "%s\n", subgraphsJson.GetChars());
                    fprintf(fjson, "      ]\n");
                    fprintf(fjson, "    }");
                }

                // TXT
                if (ftxt) {
                    fprintf(ftxt, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
                    fprintf(ftxt, "STUDY %d (ID:%d) - %s\n", studyIdx, studyID, studyName.GetChars());
                    if (shortName.GetLength() > 0) {
                        fprintf(ftxt, "Short: %s\n", shortName.GetChars());
                    }
                    fprintf(ftxt, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
                    fprintf(ftxt, "%s\n", subgraphsTxt.GetChars());
                }
            }
        }

        // --- FINALISER FICHIERS ---
        if (fjson) {
            fprintf(fjson, "\n  ],\n");
            fprintf(fjson, "  \"summary\": {\n");
            fprintf(fjson, "    \"total_studies_with_data\": %d,\n", totalStudies);
            fprintf(fjson, "    \"total_values_found\": %d\n", totalValues);
            fprintf(fjson, "  }\n");
            fprintf(fjson, "}\n");
            fclose(fjson);
        }

        if (ftxt) {
            fprintf(ftxt, "\n=======================================================================\n");
            fprintf(ftxt, "  SUMMARY\n");
            fprintf(ftxt, "=======================================================================\n");
            fprintf(ftxt, "  Studies with data: %d\n", totalStudies);
            fprintf(ftxt, "  Total values found: %d\n", totalValues);
            fprintf(ftxt, "=======================================================================\n");
            fclose(ftxt);
        }

        // --- LOG ---
        SCString msg;
        msg.Format("[MIA Scanner] Chart %d: %d studies, %d values -> D:\\MIA_IA_system\\SCAN_chart%d_%s.*",
                   chartNum, totalStudies, totalValues, chartNum, timestamp.GetChars());
        sc.AddMessageToLog(msg, 0);
    }

    // --- CRÉER FICHIER RÉCAPITULATIF MULTI-CHARTS ---
    if (numCharts > 1) {
        SCString summaryPath;
        summaryPath.Format("D:\\MIA_IA_system\\SCAN_SUMMARY_%s.txt", timestamp.GetChars());
        FILE* fsum = fopen(summaryPath.GetChars(), "w");
        if (fsum) {
            fprintf(fsum, "MIA STUDY SCANNER - MULTI-CHART SCAN\n");
            fprintf(fsum, "Timestamp: %s\n\n", timestamp.GetChars());
            fprintf(fsum, "Charts scanned: ");
            for (int i = 0; i < numCharts; i++) {
                fprintf(fsum, "%d", chartsToScan[i]);
                if (i < numCharts - 1) fprintf(fsum, ", ");
            }
            fprintf(fsum, "\n\nSee individual SCAN_chartX_*.json files for details.\n");
            fclose(fsum);
        }
    }

    SCString finalMsg;
    finalMsg.Format("[MIA Scanner] COMPLETE! Scanned %d chart(s). Files in D:\\MIA_IA_system\\", numCharts);
    sc.AddMessageToLog(finalMsg, 0);
}
