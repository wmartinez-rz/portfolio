# Changelog

Toutes les modifications notables de ce plugin sont documentées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/),
versionnage sémantique (MAJOR.MINOR.PATCH).

## [2.0.0] — 2025

### Ajouté
- Génération automatique des figures polaires conformes §3.4 de la
  méthodologie DREAL (4 scénarios réglementaires).
- Tableau de synthèse PNG (4 scénarios × 6 indices).
- Couche d'anneaux 0–5 km / 5–10 km avec style QGIS standardisé.
- Styles catégorisés sur la couche des secteurs (wedges) via
  `postProcessAlgorithm`.
- Nouveaux paramètres : nom du projet, dossier de sortie des figures.
- Calcul trigonométrique conditionnel du diamètre du rotor :
  - valeur globale unique, **ou**
  - champ attributaire par éolienne (prioritaire),
  - avec repli institutionnel (120 m isolée / distance centre-à-centre
    en configuration multi-mâts) si aucune valeur n'est fournie.
- Export CSV matriciel (4 lignes × 15 colonnes), compatible Excel
  Europe (séparateur `;`, encodage `utf-8-sig`, décimales à virgule).

## [1.0.0]

### Ajouté
- Version initiale conforme à la méthode DREAL Hauts-de-France
  (février 2024) : calcul des indices IOH, ID1, ID2 et IER sur
  4 scénarios réglementaires et 2 rayons (0–5 km et 5–10 km).
