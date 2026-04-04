#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ANALYSE DES REJETS BOT MIA - Diagnostic 100% Rejets
=============================================================================
Cree: 01/02/2026
But: Analyser les snapshots pour comprendre POURQUOI le bot rejette des trades
Usage: python analyze_bot_rejections.py [date YYYYMMDD]
=============================================================================
"""

import json
import os
from datetime import datetime
from collections import Counter
from pathlib import Path

# Chemins des snapshots
SNAPSHOT_DIRS = [
    r"D:\MIA_IA_system\DATA_SIERRA_CHART\BOT_CPP",  # Chemin principal du bot
    r"D:\LOGS\MIA\SNAPSHOTS",
    r"D:\TRADING_SIERRA_CHART_AUTO\LOGS\SNAPSHOTS",
]

def find_snapshot_file(date_str=None):
    """Trouve le fichier snapshot pour une date donnee"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    
    year = date_str[:4]
    month = date_str[4:6]
    
    # Nom du fichier
    filename = f"bot_snapshot_{date_str}.jsonl"
    
    # Chercher dans le chemin principal du bot (YYYY/MM/YYYYMMDD/)
    main_path = Path(SNAPSHOT_DIRS[0]) / year / month / date_str / filename
    if main_path.exists():
        return main_path
    
    # Chercher dans les autres chemins
    for dir_path in SNAPSHOT_DIRS[1:]:
        filepath = Path(dir_path) / filename
        if filepath.exists():
            return filepath
    
    # Chercher dans le dossier courant
    if Path(filename).exists():
        return Path(filename)
    
    # Derniere tentative: chercher recursivement
    for dir_path in SNAPSHOT_DIRS:
        base = Path(dir_path)
        if base.exists():
            for f in base.rglob(f"*{date_str}*.jsonl"):
                return f
    
    return None

def load_snapshots(filepath):
    """Charge les snapshots depuis un fichier JSONL"""
    snapshots = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    snapshots.append(data)
                except json.JSONDecodeError as e:
                    print(f"[WARN] Ligne invalide: {e}")
    return snapshots

def analyze_rejections(snapshots):
    """Analyse les raisons de rejet"""
    
    # Compteurs
    total = len(snapshots)
    by_action = Counter()
    by_symbol = Counter()
    by_reject_reason = Counter()
    by_layer = Counter()
    
    # Details
    l1_reasons = Counter()
    l2_reasons = Counter()
    l3_reasons = Counter()
    l3_vetos = Counter()
    l4_reasons = Counter()
    
    orders_sent = []
    
    for snap in snapshots:
        action = snap.get('action', 'UNKNOWN')
        symbol = snap.get('sym', 'UNKNOWN')
        reject = snap.get('reject', '')
        
        by_action[action] += 1
        by_symbol[symbol] += 1
        
        if 'REJECT' in action or 'VETO' in action:
            by_reject_reason[reject if reject else 'EMPTY'] += 1
            
            if 'L1' in action:
                by_layer['L1'] += 1
                l1_reasons[reject if reject else 'EMPTY'] += 1
            elif 'L2' in action:
                by_layer['L2'] += 1
                l2_reasons[reject if reject else 'EMPTY'] += 1
            elif 'L3_VETO' in action:
                by_layer['L3_VETO'] += 1
                l3_vetos[reject if reject else 'EMPTY'] += 1
            elif 'L3' in action:
                by_layer['L3'] += 1
                l3_reasons[reject if reject else 'EMPTY'] += 1
            elif 'L4' in action:
                by_layer['L4'] += 1
                l4_reasons[reject if reject else 'EMPTY'] += 1
        
        elif action == 'ORDER_SENT':
            orders_sent.append(snap)
    
    return {
        'total': total,
        'by_action': by_action,
        'by_symbol': by_symbol,
        'by_layer': by_layer,
        'l1_reasons': l1_reasons,
        'l2_reasons': l2_reasons,
        'l3_reasons': l3_reasons,
        'l3_vetos': l3_vetos,
        'l4_reasons': l4_reasons,
        'orders_sent': orders_sent
    }

