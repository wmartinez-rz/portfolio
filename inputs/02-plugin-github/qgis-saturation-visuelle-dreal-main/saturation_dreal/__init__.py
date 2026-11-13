# -*- coding: utf-8 -*-
"""
Point d'entrée du plugin QGIS - Saturation Visuelle DREAL HdF.
Fonction classFactory() requise par QGIS pour charger le plugin.
"""

def classFactory(iface):
    """
    Charge la classe SaturationDrealPlugin depuis plugin.py.
    
    :param iface: Interface QGIS (QgisInterface).
    :return: Instance du plugin.
    """
    from .plugin import SaturationDrealPlugin
    return SaturationDrealPlugin(iface)
