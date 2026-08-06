import gzip
import json
import os
import shutil
import struct
import sys
import tempfile
import traceback
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePath
from typing import Any, Dict, List, Tuple

# Xbox Game Pass for PC savefile extractor

# Running: Just run the script with Python 3 to create ZIP files that contain the save files

# Thanks to @snoozbuster for figuring out the container format at https://github.com/goatfungus/NMSSaveEditor/issues/306

filetime_epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
packages_root = Path(os.path.expandvars(f"%LOCALAPPDATA%\\Packages"))


def read_game_list() -> Dict[str, Any] | None:
    try:
        # Search for the games JSON in the script directory
        games_json_path = Path("games.json")
        if not games_json_path.exists():
            # Search for the games JSON in the bundle directory
            games_json_path = Path(__file__).resolve().with_name("games.json")
        if not games_json_path.exists():
            return None
        with games_json_path.open("r") as f:
            without_comments = "\n".join(
                [l for l in f.readlines() if not l.lstrip().startswith("//")]
            )
        j = json.loads(without_comments)
        # Create a dict with the package name as the key
        games: Dict[str, Any] = {}
        for entry in j["games"]:
            games[entry["package"]] = {
                "name": entry["name"],
                "handler": entry["handler"],
                "handler_args": entry.get("handler_args") or {}
            }
        return games
    except:
        return None


def discover_games(supported_games: Dict[str, Any]) -> List[str]:
    found_games = []
    for pkg_name in supported_games.keys():
        pkg_path = packages_root / pkg_name
        if pkg_path.exists():
            found_games.append(pkg_name)
    return found_games


def read_utf16_str(f, str_len=None) -> str:
    if not str_len:
        str_len = struct.unpack("<i", f.read(4))[0]
    return f.read(str_len * 2).decode("utf-16").rstrip("\0")


def read_filetime(f) -> datetime:
    filetime = struct.unpack("<Q", f.read(8))[0]
    filetime_seconds = filetime / 10_000_000
    return filetime_epoch + timedelta(seconds=filetime_seconds)


def print_sync_warning(title: str):
    print()
    print(f"  !! {title} !!")
    print("     Xbox Cloud synchronization may not be complete.")
    print("     The extracted saves for this game may be corrupted!")
    print("     Press Enter to ignore this warning and continue.")
    input()


def get_xbox_user_name(user_id: int) -> str | None:
    xbox_app_package = "Microsoft.XboxApp_8wekyb3d8bbwe"
    try:
        live_gamer_path = (
            packages_root / xbox_app_package / "LocalState/XboxLiveGamer.xml"
        )
        with live_gamer_path.open("r", encoding="utf-8") as f:
            gamer = json.load(f)
        known_user_id = gamer.get("XboxUserId")
        if known_user_id != user_id:
            return None
        return gamer.get("Gamertag")
    except:
        return None


def find_user_containers(pkg_name: str) -> List[Tuple[int | str, Path]]:
    # Find container dir
    wgs_dir = packages_root / pkg_name / "SystemAppData/wgs"
    if not wgs_dir.is_dir():
        return []
    # Get the correct user directory
    has_backups = False
    valid_user_dirs = []
    for entry in wgs_dir.iterdir():
        if not entry.is_dir():
            continue
        if entry.name == "t":
            continue
        if "backup" in entry.name:
            has_backups = True
            continue
        if len(entry.name.split("_")) == 2:
            valid_user_dirs.append(entry)

    if has_backups:
        print("  !! The save folder contains backup copies!  !!")
        print("     Backup copies created by the Xbox app will be ignored.")
        print("     Press Enter to continue.")
        input()

    if len(valid_user_dirs) == 0:
        # No saves for any users
        return []

    user_dirs = []

    for valid_user_dir in valid_user_dirs:
        user_id_hex, title_id_hex = valid_user_dir.name.split("_", 1)
        user_id = int(user_id_hex, 16)
        user_name = get_xbox_user_name(user_id)
        user_dirs.append((user_name or user_id, valid_user_dir))

    return user_dirs