def print_report(analysis, filepath):
    """Affiche le rapport d'analyse"""
    
    print("\n" + "="*70)
    print("   RAPPORT D'ANALYSE DES REJETS - MIA BOT")
    print("="*70)
    print(f"Fichier: {filepath}")
    print(f"Total snapshots: {analysis['total']}")
    print("="*70)
    
    # Resume par action
    print("\n[1] RESUME PAR ACTION:")
    print("-"*40)
    total_rejects = 0
    total_orders = 0
    for action, count in analysis['by_action'].most_common():
        pct = count / analysis['total'] * 100
        marker = ""
        if 'REJECT' in action or 'VETO' in action:
            total_rejects += count
            marker = " <-- REJET"
        elif action == 'ORDER_SENT':
            total_orders += count
            marker = " <-- ORDRE"
        print(f"  {action:20} : {count:5} ({pct:5.1f}%){marker}")
    
    if analysis['total'] > 0:
        reject_rate = total_rejects / analysis['total'] * 100
        print(f"\n  >>> TAUX DE REJET: {reject_rate:.1f}% ({total_rejects}/{analysis['total']})")
        print(f"  >>> ORDRES ENVOYES: {total_orders}")
    
    # Par symbole
    print("\n[2] PAR SYMBOLE:")
    print("-"*40)
    for sym, count in analysis['by_symbol'].most_common():
        print(f"  {sym:10} : {count:5}")
    
    # Par layer
    print("\n[3] REJETS PAR LAYER:")
    print("-"*40)
    for layer, count in sorted(analysis['by_layer'].items()):
        pct = count / max(1, sum(analysis['by_layer'].values())) * 100
        bar = "#" * int(pct / 2)
        print(f"  {layer:10} : {count:5} ({pct:5.1f}%) {bar}")
    
    # Details L1
    if analysis['l1_reasons']:
        print("\n[4] DETAILS REJETS L1 (Pas de niveau proche):")
        print("-"*40)
        for reason, count in analysis['l1_reasons'].most_common(10):
            print(f"  {count:4}x : {reason[:60]}")
    
    # Details L2
    if analysis['l2_reasons']:
        print("\n[5] DETAILS REJETS L2 (OrderFlow insuffisant):")
        print("-"*40)
        for reason, count in analysis['l2_reasons'].most_common(10):
            print(f"  {count:4}x : {reason[:60]}")
    
    # Details L3 VETO
    if analysis['l3_vetos']:
        print("\n[6] DETAILS VETOS L3 (Contre-tendance/Divergence):")
        print("-"*40)
        for reason, count in analysis['l3_vetos'].most_common(10):
            print(f"  {count:4}x : {reason[:60]}")
    
    # Details L3
    if analysis['l3_reasons']:
        print("\n[7] DETAILS REJETS L3 (Contexte defavorable):")
        print("-"*40)
        for reason, count in analysis['l3_reasons'].most_common(10):
            print(f"  {count:4}x : {reason[:60]}")
    
    # Details L4
    if analysis['l4_reasons']:
        print("\n[8] DETAILS REJETS L4 (Combo filter):")
        print("-"*40)
        for reason, count in analysis['l4_reasons'].most_common(10):
            print(f"  {count:4}x : {reason[:60]}")
    
    # Ordres envoyes
    if analysis['orders_sent']:
        print("\n[9] ORDRES ENVOYES:")
        print("-"*40)
        for order in analysis['orders_sent'][-5:]:  # 5 derniers
            print(f"  {order.get('sym', '?')} @ {order.get('price', 0):.2f}")
    
    print("\n" + "="*70)
    print("FIN DU RAPPORT")
    print("="*70)

def main():
    import sys
    
    # Date optionnelle en argument
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    
    print("Recherche des fichiers snapshot...")
    filepath = find_snapshot_file(date_str)
    
    if not filepath:
        print(f"[ERREUR] Aucun fichier snapshot trouve!")
        print(f"Chemins recherches:")
        for d in SNAPSHOT_DIRS:
            print(f"  - {d}")
        print("\nCreez le dossier et relancez le bot pour generer des snapshots.")
        return
    
    print(f"Fichier trouve: {filepath}")
    print("Chargement des snapshots...")
    
    snapshots = load_snapshots(filepath)
    
    if not snapshots:
        print("[ERREUR] Aucun snapshot dans le fichier!")
        return
    
    print(f"Charge: {len(snapshots)} snapshots")
    print("Analyse en cours...")
    
    analysis = analyze_rejections(snapshots)
    print_report(analysis, filepath)

if __name__ == "__main__":
    main()
