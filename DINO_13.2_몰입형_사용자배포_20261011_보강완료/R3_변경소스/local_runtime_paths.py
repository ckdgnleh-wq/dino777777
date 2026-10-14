"""Persist real installed paths; never copy models or bundle customer settings."""
import json, os, socket, time, uuid, wave
from pathlib import Path


def read(path, default=None):
    try:
        return json.loads(path.read_text('utf-8-sig'))
    except (OSError, ValueError):
        return default


def atomic(path, value):
    pending = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')
    pending.replace(path)


def server_present():
    for port in (5911, 5912):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.3):
                return True
        except OSError:
            pass
    return False


def installed_folder(folder, name, root, manifest):
    """Use genuine installation records and expected files, not a guessed path."""
    if not (folder / 'python/python.exe').is_file():
        return False
    features = ('qwen',) if name == 'voice' else ('flux', 'zimage')
    for feature in features:
        marker = read(root / (feature + '.ready.json'), {}) or {}
        if marker.get('manifest_version') != manifest.get('version'):
            continue
        files = manifest.get('features', {}).get(feature, [])
        if not files:
            continue
        valid = True
        for item in files:
            relative = Path(item['target'])
            if not relative.parts or relative.parts[0] != name or relative.is_absolute() or '..' in relative.parts:
                return False
            file = folder.joinpath(*relative.parts[1:])
            if not file.is_file() or file.stat().st_size != item['bytes']:
                valid = False
                break
        if valid:
            return True
    return False


def reconnect(link, target):
    """Preserve the old junction for rollback; never remove a real directory."""
    import _winapi
    backup = None
    if link.is_junction():
        backup = link.with_name(link.name + '.link-backup-' + str(time.time_ns()))
        link.rename(backup)
    elif link.exists() or link.is_symlink():
        raise RuntimeError('An existing ordinary runtime folder will not be replaced.')
    try:
        _winapi.CreateJunction(str(target), str(link))
    except BaseException:
        if backup is not None and not link.exists() and not link.is_junction():
            backup.rename(link)
        raise


def repair(release, root=None, live=None):
    release = Path(release)
    root = Path(root) if root is not None else Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'DINO_Local_v12'
    if os.name != 'nt' or not root.is_dir():
        return {'changed': [], 'reason': 'no_existing_installation'}
    manifest = read(release / '연결보조/로컬기능/manifest.json', {}) or {}
    if not manifest.get('features'):
        raise RuntimeError('The installation manifest is missing.')
    record_path = root / 'runtime-paths.json'
    recorded = read(record_path, {}) or {}
    saved = {'version': 1, 'folders': {}}
    changes = []
    running = server_present() if live is None else live
    for name in ('image', 'voice'):
        link = root / name
        # resolve() obtains the physical MSIX/Store path in a packaged host,
        # which may differ from the virtual path visible to that host.
        target = link.resolve()
        if not installed_folder(target, name, root, manifest):
            previous = (recorded.get('folders') or {}).get(name)
            if not previous:
                continue
            target = Path(previous).resolve()
            if not installed_folder(target, name, root, manifest):
                continue
        saved['folders'][name] = str(target)
        if not running and (link.is_junction() or not link.exists()):
            current = os.readlink(link) if link.is_junction() else ''
            normalized = current.removeprefix('\\\\?\\').removeprefix('\\??\\')
            if os.path.normcase(normalized) != os.path.normcase(str(target)):
                reconnect(link, target)
                changes.append(name)
    if saved['folders'] and saved != recorded:
        atomic(record_path, saved)
    if not running and 'voice' in saved['folders']:
        profile_path = root / 'voice/voice_profile.json'
        profile = read(profile_path, {}) or {}
        old = Path(profile.get('reference_wav', ''))
        if profile and not old.is_file():
            candidate = root / 'voice/references' / old.name
            if candidate.suffix.lower() == '.wav' and candidate.is_file():
                with wave.open(str(candidate), 'rb') as audio:
                    if audio.getnframes() <= 0 or audio.getframerate() <= 0:
                        raise RuntimeError('The saved voice recording is invalid.')
                profile['reference_wav'] = str(candidate)
                atomic(profile_path, profile)
                changes.append('voice_reference')
    return {'changed': changes, 'recorded': sorted(saved['folders']), 'running_preserved': running}
