# -*- coding: utf-8 -*-
"""
provider.py - Fournisseur de traitements QGIS (QgsProcessingProvider).
Déclare les métadonnées du groupe d'algorithmes et enregistre
l'algorithme de saturation visuelle DREAL.
"""

import os
from qgis.core import QgsProcessingProvider
from .algorithm import SaturationDrealAlgorithm


class SaturationDrealProvider(QgsProcessingProvider):
    """
    Fournisseur de traitements pour la saturation visuelle éolienne
    selon la méthode DREAL Hauts-de-France.

    Apparaît dans la Boîte à outils de traitements QGIS sous
    le groupe "Saturation Visuelle DREAL HdF".
    """

    # Identifiant unique du fournisseur (minuscules, sans espaces)
    PROVIDER_ID = "saturation_dreal"

    def __init__(self):
        super().__init__()

    def loadAlgorithms(self):
        """
        Enregistre tous les algorithmes fournis par ce provider.
        Appelé automatiquement par QGIS lors du chargement.
        """
        self.addAlgorithm(SaturationDrealAlgorithm())

    def id(self):
        """
        Retourne l'identifiant unique du fournisseur.
        Utilisé en interne par QGIS Processing.
        """
        return self.PROVIDER_ID

    def name(self):
        """
        Nom affiché dans la boîte à outils de traitements.
        """
        return "Saturation Visuelle DREAL HdF"

    def longName(self):
        """
        Nom long optionnel pour la description complète du fournisseur.
        """
        return "Saturation Visuelle Éolienne — Méthode DREAL Hauts-de-France (fév. 2024)"

    def icon(self):
        """
        Icône du fournisseur dans la boîte à outils.
        Retourne l'icône par défaut si aucun fichier icon.png n'existe.
        """
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            from qgis.PyQt.QtGui import QIcon
            return QIcon(icon_path)
        return super().icon()

    def svgIconPath(self):
        """
        Chemin vers une icône SVG alternative (optionnel).
        """
        return None
