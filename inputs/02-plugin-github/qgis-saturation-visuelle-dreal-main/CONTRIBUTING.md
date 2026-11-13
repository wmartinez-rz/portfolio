# Contribuer

Merci de l'intérêt porté à ce projet ! Quelques règles simples avant
d'ouvrir une issue ou une pull request.

## Règle absolue : aucune donnée réelle

Ce dépôt implémente une **méthodologie publique** (guide DREAL
Hauts-de-France, février 2024). Il ne doit **jamais** contenir :

- de données d'un projet éolien réel (coordonnées, noms de parcs,
  diamètres de rotor spécifiques à un projet client) ;
- de captures d'écran, jeux de données ou fichiers de test issus d'un
  contexte professionnel ou d'un bureau d'études ;
- toute donnée couverte par un secret d'affaires ou une clause de
  confidentialité.

Les jeux de données de démonstration ou de test doivent utiliser des
coordonnées fictives ou des données ouvertes (IGN, OpenStreetMap...),
clairement identifiées comme telles.

## Environnement de développement

`math_utils.py` est du Python pur (aucune dépendance QGIS) et peut être
testé directement :

```bash
pip install pytest
pytest tests/ -v
```

Les autres modules (`algorithm.py`, `plugin.py`, `provider.py`,
`styles.py`) dépendent de `qgis.core` / `qgis.PyQt` et nécessitent une
installation QGIS (ou le [plugin QGIS Console](https://qgis.org)) pour
être testés en conditions réelles.

## Style de code

- Suivre PEP 8 dans la mesure du possible.
- Docstrings en français, cohérent avec le reste du code.
- Un commit = un changement logique, message clair
  (`feat: ...`, `fix: ...`, `docs: ...`).

## Pull requests

1. Fork + branche dédiée (`feat/ma-fonctionnalite`).
2. Vérifier que `pytest tests/` passe.
3. Décrire clairement le changement et, si pertinent, la référence au
   guide DREAL concerné (page/paragraphe).
