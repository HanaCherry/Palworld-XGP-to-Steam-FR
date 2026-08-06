# Palworld XGP vers Steam FR

English documentation: [README_EN.md](README_EN.md)

Outil Windows en français pour extraire des sauvegardes Xbox Game Pass et transférer automatiquement un monde **Palworld PC Game Pass vers Steam**.

Le transfert Palworld prend en charge le format moderne Xbox `Level/01.sav` (CNK/PLZ), le convertit au format Steam PLM et copie le monde, le personnage et les options nécessaires. Une sauvegarde ZIP du monde Steam est créée avant chaque remplacement.

## Précautions

- Faites une copie de vos sauvegardes avant toute manipulation.
- Créez et sauvegardez d'abord un monde temporaire dans Palworld Steam.
- Fermez Palworld, Steam et l'application Xbox avant le transfert.
- Désactivez les mods incompatibles si Palworld affiche une erreur de sérialisation.
- L'outil est fourni sans garantie. Utilisez-le à vos risques et périls.

## Utilisation

1. Téléchargez l'EXE français ou anglais depuis la section **Releases** du dépôt.
2. Lancez-le sous le compte Windows qui possède les sauvegardes.
3. Choisissez `2. Transférer automatiquement Palworld de Xbox Game Pass vers Steam`.
4. Sélectionnez la sauvegarde Xbox puis le monde Steam temporaire.
5. Vérifiez le récapitulatif et confirmez le transfert.
6. Lancez Palworld depuis Steam et chargez le monde transféré.

Les sauvegardes de sécurité sont placées dans `XGP-Transfer-Backups`, à côté des mondes Steam.

## Fonctions

- extraction générique des sauvegardes Xbox Game Pass en ZIP ;
- import manuel d'un ZIP vers un dossier Steam ;
- détection des mondes Palworld Xbox, y compris `Slot1`, `Slot2` et `Slot3` ;
- conversion CNK/PLZ vers PLM avec vérification après conversion ;
- transfert de `Level.sav`, `LevelMeta.sav`, `LocalData.sav`, `WorldOption.sav` et `Players` ;
- sauvegarde automatique et écritures atomiques pour limiter le risque de corruption ;
- interface et messages d'erreur en français.

## Vérifier le téléchargement

Le SHA-256 officiel de chaque EXE est indiqué dans la Release correspondante. Sous PowerShell :

```powershell
Get-FileHash .\palworld-xbox-vers-steam-fr.exe -Algorithm SHA256
```

## Exécuter depuis le code source

Le script utilise Python 3 et, pour la conversion Palworld moderne, les modules `palsav-flex` et `palooz` issus de [PalworldSaveTools](https://github.com/deafdudecomputers/PalworldSaveTools).

```powershell
python main.py
```

Le test intégré du moteur de conversion peut être lancé avec :

```powershell
python main.py --test-palworld
```

La version anglaise utilise `main_en.py` et accepte `YES` pour les confirmations.

## Crédits et licence

Ce projet est une adaptation de [Z1ni/XGP-save-extractor](https://github.com/Z1ni/XGP-save-extractor), distribué sous licence MIT. La conversion des sauvegardes Palworld repose sur le travail du projet [PalworldSaveTools](https://github.com/deafdudecomputers/PalworldSaveTools).

La notice MIT d'origine est conservée dans [LICENSE](LICENSE). Palworld est une marque de Pocketpair, Inc. Ce projet communautaire n'est affilié ni à Pocketpair, ni à Microsoft, ni à Valve.
