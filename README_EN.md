# Palworld XGP to Steam Transfer

### Language / Langue

**[English](README_EN.md)** | **[Français](README.md)**

> This is the complete English documentation. For French documentation, open the [French README](README.md).

Windows tool for extracting Xbox Game Pass saves and automatically transferring a **Palworld PC Game Pass world to Steam**.

The Palworld transfer supports the modern Xbox `Level/01.sav` CNK/PLZ format, converts it to Steam's PLM format, and copies the world, player, and required options. A ZIP backup of the target Steam world is created before replacement.

## Safety precautions

- Back up your saves before making any changes.
- First create and save a temporary world in Palworld Steam.
- Close Palworld, Steam, and the Xbox app before transferring.
- Disable incompatible mods if Palworld reports a serialization error.
- This tool is provided without warranty. Use it at your own risk.

## Usage

1. Download the English EXE from the repository's **Releases** section.
2. Run it from the Windows account that owns the saves.
3. Choose `2. Automatically transfer Palworld from Xbox Game Pass to Steam`.
4. Select the Xbox save and then the temporary Steam world.
5. Review the summary and type `YES` to confirm.
6. Launch Palworld through Steam and load the transferred world.

Safety backups are stored in `XGP-Transfer-Backups`, next to the Steam worlds.

## Features

- generic Xbox Game Pass save extraction to ZIP files;
- manual ZIP import into a Steam save folder;
- detection of Palworld Xbox worlds, including `Slot1`, `Slot2`, and `Slot3`;
- CNK/PLZ to PLM conversion with post-conversion verification;
- transfer of `Level.sav`, `LevelMeta.sav`, `LocalData.sav`, `WorldOption.sav`, and `Players`;
- automatic backups and atomic writes to reduce corruption risk;
- separate French and English command-line interfaces.

## Download verification

The official SHA-256 hash for each EXE is listed in its GitHub Release. In PowerShell:

```powershell
Get-FileHash .\palworld-xbox-to-steam-en.exe -Algorithm SHA256
```

## Running from source

The script requires Python 3. Modern Palworld conversion uses the `palsav-flex` and `palooz` modules from [PalworldSaveTools](https://github.com/deafdudecomputers/PalworldSaveTools).

```powershell
python main_en.py
python main_en.py --test-palworld
```

## Credits and license

This project is based on [Z1ni/XGP-save-extractor](https://github.com/Z1ni/XGP-save-extractor), distributed under the MIT License. Palworld save conversion uses work from [PalworldSaveTools](https://github.com/deafdudecomputers/PalworldSaveTools).

The original MIT notice is preserved in [LICENSE](LICENSE), and the PalworldSaveTools notice is preserved in [LICENSE-PalworldSaveTools](LICENSE-PalworldSaveTools). Palworld is a trademark of Pocketpair, Inc. This community project is not affiliated with Pocketpair, Microsoft, or Valve.
