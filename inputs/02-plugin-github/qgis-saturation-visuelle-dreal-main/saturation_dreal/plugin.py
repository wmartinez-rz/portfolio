# -*- coding: utf-8 -*-
"""
plugin.py - Initialisation du plugin Saturation Visuelle DREAL HdF.
Gère le cycle de vie du plugin : initGui, unload et enregistrement
du Processing Provider auprès du registre QGIS.
"""

from qgis.core import QgsApplication
from .provider import SaturationDrealProvider


class SaturationDrealPlugin:
    """
    Classe principale du plugin.
    Instanciée par classFactory() lors du chargement par QGIS.
    """

    def __init__(self, iface):
        """
        Constructeur.

        :param iface: Référence à l'interface QGIS (QgisInterface).
        """
        self.iface = iface
        self.provider = None

    def initProcessing(self):
        """
        Crée et enregistre le fournisseur de traitements (Processing Provider)
        dans le registre de traitement de QGIS.
        Appelé par initGui() et potentiellement par QGIS en mode headless.
        """
        self.provider = SaturationDrealProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        """
        Appelé par QGIS lors du chargement du plugin dans l'interface graphique.
        Enregistre le Processing Provider.
        """
        self.initProcessing()

    def unload(self):
        """
        Appelé par QGIS lors du déchargement du plugin.
        Supprime le Processing Provider du registre pour nettoyer proprement.
        """
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
