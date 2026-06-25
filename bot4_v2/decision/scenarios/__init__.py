"""Bot 4 v2 scenarios package — Detectors individuels (1 fichier par scenario).

Spec section 3 P3 : 17 scenarios cibles v2.

Implementation phasee (batch 2 P3 = 2 exemples, batches suivants = 15 autres) :
- bearish_rejection : KEEP (seul edge credible v1 PF 5.05) — batch 2 P3 done
- sweep_reclaim_n1 : NEW ICT canonique — batch 2 P3 done
- ...15 autres scenarios a implementer apres validation infrastructure
"""
from bot4_v2.decision.scenarios.bearish_rejection import BearishRejectionDetector
from bot4_v2.decision.scenarios.sweep_reclaim_n1 import SweepReclaimN1Detector

__all__ = [
    "BearishRejectionDetector",
    "SweepReclaimN1Detector",
]