def read_user_containers(user_wgs_dir: Path) -> Tuple[str, List[Dict[str, Any]]]:
    containers_dir = user_wgs_dir
    containers_idx_path = containers_dir / "containers.index"

    containers = []

    # Read the index file
    with containers_idx_path.open("rb") as f:
        # Unknown
        f.read(4)

        container_count = struct.unpack("<i", f.read(4))[0]

        # Package display name seems to be available only on console saves
        pkg_display_name = read_utf16_str(f)

        store_pkg_name = read_utf16_str(f).split("!")[0]

        # Creation date, FILETIME
        creation_date = read_filetime(f)
        # print(f"  Container index created at {creation_date}")
        # Unknown
        f.read(4)
        read_utf16_str(f)

        # Unknown
        f.read(8)

        for _ in range(container_count):
            # Container name
            container_name = read_utf16_str(f)
            # Duplicate of the file name
            read_utf16_str(f)
            # Unknown quoted hex number
            read_utf16_str(f)
            # Container number
            container_num = struct.unpack("B", f.read(1))[0]
            # Unknown
            f.read(4)
            # Read container (folder) GUID
            container_guid = uuid.UUID(bytes_le=f.read(16))
            # Creation date, FILETIME
            container_creation_date = read_filetime(f)
            # print(f"Container created at {container_creation_date}")
            # Unknown
            f.read(16)

            files = []

            # Read the container file in the container directory
            container_path = containers_dir / container_guid.hex.upper()
            container_file_path = container_path / f"container.{container_num}"

            if not container_file_path.is_file():
                print_sync_warning(f'Missing container "{container_name}"')
                continue

            with container_file_path.open("rb") as cf:
                # Unknown (always 04 00 00 00 ?)
                cf.read(4)
                # Number of files in this container
                file_count = struct.unpack("<i", cf.read(4))[0]
                for _ in range(file_count):
                    # File name, 0x80 (128) bytes UTF-16 = 64 characters
                    file_name = read_utf16_str(cf, 64)
                    # Read file GUID
                    file_guid = uuid.UUID(bytes_le=cf.read(16))
                    # Read the copy of the GUID
                    file_guid_2 = uuid.UUID(bytes_le=cf.read(16))

                    if file_guid == file_guid_2:
                        file_path = container_path / file_guid.hex.upper()
                    else:
                        # Check if one of the file paths exist
                        file_guid_1_path = container_path / file_guid.hex.upper()
                        file_guid_2_path = container_path / file_guid_2.hex.upper()

                        file_1_exists = file_guid_1_path.is_file()
                        file_2_exists = file_guid_2_path.is_file()

                        if file_1_exists and not file_2_exists:
                            file_path = file_guid_1_path
                        elif not file_1_exists and file_2_exists:
                            file_path = file_guid_2_path
                        elif file_1_exists and file_2_exists:
                            # Which one to use?
                            print_sync_warning(
                                f'Two files exist for container "{container_name}" file "{file_name}": {file_guid} and {file_guid_2}, can\'t choose one'
                            )
                            continue
                        else:
                            print_sync_warning(
                                f'Missing file "{file_name}" inside container "{container_name}"'
                            )
                            continue

                    files.append(
                        {
                            "name": file_name,
                            # "guid": file_guid,
                            "path": file_path,
                        }
                    )

            containers.append(
                {
                    "name": container_name,
                    "number": container_num,
                    # "guid": container_guid,
                    "files": files,
                }
            )

    return (store_pkg_name, containers)


def get_save_paths(
    supported_games: Dict[str, Any],
    store_pkg_name: str,
    containers: List[Dict[str, Any]],
    temp_dir: tempfile.TemporaryDirectory,
) -> List[Tuple[str, Path]]:
    save_meta = []

    handler_name = supported_games[store_pkg_name]["handler"]
    handler_args = supported_games[store_pkg_name].get("handler_args") or {}

    if handler_name == "1c1f":
        # "1 container, 1 file" (1c1f). Each container contains only one file which name will be the name of the container.
        file_suffix = handler_args.get("suffix")
        for container in containers:
            fname = container["name"]
            if file_suffix is not None:
                # Add a suffix to the file name if configured
                fname += file_suffix
            fpath = container["files"][0]["path"]
            save_meta.append((fname, fpath))

    elif handler_name == "1cnf":
        # "1 container, n files" (1cnf). There's only one container that contains all the savefiles.
        file_suffix = handler_args.get("suffix")
        container = containers[0]
        for c_file in container["files"]:
            final_filename = c_file["name"]
            if file_suffix is not None:
                # Add a suffix to the file name if configured
                final_filename += file_suffix
            save_meta.append((final_filename, c_file["path"]))

    elif handler_name == "1cnf-folder":
        # Each container represents one folder
        for container in containers:
            folder_name: str = container["name"]
            for file in container["files"]:
                fname = file["name"]
                zip_fname = f"{folder_name}/{fname}"
                fpath = file["path"]
                save_meta.append((zip_fname, fpath))

    elif handler_name == "control":
        # Handle Control saves
        # Control uses container in a "n containers, n files" manner (ncnf),
        # where the container represents a folder that has named files.
        # Epic Games Store (and Steam?) use the same file names, but with a ".chunk" file extension.
        # TODO: Are files named "meta" unnecessary?
        for container in containers:
            path = PurePath(container["name"])

            # Create "--containerDisplayName.chunk" that contains the container name
            # TODO: Does Control _need_ "--containerDisplayName.chunk"?
            temp_container_disp_name_path = (
                Path(temp_dir.name)
                / f"{container['name']}_--containerDisplayName.chunk"
            )
            with temp_container_disp_name_path.open("w") as f:
                f.write(container["name"])
            save_meta.append(
                (path / "--containerDisplayName.chunk", temp_container_disp_name_path)
            )

            for file in container["files"]:
                save_meta.append((path / f"{file['name']}.chunk", file["path"]))

    elif handler_name == "starfield":
        # Starfield
        # The Steam version uses SFS ("Starfield save"?) files, whereas the Store version splits the SFS files into multiple files inside the containers.
        # One container is one save.
        # It seems that the "BETHESDAPFH" file is a header which is padded to the next 16 byte boundary with the string "padding\0", where \0 is NUL.
        # The other files ("PnP", where n is a number starting from 0) are then concatenated into the SFS file, also with padding.

        # As of at least Starfield version 1.9.51.0, the containers contain "toc" and one or more "BlobDataN" files (where N is a number starting from 0).
        # The new format seems to already include the padding.

        temp_folder = Path(temp_dir.name) / "Starfield"
        temp_folder.mkdir()

        pad_str = "padding\0" * 2

        for container in containers:
            path = PurePath(container["name"])
            # There can be other files than saves, e.g. files under "Settings/" path. Skip those.
            if path.parent.name != "Saves":
                continue
            # Strip out the parent folder name
            sfs_name = path.name
            # Arrange the files: header as index 0, P0P as 1, P1P as 2, etc. (or BlobData0, ... for the new format)
            parts = {}

            is_new_format = "toc" in [f["name"] for f in container["files"]]

            for file in container["files"]:
                if file["name"] == "toc":
                    continue
                if is_new_format:
                    idx = int(file["name"].removeprefix("BlobData"))
                else:
                    if file["name"] == "BETHESDAPFH":
                        idx = 0
                    else:
                        idx = int(file["name"].strip("P")) + 1
                parts[idx] = file["path"]

            # Construct the SFS file
            sfs_path = temp_folder / sfs_name
            with sfs_path.open("wb") as sfs_f:
                for idx, part_path in sorted(parts.items(), key=lambda t: t[0]):
                    with open(part_path, "rb") as part_f:
                        data = part_f.read()
                    size = sfs_f.write(data)
                    pad = 16 - (size % 16)
                    if pad != 16:
                        sfs_f.write(pad_str[:pad].encode("ascii"))

            save_meta.append((sfs_name, sfs_path))

    elif handler_name == "lies-of-p":
        # Lies of P
        for container in containers:
            fname: str = container["name"]
            # Lies of P prefixes the save file names with a numeric ID
            # Filter the numbers out
            for i, c in enumerate(fname):
                if c.isdigit():
                    continue
                fname = fname[i:]
                break

            # The names also need a ".sav" suffix
            fname += ".sav"
            fpath = container["files"][0]["path"]

            save_meta.append((fname, fpath))

    elif handler_name == "palworld":
        for container in containers:
            fname = container["name"]
            # Each "-" in the name is a directory separator
            fname = fname.replace("-", "/")
            fname += ".sav"
            fpath = container["files"][0]["path"]
            save_meta.append((fname, fpath))

    elif handler_name == "like-a-dragon":
        for container in containers:
            path = PurePath(container["name"])
            if path.name == "datasav":
                fpath = path.with_name("data.sav")
            elif path.name == "datasys":
                fpath = path.with_name("data.sys")
            else:
                fpath = path

            for file in container["files"]:
                if file["name"].lower() == "data":
                    save_meta.append((str(fpath), file["path"]))
                elif file["name"].lower() == "icon":
                    icon_format = handler_args.get("icon_format")
                    if icon_format is None:
                        continue
                    save_meta.append(
                        (
                            str(
                                fpath.with_name(
                                    f"{fpath.parent.name}_icon.{icon_format}"
                                )
                            ),
                            file["path"],
                        )
                    )

    elif handler_name == "cricket-24":
        # 1cnf-folder, but with a file suffix and "CHUNK" suffix removal
        # TODO: Can there be more than one chunk?
        # Each container represents one folder
        for container in containers:
            folder_name: str = container["name"]
            for file in container["files"]:
                fname = file["name"]
                fname = fname.removesuffix(".CHUNK0")
                if "CHUNK" in fname:
                    raise Exception(
                        f"Nom de segment inattendu dans {file['name']} ! Signalez ce problème sur le dépôt GitHub."
                    )
                fname += ".SAV"
                zip_fname = f"{folder_name}/{fname}"
                fpath = file["path"]
                save_meta.append((zip_fname, fpath))

    elif handler_name == "forza":
        # Container name is the filename prefix, file names inside container are appended to that after "."
        for container in containers:
            for file in container["files"]:
                fname = f"{container['name']}.{file['name']}"
                save_meta.append((fname, file["path"]))

    elif handler_name == "arcade-paradise":
        # Arcade Paradise seems to save to one container with one file, which should be renamed to "RATSaveData.dat" for Steam
        fpath = containers[0]["files"][0]["path"]
        save_meta.append(("RATSaveData.dat", fpath))

    elif handler_name == "state-of-decay-2":
        # This is otherwise identical to 1cnf, but we ignore the path in the file names
        for file in containers[0]["files"]:
            fname = file["name"].split("/")[-1] + ".sav"
            save_meta.append((fname, file["path"]))

    elif handler_name == "railway-empire-2":
        # Each container is one file.
        # The files inside the container are "savegame" and "description". It seems that we can ignore "description".
        for container in containers:
            for file in container["files"]:
                if file["name"] != "savegame":
                    continue
                save_meta.append((container["name"], file["path"]))

    elif handler_name == "coral-island":
        # 1c1f with ".sav" suffix, but if the file name is prefixed with "Backup", we place it in a folder
        # without the prefix.
        for container in containers:
            fname = f"{container['name']}.sav"
            if fname.startswith("Backup"):
                fname = f"Backup/{fname.removeprefix('Backup')}"
            fpath = container["files"][0]["path"]
            save_meta.append((fname, fpath))

    elif handler_name == "one-lonely-outpost":
        # One Lonely Outpost on game pass stores its data in a single gzipped JSON file that
        # contains all the individual files from the Steam version, so decompress it and extract
        # the individual files
        temp_folder = Path(temp_dir.name) / "OneLonelyOutpost"
        temp_folder.mkdir()

        container = containers[0]

        with container["files"][0]["path"].open("rb") as f:
            json_data = gzip.decompress(f.read())

        data = json.loads(json_data)

        for file in data["files"]["$values"]:
            # The file names are prefixed with "ConsoleSaves/", so nix that
            fname = file["name"].removeprefix("ConsoleSaves/")

            fpath = temp_folder / fname
            fpath.parent.mkdir(parents=True, exist_ok=True)
            with fpath.open("w") as out_f:
                out_f.write(file["datas"]["$values"][0])

            save_meta.append((fname, fpath))

    else:
        raise Exception('Unsupported Xbox Game Pass application : "%s"' % store_pkg_name)

    return save_meta


def clean_user_path(value: str) -> Path:
    """Accept paths pasted with or without surrounding quotes."""
    return Path(os.path.expandvars(value.strip().strip('"').strip("'"))).expanduser()


def safe_zip_members(save_zip: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    """Return regular archive members and reject paths escaping the destination."""
    members = []
    for member in save_zip.infolist():
        member_path = PurePath(member.filename.replace("\\", "/"))
        if member.is_dir():
            continue
        if (
            member_path.is_absolute()
            or not member_path.parts
            or ".." in member_path.parts
            or member_path.parts[0].endswith(":")
        ):
            raise ValueError(f'Unsafe path in archive: "{member.filename}"')

        # ZIP stores Unix file type bits in the upper portion of external_attr.
        # Refuse symbolic links instead of following or materializing them.
        unix_file_type = (member.external_attr >> 16) & 0o170000
        if unix_file_type == 0o120000:
            raise ValueError(f'Symbolic link rejected : "{member.filename}"')
        members.append(member)
    return members


def install_save_archive(archive_path: Path, destination: Path) -> Path | None:
    """Copy an extracted Xbox save archive into a Steam save directory safely."""
    archive_path = archive_path.resolve()
    destination = destination.resolve()

    if not archive_path.is_file():
        raise FileNotFoundError(f'Archive not found : "{archive_path}"')
    if archive_path.suffix.lower() != ".zip":
        raise ValueError("The selected save archive must be a ZIP file.")

    with zipfile.ZipFile(archive_path, "r") as save_zip:
        bad_member = save_zip.testzip()
        if bad_member is not None:
            raise ValueError(f'Corrupted file in archive: "{bad_member}"')
        members = safe_zip_members(save_zip)
        if not members:
            raise ValueError("The selected archive contains no save files.")

        print()
        print(f'Archive: "{archive_path}"')
        print(f'Steam save folder : "{destination}"')
        print("Files to copy :")
        for member in members:
            target = destination.joinpath(*PurePath(member.filename.replace("\\", "/")).parts)
            action = "replace" if target.exists() else "create"
            print(f"- {member.filename} ({action})")

        print()
        answer = input("Continue the import? Type YES to confirm: ").strip()
        if answer.upper() != "YES":
            print("Import cancelled. No files were changed.")
            return None

        destination.mkdir(parents=True, exist_ok=True)
        existing = []
        for member in members:
            relative = PurePath(member.filename.replace("\\", "/"))
            target = destination.joinpath(*relative.parts)
            if target.is_file():
                existing.append((relative, target))

        backup_path = None
        if existing:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
            backup_path = archive_path.with_name(f"steam_save_backup_{timestamp}.zip")
            counter = 1
            while backup_path.exists():
                backup_path = archive_path.with_name(
                    f"steam_save_backup_{timestamp}_{counter}.zip"
                )
                counter += 1
            with zipfile.ZipFile(backup_path, "x", zipfile.ZIP_DEFLATED) as backup_zip:
                for relative, target in existing:
                    backup_zip.write(target, arcname=str(relative).replace("\\", "/"))

        for member in members:
            relative = PurePath(member.filename.replace("\\", "/"))
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with save_zip.open(member, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    print()
    print(f"Import complete : {len(members)} file(s) copied.")
    if backup_path is not None:
        print(f'Previous Steam files backed up to "{backup_path}"')
    return backup_path


def import_saves_to_steam():
    print("Import an extracted Xbox save into a Steam game")
    print("========================================================")
    print("Close both the Xbox and Steam versions of the game before continuing.")
    print("Otherwise, Steam Cloud may restore an older save.")
    print()
    archive_path = clean_user_path(input("Path to the extracted Xbox ZIP: "))
    destination = clean_user_path(input("Path to the Steam save folder: "))
    install_save_archive(archive_path, destination)


def choose_number(title: str, choices: List[Tuple[str, Any]]) -> Any:
    if not choices:
        raise ValueError(f"No items available : {title}")
    print(title)
    for index, (label, _) in enumerate(choices, 1):
        print(f"{index}. {label}")
    while True:
        answer = input("Your choice: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1][1]
        print("Invalid choice.")


def latest_file_date(files: List[Tuple[PurePath, Path]]) -> datetime:
    timestamps = [source.stat().st_mtime for _, source in files if source.exists()]
    return datetime.fromtimestamp(max(timestamps))


def find_steam_palworld_worlds() -> List[Tuple[Path, Path]]:
    save_root = Path(os.path.expandvars("%LOCALAPPDATA%")) / "Pal/Saved/SaveGames"
    if not save_root.is_dir():
        return []
    worlds = []
    for account_dir in save_root.iterdir():
        if not account_dir.is_dir():
            continue
        for world_dir in account_dir.iterdir():
            if world_dir.is_dir() and (world_dir / "Level.sav").is_file():
                worlds.append((account_dir, world_dir))
    return worlds


def backup_palworld_target(account_dir: Path, world_dir: Path) -> Path:
    backup_root = account_dir / "XGP-Transfer-Backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
    backup_path = backup_root / f"palworld_steam_{world_dir.name}_{timestamp}.zip"
    counter = 1
    while backup_path.exists():
        backup_path = backup_root / (
            f"palworld_steam_{world_dir.name}_{timestamp}_{counter}.zip"
        )
        counter += 1

    with zipfile.ZipFile(backup_path, "x", zipfile.ZIP_DEFLATED) as backup_zip:
        for account_file_name in ("UserOption.sav", "GlobalPalStorage.sav"):
            account_file = account_dir / account_file_name
            if account_file.is_file():
                backup_zip.write(account_file, arcname=account_file_name)
        for file_path in world_dir.rglob("*"):
            if file_path.is_file():
                backup_zip.write(
                    file_path,
                    arcname=f"{world_dir.name}/{file_path.relative_to(world_dir)}",
                )
    return backup_path


def copy_palworld_world(
    source_files: List[Tuple[PurePath, Path]],
    root_files: List[Tuple[PurePath, Path]],
    account_dir: Path,
    world_dir: Path,
) -> Path:
    backup_path = backup_palworld_target(account_dir, world_dir)

    # A failed/old transfer may have left the segmented Xbox Level directory in
    # the Steam world. Move it out after it has been included in the ZIP backup,
    # otherwise Palworld can prefer Level/01.sav over the converted Level.sav.
    segmented_level = world_dir / "Level"
    if segmented_level.is_dir():
        retired_root = account_dir / "XGP-Transfer-Backups"
        timestamp = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
        retired = retired_root / f"old_Level_{world_dir.name}_{timestamp}"
        counter = 1
        while retired.exists():
            retired = retired_root / (
                f"old_Level_{world_dir.name}_{timestamp}_{counter}"
            )
            counter += 1
        shutil.move(str(segmented_level), str(retired))

    for relative, source in source_files:
        target = world_dir.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_palworld_steam_file(source, target)

    for relative, source in root_files:
        write_palworld_steam_file(source, account_dir / relative.name)

    return backup_path


def convert_palworld_data_for_steam(data: bytes) -> bytes:
    """Convert Game Pass compression (CNK/PLZ) to Steam compression (PLM)."""
    if data[:4] == b"GVAS" or data[8:11] == b"PlM":
        return data
    if data[8:11] not in (b"CNK", b"PlZ"):
        raise ValueError(
            f"Format Palworld inconnu : en-tête {data[:12].hex()}"
        )

    from palsav.core import decompress_sav_to_gvas, compress_gvas_to_sav

    raw_gvas, _ = decompress_sav_to_gvas(data)
    converted = compress_gvas_to_sav(raw_gvas, 49)
    verified_gvas, _ = decompress_sav_to_gvas(converted)
    if converted[8:11] != b"PlM" or verified_gvas != raw_gvas:
        raise ValueError("Xbox-to-Steam conversion verification failed.")
    return converted


def write_palworld_steam_file(source: Path, target: Path) -> None:
    converted = convert_palworld_data_for_steam(source.read_bytes())
    temporary = target.with_name(f".{target.name}.xgp-transfer.tmp")
    with temporary.open("wb") as output:
        output.write(converted)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, target)


def group_palworld_worlds(
    converted_paths: List[Tuple[PurePath, Path]],
) -> Tuple[List[Tuple[PurePath, Path]], Dict[str, List[Tuple[PurePath, Path]]]]:
    account_file_names = {"useroption.sav", "globalpalstorage.sav"}
    root_files = [
        (relative, source)
        for relative, source in converted_paths
        if len(relative.parts) == 1 and relative.name.lower() in account_file_names
    ]
    world_roots = []
    for relative, _ in converted_paths:
        if relative.name.lower() == "level.sav":
            world_root = relative.parent
        elif (
            len(relative.parts) >= 2
            and relative.parts[-2].lower() == "level"
            and relative.name.lower() == "01.sav"
        ):
            world_root = relative.parent.parent
        else:
            continue
        if world_root not in world_roots:
            world_roots.append(world_root)

    xbox_worlds: Dict[str, List[Tuple[PurePath, Path]]] = {}
    for world_root in world_roots:
        files = []
        for relative, source in converted_paths:
            if relative in [path for path, _ in root_files]:
                continue
            if world_root.parts:
                if not relative.is_relative_to(world_root):
                    continue
                target_relative = relative.relative_to(world_root)
            else:
                target_relative = relative

            # Do not mix Slot1/Slot2/Slot3 recovery points into the active world.
            belongs_to_nested_world = any(
                other_root != world_root
                and len(other_root.parts) > len(world_root.parts)
                and other_root.is_relative_to(world_root)
                and relative.is_relative_to(other_root)
                for other_root in world_roots
            )
            if belongs_to_nested_world:
                continue

            # Recent Game Pass saves store the actual Level.sav as Level/01.sav.
            if (
                len(target_relative.parts) == 2
                and target_relative.parts[0].lower() == "level"
                and target_relative.name.lower() == "01.sav"
            ):
                target_relative = PurePath("Level.sav")
            files.append((target_relative, source))
        world_label = "/".join(world_root.parts) or "main save"
        if world_root.name.lower().startswith("slot"):
            world_label += " (point de restauration)"
        xbox_worlds[world_label] = files
    return root_files, xbox_worlds


def transfer_palworld_xbox_to_steam():
    print("Automatic Palworld transfer: Xbox Game Pass to Steam")
    print("==========================================================")
    print("Before continuing:")
    print("- create and save a temporary world in the Steam version;")
    print("- completely close Palworld, the Xbox app, and Steam.")
    print()

    games = read_game_list()
    package_name = "PocketpairInc.Palworld_ad4psfrxyesvt"
    if games is None or package_name not in games:
        raise ValueError("The Palworld configuration is missing from games.json.")

    xbox_users = find_user_containers(package_name)
    if not xbox_users:
        raise FileNotFoundError("No Palworld Xbox Game Pass save was found.")
    if len(xbox_users) > 1:
        xbox_user = choose_number(
            "Select the Xbox profile:",
            [(str(user), (user, path)) for user, path in xbox_users],
        )
    else:
        xbox_user = xbox_users[0]

    xbox_user_name, container_dir = xbox_user
    store_pkg_name, containers = read_user_containers(container_dir)
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        save_paths = get_save_paths(games, store_pkg_name, containers, temp_dir)
        converted_paths = [
            (PurePath(file_name.replace("\\", "/")), source)
            for file_name, source in save_paths
        ]
        # Un monde est identifié par son Level.sav. Son dossier parent peut être
        # l'identifiant Xbox, mais certaines versions stockent les fichiers à la racine
        # ou ajoutent un niveau de dossier supplémentaire.
        root_files, xbox_worlds = group_palworld_worlds(converted_paths)

        if not xbox_worlds:
            print("Detected Xbox files:")
            for relative, _ in converted_paths:
                print(f"- {relative}")
            raise ValueError(
                "No Level.sav or Level/01.sav file was found. Xbox Cloud synchronization "
                "may be incomplete: launch Palworld through Xbox, load the world, "
                "exit the game normally, and try again after a few minutes."
            )

        xbox_choices = []
        for world_id, files in xbox_worlds.items():
            modified = latest_file_date(files).strftime("%d/%m/%Y à %H:%M:%S")
            xbox_choices.append(
                (f"World {world_id} — last save: {modified}", (world_id, files))
            )
        if len(xbox_choices) == 1:
            xbox_world_id, source_files = xbox_choices[0][1]
            print(f"Detected Xbox world: {xbox_choices[0][0]}")
        else:
            xbox_world_id, source_files = choose_number(
                "Select the Xbox world to transfer:", xbox_choices
            )

        steam_worlds = find_steam_palworld_worlds()
        if not steam_worlds:
            raise FileNotFoundError(
                "No Steam world was found. Launch Palworld on Steam, create and save a world, "
                "then close the game."
            )
        steam_choices = []
        for account_dir, world_dir in steam_worlds:
            modified = datetime.fromtimestamp(
                (world_dir / "Level.sav").stat().st_mtime
            ).strftime("%d/%m/%Y à %H:%M:%S")
            steam_choices.append(
                (
                    f"Account {account_dir.name}, world {world_dir.name} — {modified}",
                    (account_dir, world_dir),
                )
            )
        account_dir, world_dir = choose_number(
            "Select the temporary Steam world to replace:", steam_choices
        )

        print()
        print(f"Xbox profile: {xbox_user_name}")
        print(f"World Xbox source : {xbox_world_id}")
        print(f"Target Steam world: {world_dir}")
        print("World files that will be replaced:")
        for relative, _ in source_files:
            print(f"- {relative}")
        for relative, _ in root_files:
            print(f"- {relative.name}")
        print()
        answer = input("Type YES to start the transfer: ").strip().upper()
        if answer != "YES":
            print("Transfer cancelled. No files were changed.")
            return

        backup_path = copy_palworld_world(
            source_files, root_files, account_dir, world_dir
        )
        print()
        print("Palworld transfer complete.")
        print(f'Safety backup created at: "{backup_path}"')
        print("You can now launch Palworld on Steam.")
        print("If Steam Cloud asks which save to keep, choose the local files.")
    finally:
        temp_dir.cleanup()


def extract_xbox_saves():
    print("Xbox Game Pass save extractor for PC")
    print("=================================================")

    games = read_game_list()
    if games is None:
        print("Unable to read the game list. Check the games.json file.")
        print()
        print("Press Enter to exit")
        input()
        sys.exit(1)

    # Discover supported games
    found_games = discover_games(games)

    if len(found_games) == 0:
        print("No supported game is installed")
        print()
        print("Press Enter to exit")
        input()
        sys.exit(1)

    print("Installed supported games:")
    for package_name in found_games:
        name: str = games[package_name]["name"]
        print("- %s" % name)

        try:
            user_containers = find_user_containers(package_name)
            if len(user_containers) == 0:
                print(
                    "  No save was found; the game may no longer be installed"
                )
                print()
                continue

            for xbox_username_or_id, container_dir in user_containers:
                read_result = read_user_containers(container_dir)
                store_pkg_name, containers = read_result

                # Create tempfile directory
                # Some save files need this, as we need to create files that do not exist in the XGP save data
                temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

                # Get save file paths
                save_paths = get_save_paths(games, store_pkg_name, containers, temp_dir)
                if len(save_paths) == 0:
                    continue
                print(f"  Saves for user {xbox_username_or_id} :")
                for file_name, _ in save_paths:
                    print(f"  - {file_name}")

                # Create a ZIP file
                formatted_game_name = (
                    name.replace(" ", "_")
                    .replace(":", "_")
                    .replace("'", "")
                    .replace("!", "")
                    .lower()
                )
                timestamp = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
                zip_name = "{}_{}_{}.zip".format(
                    formatted_game_name, xbox_username_or_id, timestamp
                )
                with zipfile.ZipFile(zip_name, "x", zipfile.ZIP_DEFLATED) as save_zip:
                    for file_name, file_path in save_paths:
                        save_zip.write(file_path, arcname=file_name)

                temp_dir.cleanup()

                print()
                print('  Saves written to "%s"' % zip_name)
                print()

        except Exception:
            print("  Save extraction failed:")
            traceback.print_exc()
            print()



def test_palworld_conversion_engine():
    """Test intégral du moteur embarqué sans modifier les sauvegardes Steam."""
    games = read_game_list()
    package_name = "PocketpairInc.Palworld_ad4psfrxyesvt"
    xbox_users = find_user_containers(package_name)
    if games is None or not xbox_users:
        raise ValueError("Palworld Xbox save not found for the test.")
    store_pkg_name, containers = read_user_containers(xbox_users[0][1])
    temp_extract = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    temp_target = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        save_paths = get_save_paths(games, store_pkg_name, containers, temp_extract)
        converted_paths = [
            (PurePath(name.replace("\\", "/")), source)
            for name, source in save_paths
        ]
        account_files, worlds = group_palworld_worlds(converted_paths)
        active = next(
            files
            for name, files in worlds.items()
            if "point de restauration" not in name
        )
        account_dir = Path(temp_target.name) / "COMPTE_STEAM_TEST"
        world_dir = account_dir / "MONDE_STEAM_TEST"
        (world_dir / "Level").mkdir(parents=True)
        (world_dir / "Level.sav").write_bytes(b"old test manifest")
        (world_dir / "Level/01.sav").write_bytes(b"old test segment")
        copy_palworld_world(active, account_files, account_dir, world_dir)

        level = (world_dir / "Level.sav").read_bytes()
        if level[8:11] != b"PlM" or (world_dir / "Level").exists():
            raise ValueError("The Steam format test failed.")
        from palsav.core import decompress_sav_to_gvas

        raw_level, _ = decompress_sav_to_gvas(level)
        if raw_level[:4] != b"GVAS":
            raise ValueError("The converted Level.sav is invalid.")
        print("PALWORLD TEST PASSED: Xbox CNK/PLZ converted to Steam PLM.")
    finally:
        temp_extract.cleanup()
        temp_target.cleanup()


def main():
    if "--test-palworld" in sys.argv:
        test_palworld_conversion_engine()
        return

    print("Xbox Game Pass / Steam save transfer tool")
    print("=========================================================")
    print("1. Extract Xbox Game Pass saves to ZIP files")
    print("2. Automatically transfer Palworld from Xbox Game Pass to Steam")
    print("3. Manually import a ZIP into a Steam save folder")
    print()
    choice = input("Choose 1, 2, or 3: ").strip()
    print()

    try:
        if choice == "1":
            extract_xbox_saves()
        elif choice == "2":
            transfer_palworld_xbox_to_steam()
        elif choice == "3":
            import_saves_to_steam()
        else:
            print("Invalid choice.")
    except Exception:
        print("Operation failed:")
        traceback.print_exc()

    print()
    print("Press Enter to exit")
    input()


if __name__ == "__main__":
    main()
