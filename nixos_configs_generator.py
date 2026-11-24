#!/usr/bin/env python3
"""Prepare a new NixOS configuration in an isolated directory."""
from __future__ import annotations
import argparse
import ctypes
import errno
import ipaddress
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

REPOSITORY = 'https://github.com/palumbou/another_nixos_configurations_template.git'
TOKEN = re.compile(r"(?<!'')(?<!\\)\$\{([A-Z][A-Z0-9_]*)\}")
FEATURES = {name: f'common/packages/{name}.nix' for name in (
    'photo_editing', 'video_editing', 'development', 'recording', 'container_tools',
    'distrobox', 'virtualization_tools', 'extra_packages_services', 'kde_packages',
    'gamestation_packages', 'external_monitor', 'unstable_temporary_packages')}
FEATURES.update({name: f'common/services/{name}.nix' for name in ('docker', 'libvirt')})
FEATURES.update({name: f'common/config/{name}.nix' for name in ('audio', 'audio_airplay', 'audio_chromecast')})
FEATURES['bluetooth'] = 'common/network/default_bluetooth.nix'
DEFAULTS = dict(
    HOST_ROLE='client', HOSTNAME='nixos', DESKTOP='none', FEATURES='',
    ADMIN_USER='admin', ADMIN_UID='1000', ADMIN_GID='1000',
    WORKER_USER='worker', WORKER_UID='1100', WORKER_GID='1100',
    WORK_GROUP='worker-work', WORK_GID='1200', WORK_ROOT='/srv/worker',
    TIMEZONE='Europe/Rome', DEFAULT_LOCALE='it_IT.UTF-8', KEY_LAYOUT='it',
    FONT='nerd-fonts.code-new-roman', NIXOS_VERSION='26.05',
    SSH_PORT='22', SSH_ALLOWED_CIDRS='', DICTIONARY='it_IT', BASEPATHUSER='/home',
    ENABLE_RDP='false', RDP_PORT='3389', RDP_ALLOWED_CIDRS='',
    ENABLE_WIFI='false', WIFI_SSID='', ENABLE_SYNCTHING='false',
    SYNCTHING_DEVICE_ID='', SYNCTHING_ADDRESS='dynamic', SYNCTHING_FOLDER_PATH='',
    SYNCTHING_FOLDER_ID='work-data',
    ENABLE_SNAPSHOTS='false', ENABLE_SCRUB='false', ENABLE_BTRFS_ASSISTANT='false',
    ENABLE_BATTERY='false', MAX_JOBS='', BUILD_CORES='',
    ENABLE_ZRAM='true', ZRAM_PERCENT='', ZRAM_ALGORITHM='',
    DISK_LAYOUT='', DISK_DEVICE='sda', SWAP_SIZE='16G', BOOT_LOADER='systemd-boot',
    CPU_VENDOR='generic', PLATFORM='x86_64-linux', CHARGE_LIMIT_MODE='none',
    CHARGE_START_THRESHOLD='75', CHARGE_STOP_THRESHOLD='80')
BOOLS = {key for key in DEFAULTS if key.startswith('ENABLE_')}
NUMBERS = {'ADMIN_UID': (1000, 60000), 'ADMIN_GID': (1000, 60000),
    'WORKER_UID': (1000, 60000), 'WORKER_GID': (1000, 60000), 'WORK_GID': (1000, 60000),
    'SSH_PORT': (1, 65535), 'RDP_PORT': (1, 65535), 'MAX_JOBS': (1, 1024),
    'BUILD_CORES': (0, 1024), 'ZRAM_PERCENT': (1, 100),
    'CHARGE_START_THRESHOLD': (0, 99), 'CHARGE_STOP_THRESHOLD': (1, 100)}
RESERVED_NAMES = {
    'root', 'nobody', 'nogroup', 'wheel', 'users', 'daemon', 'bin', 'sys', 'adm',
    'disk', 'tty', 'kmem', 'mem', 'audio', 'video', 'input', 'render', 'storage',
    'networkmanager', 'i2c', 'kvm', 'docker', 'libvirtd', 'qemu-libvirtd', 'syncthing',
    'messagebus', 'polkituser', 'sshd', 'nscd', 'avahi', 'geoclue', 'rtkit',
    'pipewire', 'pulse', 'cups', 'scanner', 'lp', 'utmp', 'flatpak',
    'systemd-network', 'systemd-resolve', 'systemd-timesync', 'systemd-coredump',
}

# Only the secret paths are replaced for evaluation; the real SOPS module stays loaded.
NIX_VALIDATION_EXPRESSION = r'''
let
  source = builtins.toPath (builtins.getEnv "NIXOS_GENERATOR_NIXPKGS");
  parameters = builtins.fromJSON (builtins.getEnv "NIXOS_GENERATOR_PARAMETERS");
  placeholder = builtins.path {
    path = builtins.toPath (builtins.getEnv "NIXOS_GENERATOR_SECRET_PLACEHOLDER");
    name = "generator-secrets-placeholder.yaml";
  };
  result = import (source + "/nixos/lib/eval-config.nix") {
    system = parameters.PLATFORM;
    modules = [
      (builtins.toPath (builtins.getEnv "NIXOS_GENERATOR_CONFIG"))
      ({ lib, ... }: {
        options.sops.secrets = lib.mkOption {
          type = lib.types.attrsOf (lib.types.submodule ({ ... }: {
            config.sopsFile = lib.mkForce placeholder;
          }));
        };
        config.sops.defaultSopsFile = lib.mkForce placeholder;
      })
    ];
  };
  inherit (result) config pkgs;
  inherit (pkgs) lib;
  data = import source { system = builtins.currentSystem; };
  fontPath = lib.splitString "." parameters.FONT;
  font = if lib.hasAttrByPath fontPath pkgs
    then lib.getAttrFromPath fontPath pkgs
    else throw "Unknown FONT package attribute: ${parameters.FONT}";
  dictionary = if builtins.hasAttr parameters.DICTIONARY pkgs.hunspellDicts
    then builtins.getAttr parameters.DICTIONARY pkgs.hunspellDicts
    else throw "Unknown DICTIONARY package attribute: ${parameters.DICTIONARY}";
  failures = map (a: a.message) (builtins.filter (a: !a.assertion) config.assertions)
    ++ lib.optional (config.nixpkgs.hostPlatform.system != parameters.PLATFORM)
      "The supplied hardware platform differs from PLATFORM"
    ++ lib.optional (parameters.ENABLE_SNAPSHOTS == "true" && config.services.snapper.configs == {})
      "ENABLE_SNAPSHOTS requires an effective Btrfs snapshot configuration";
in {
  failed_assertions = failures;
  system_derivation = if failures == [] then config.system.build.toplevel.drvPath else "";
  nixpkgs_version = lib.version;
  font_derivation = if lib.isDerivation font then font.drvPath else throw "FONT must select a package";
  dictionary_derivation = if lib.isDerivation dictionary then dictionary.drvPath else throw "DICTIONARY must select a package";
  catalogs = {
    outputs = map toString [ data.tzdata data.glibcLocales data.xkeyboard_config ];
    zoneinfo = "${data.tzdata}/share/zoneinfo";
    locales = "${data.glibcLocales}/share/i18n/SUPPORTED";
    keymaps = "${data.xkeyboard_config}/etc/X11/xkb/rules/base.lst";
    default_charset = config.i18n.defaultCharset;
    supported_locales = config.i18n.supportedLocales;
  };
}
'''


class InvalidConfiguration(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidConfiguration(message)


def read_env(path):
    """Parse assignments as data, never execute shell commands or expansions."""
    result = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        parts = shlex.split(line, comments=True, posix=True)
        if not parts:
            continue
        if parts[0] == 'export':
            parts.pop(0)
        require(len(parts) == 1 and '=' in parts[0], f'{path}:{number}: expected KEY=value')
        key, value = parts[0].split('=', 1)
        require(key in DEFAULTS, f'{path}:{number}: unknown parameter {key}')
        require(key not in result, f'{path}:{number}: duplicate parameter {key}')
        result[key] = value
    return result


def csv(value):
    return [item.strip() for item in value.split(',') if item.strip()]


def cidrs(value):
    networks = []
    for item in csv(value):
        require('%' not in item, 'CIDRs must not contain IPv6 scope identifiers')
        networks.append(str(ipaddress.ip_network(item, strict=False)))
    return list(dict.fromkeys(networks))


def validate(values):
    p = dict(values)
    p['DISK_LAYOUT'] = p['DISK_LAYOUT'] or ('btrfs-worker-luks' if p['HOST_ROLE'] == 'server' else 'single-disk-ext4')
    p['MAX_JOBS'] = p['MAX_JOBS'] or ('2' if p['HOST_ROLE'] == 'server' else '4')
    p['BUILD_CORES'] = p['BUILD_CORES'] or ('4' if p['HOST_ROLE'] == 'server' else '0')
    p['ZRAM_PERCENT'] = p['ZRAM_PERCENT'] or ('50' if p['HOST_ROLE'] == 'server' else '30')
    p['ZRAM_ALGORITHM'] = p['ZRAM_ALGORITHM'] or ('zstd' if p['HOST_ROLE'] == 'server' else 'lz4')
    p['SYNCTHING_FOLDER_PATH'] = p['SYNCTHING_FOLDER_PATH'] or (
        p['WORK_ROOT'].rstrip('/') + '/data' if p['HOST_ROLE'] == 'server' else
        '/home/' + p['ADMIN_USER'] + '/Sync/work-data')
    for key in BOOLS:
        require(p[key].lower() in ('true', 'false'), f'{key} must be true or false')
        p[key] = p[key].lower()
    for key, (low, high) in NUMBERS.items():
        require(p[key].isdigit() and low <= int(p[key]) <= high, f'{key} must be {low}..{high}')
        p[key] = str(int(p[key]))
        if key.endswith(('_UID', '_GID')):
            require(not 30000 <= int(p[key]) <= 31000, f'{key} overlaps the reserved Nix build-account ID range 30000..31000')
    for key, choices in {
        'HOST_ROLE': ('client', 'server'), 'DESKTOP': ('none', 'kde', 'gnome', 'hyprland'),
        'BOOT_LOADER': ('systemd-boot', 'grub', 'lanzaboote'),
        'CPU_VENDOR': ('generic', 'intel', 'amd'), 'PLATFORM': ('x86_64-linux', 'aarch64-linux'),
        'CHARGE_LIMIT_MODE': ('none', 'thresholds'),
        'ZRAM_ALGORITHM': ('lz4', 'zstd', 'lzo', 'lzo-rle'),
    }.items():
        require(p[key] in choices, f'{key} must be one of {", ".join(choices)}')
    require(p['PLATFORM'] == 'x86_64-linux' or p['CPU_VENDOR'] == 'generic',
        'CPU_VENDOR intel/amd requires PLATFORM=x86_64-linux')
    require(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p['HOSTNAME']), 'Invalid HOSTNAME')
    for key in ('ADMIN_USER', 'WORKER_USER', 'WORK_GROUP'):
        require(re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', p[key]), f'Invalid {key}')
        require(p[key] not in RESERVED_NAMES and not re.fullmatch(r'nixbld[0-9]*', p[key]), f'Reserved service/account/group name for {key}')
    require(len({p[key] for key in ('ADMIN_USER', 'WORKER_USER', 'WORK_GROUP')}) == 3, 'Account/group names must differ')
    require(p['ADMIN_UID'] != p['WORKER_UID'], 'Admin and worker UIDs must differ')
    require(len({p[key] for key in ('ADMIN_GID', 'WORKER_GID', 'WORK_GID')}) == 3, 'Account/shared GIDs must differ')
    for key in ('WORK_ROOT', 'BASEPATHUSER', 'SYNCTHING_FOLDER_PATH'):
        require(re.fullmatch(r'/[A-Za-z0-9_./-]+', p[key]), f'Invalid absolute {key}')
        p[key] = posixpath.normpath('/' + p[key].lstrip('/'))
        require(p[key] != '/', f'{key} must name a dedicated directory')
    work = Path(p['WORK_ROOT'])
    system_roots = ('/boot', '/dev', '/proc', '/sys', '/usr', '/etc', '/nix', '/run', '/bin', '/sbin', '/lib', '/lib64')
    require(str(work) not in ('/home', '/var', '/opt', '/srv'), 'WORK_ROOT must not be a system mount point')
    require(not any(work == Path(root) or Path(root) in work.parents for root in system_roots),
        'WORK_ROOT must be outside system directories')
    protected = [Path('/home') / p[key] for key in ('ADMIN_USER', 'WORKER_USER')]
    protected.append(Path('/var/lib/syncthing'))
    require(not any(work == path or work in path.parents or path in work.parents for path in protected),
        'WORK_ROOT must not overlap account homes or Syncthing state')
    folder = Path(p['SYNCTHING_FOLDER_PATH'])
    require(str(folder) not in ('/home', '/var', '/opt', '/srv'), 'Syncthing data folder must name a dedicated directory')
    sync_state = [Path('/var/lib/syncthing'), Path('/home') / p['ADMIN_USER'] / '.config/syncthing']
    require(not any(folder == path or folder in path.parents or path in folder.parents for path in sync_state),
        'Syncthing data folder must not overlap service state')
    require(not any(folder == Path(root) or Path(root) in folder.parents for root in system_roots),
        'Syncthing data folder must be outside system directories')
    for key in ('TIMEZONE', 'DEFAULT_LOCALE', 'KEY_LAYOUT', 'DICTIONARY', 'SYNCTHING_FOLDER_ID'):
        require(re.fullmatch(r'[A-Za-z0-9_+./@-]+', p[key]), f'Invalid {key}')
    require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*', p['FONT']), 'Invalid FONT package attribute')
    require(re.fullmatch(r'\d{2}\.\d{2}', p['NIXOS_VERSION']), 'NIXOS_VERSION must be YY.MM')
    require(p['HOST_ROLE'] != 'server' or p['DESKTOP'] == 'none', 'Servers require DESKTOP=none; RDP is separate')
    require(p['ENABLE_BTRFS_ASSISTANT'] != 'true' or (p['ENABLE_SNAPSHOTS'] == 'true' and (p['DESKTOP'] != 'none' or p['ENABLE_RDP'] == 'true')), 'Btrfs Assistant requires snapshots and a local or remote desktop')
    require(p['CHARGE_LIMIT_MODE'] != 'thresholds' or int(p['CHARGE_START_THRESHOLD']) < int(p['CHARGE_STOP_THRESHOLD']), 'Charge start must be below stop')
    require(re.fullmatch(r'(?:/dev/)?[A-Za-z0-9_./:-]+', p['DISK_DEVICE']) and '..' not in Path(p['DISK_DEVICE']).parts, 'Invalid DISK_DEVICE')
    require(not p['DISK_DEVICE'].startswith('/') or p['DISK_DEVICE'].startswith('/dev/'), 'Device paths must start /dev/')
    p['DISK_DEVICE'] = p['DISK_DEVICE'].removeprefix('/dev/')
    require(bool(p['DISK_DEVICE']), 'Empty device name')
    require(re.fullmatch(r'[1-9][0-9]*[MG]', p['SWAP_SIZE']), 'SWAP_SIZE must be positive, e.g. 16G')
    features = list(dict.fromkeys(csv(p['FEATURES'])))
    require(not set(features) - FEATURES.keys(), 'Unknown FEATURES: ' + ','.join(sorted(set(features) - FEATURES.keys())))
    require(p['PLATFORM'] == 'x86_64-linux' or 'gamestation_packages' not in features,
        'gamestation_packages requires PLATFORM=x86_64-linux (Steam)')
    p['FEATURES'] = ','.join(features)
    for key in ('SSH_ALLOWED_CIDRS', 'RDP_ALLOWED_CIDRS'):
        p[key] = ','.join(cidrs(p[key]))
    p['RDP_ALLOWED_CIDRS'] = p['RDP_ALLOWED_CIDRS'] or p['SSH_ALLOWED_CIDRS']
    require(p['HOST_ROLE'] != 'server' or p['SSH_ALLOWED_CIDRS'], 'Servers require nonempty SSH_ALLOWED_CIDRS')
    require(p['ENABLE_RDP'] != 'true' or p['RDP_ALLOWED_CIDRS'], 'RDP requires allowed CIDRs (or SSH CIDRs as fallback)')
    require(p['ENABLE_RDP'] != 'true' or p['SSH_PORT'] != p['RDP_PORT'], 'SSH_PORT and RDP_PORT must differ when RDP is enabled')
    if p['ENABLE_SYNCTHING'] == 'true':
        for key in ('SSH_PORT', 'RDP_PORT') if p['ENABLE_RDP'] == 'true' else ('SSH_PORT',):
            require(p[key] not in ('22222', '8843'), f'{key} conflicts with a Syncthing listening port (22222 or 8843)')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in p['WIFI_SSID']), 'WIFI_SSID must not contain control characters')
    require(p['ENABLE_WIFI'] != 'true' or bool(p['WIFI_SSID']), 'WiFi requires WIFI_SSID')
    require(p['ENABLE_WIFI'] != 'true' or len(p['WIFI_SSID'].encode('utf-8')) <= 32,
        'WIFI_SSID must be at most 32 UTF-8 bytes')
    require(not p['SYNCTHING_DEVICE_ID'] or re.fullmatch(r'[A-Z2-7]{7}(?:-[A-Z2-7]{7}){7}', p['SYNCTHING_DEVICE_ID']), 'Invalid Syncthing device ID')
    require(not p['SYNCTHING_ADDRESS'] or re.fullmatch(r'[A-Za-z0-9:/?.&=_+\[\]-]+', p['SYNCTHING_ADDRESS']), 'Invalid SYNCTHING_ADDRESS')
    require(not p['SYNCTHING_DEVICE_ID'] or re.fullmatch(r'tcp[46]?://(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]):[0-9]{1,5}', p['SYNCTHING_ADDRESS']), 'A remote device ID requires a fixed tcp/tcp4/tcp6 endpoint with port')
    if p['SYNCTHING_DEVICE_ID']:
        require(1 <= int(p['SYNCTHING_ADDRESS'].rsplit(':', 1)[1]) <= 65535, 'Invalid Syncthing endpoint port')
    require(p['HOST_ROLE'] != 'server' or p['SYNCTHING_FOLDER_PATH'] == p['WORK_ROOT'] + '/data', 'Server Syncthing folder must be WORK_ROOT/data')
    return p


def nix_string(value):
    return json.dumps(str(value), ensure_ascii=False).replace('${', '\\${')


def derived(p):
    result = dict(p)
    # SSIDs are emitted only through this quoted, escaped value.
    result['WIFI_SSID_NIX'] = nix_string(p['WIFI_SSID'])
    for prefix in ('SSH', 'RDP'):
        for version in (4, 6):
            values = [net for net in csv(p[prefix + '_ALLOWED_CIDRS']) if ipaddress.ip_network(net).version == version]
            result[f'{prefix}_ALLOWED_IPV{version}_NIX'] = '[ ' + ' '.join(map(nix_string, values)) + ' ]'
    return result


def optional_imports(p):
    result = []
    if p['DESKTOP'] != 'none':
        result.append(f'common/gui/{p["DESKTOP"]}.nix')
    for flag, file in (
        ('ENABLE_RDP', 'common/gui/xfce-rdp.nix'),
        ('ENABLE_SNAPSHOTS', 'common/config/btrfs_snapshots.nix'),
        ('ENABLE_SCRUB', 'common/config/btrfs_scrub.nix'),
        ('ENABLE_BTRFS_ASSISTANT', 'common/packages/btrfs_assistant.nix'),
        ('ENABLE_BATTERY', 'common/config/battery_management.nix')):
        if p[flag] == 'true' and (flag != 'ENABLE_BATTERY' or p['HOST_ROLE'] == 'client'):
            result.append(file)
    result += [FEATURES[key] for key in csv(p['FEATURES'])]
    if p['DESKTOP'] == 'none' and {'audio_airplay', 'audio_chromecast'} & set(csv(p['FEATURES'])):
        result.append(FEATURES['audio'])
    if p['DISK_LAYOUT'] != 'none':
        result += ['common/config/disko.nix']
    imports = ['    ../../../' + file for file in dict.fromkeys(result)]
    if p['DISK_LAYOUT'] != 'none':
        imports.append('    ./disk-layout.nix')
    if p['BOOT_LOADER'] == 'lanzaboote':
        imports.append('    ../../secure_boot/secure_boot.nix')
    return '\n'.join(imports)


def extra_settings(p):
    result = [f'  nixpkgs.hostPlatform = lib.mkDefault {nix_string(p["PLATFORM"])};']
    if p['BOOT_LOADER'] == 'grub':
        result += ['  boot.loader.grub.enable = true;', f'  boot.loader.grub.devices = lib.mkForce [ {nix_string("/dev/" + p["DISK_DEVICE"])} ];', '  boot.loader.grub.useOSProber = false;']
    elif p['BOOT_LOADER'] == 'systemd-boot':
        result += ['  boot.loader.systemd-boot.enable = true;', '  boot.loader.efi.canTouchEfiVariables = true;']
    return '\n'.join(result)


def render(text, values, path):
    def replace(match):
        key = match.group(1)
        require(key in values, f'{path}: undeclared placeholder {key}')
        return values[key]
    return TOKEN.sub(replace, text)


def check_source(source):
    for file in source.rglob('*'):
        require(not file.is_symlink(), f'Symlink in template input: {file.relative_to(source)}')
    for name in ('roles/base.nix', 'roles/client.nix', 'roles/server.nix',
        'hosts/client/ABC/configuration.nix.template', 'hosts/server/ABC/configuration.nix.template',
        'users/ADMIN/admin.nix.template', 'users/ADMIN/client.nix.template', 'users/WORKER/worker.nix.template'):
        require((source / name).is_file(), f'Unsupported template schema: missing {name}')


def check_sops(path, required):
    """Check ciphertext structure only: no decryption, keys or secret printing."""
    require(path.is_file() and not path.is_symlink(), f'Missing regular SOPS input: {path.name}')
    text = path.read_text()
    body, separator, metadata = text.partition('\nsops:')
    require(separator and re.search(r'^\s+mac:\s*ENC\[', metadata, re.M), f'{path.name}: missing encrypted SOPS metadata')
    fields = set()
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_-]*):\s*ENC\[.+\]\s*', line)
        require(match, f'{path.name}: every top-level secret must be encrypted')
        fields.add(match.group(1))
    require(not required - fields, f'{path.name}: missing encrypted fields: {", ".join(sorted(required - fields))}')


def install_secrets(output, p, args):
    require(not args.require_secrets or args.secrets_dir, '--require-secrets needs --secrets-dir')
    if args.secrets_dir:
        inputs = [('common.yaml', {'admin_hashedPassword', 'admin_ssh_publicKey'})]
        host_fields = {'worker_hashedPassword', 'worker_ssh_publicKey'} if p['HOST_ROLE'] == 'server' else set()
        if p['ENABLE_WIFI'] == 'true':
            host_fields.add('wifi_env')
        inputs.append((p['HOSTNAME'] + '.yaml', host_fields))
        for name, fields in inputs:
            source = args.secrets_dir / name
            check_sops(source, fields)
            shutil.copyfile(source, output / 'secrets' / name)
    require(bool(args.admin_age_recipient) == bool(args.host_age_recipient), 'Supply both public age recipients or neither')
    if args.admin_age_recipient:
        for recipient in (args.admin_age_recipient, args.host_age_recipient):
            require(re.fullmatch(r'age1[023456789acdefghjklmnpqrstuvwxyz]{58}', recipient), 'Expected an age public recipient')
        text = (output / '.sops.yaml.template').read_text()
        text = text.replace('REPLACE_WITH_EDITOR_AGE_RECIPIENT', args.admin_age_recipient).replace('REPLACE_WITH_HOST_AGE_RECIPIENT', args.host_age_recipient)
        (output / '.sops.yaml').write_text(text)
    return bool(args.secrets_dir)


def verify_placeholders(tree):
    for file in tree.rglob('*.nix'):
        text = file.read_text()
        require(not TOKEN.search(text), f'Unresolved parameter: {file.relative_to(tree)}')


def run_nix(command, *, env=None, context):
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    require(result.returncode == 0, f'{context}:\n{result.stderr.strip() or result.stdout.strip()}')
    return result.stdout


def validate_catalogs(catalogs, p, env):
    """Check names against data from the selected nixpkgs, without building a system."""
    missing = [path for path in catalogs['outputs'] if not Path(path).is_dir()]
    if missing:
        store = shutil.which('nix-store')
        require(store is not None, 'Catalog validation requires nix-store to obtain missing nixpkgs data')
        # Disable local and remote builders: only obtain catalog outputs from substitutes.
        run_nix([store, '--realise', '--option', 'max-jobs', '0', '--option', 'builders', '', *missing], env=env,
            context='Cannot obtain nixpkgs catalog data; check Nix substitutes/network access')
    zoneinfo = Path(catalogs['zoneinfo'])
    timezone = p['TIMEZONE']
    zones = {str(file.relative_to(zoneinfo)) for file in zoneinfo.rglob('*') if file.is_file()}
    require(timezone in zones and (zoneinfo / timezone).read_bytes()[:4] == b'TZif',
        f'Unknown TIMEZONE in selected nixpkgs: {timezone}')
    supported = set()
    for line in Path(catalogs['locales']).read_text().splitlines():
        match = re.match(r'^([^\s#]+/[^\s\\]+)', line)
        if match:
            supported.add(match.group(1))
    locale = p['DEFAULT_LOCALE']
    require(locale == 'C' or locale + '/' + catalogs['default_charset'] in supported,
        f'Unknown DEFAULT_LOCALE in selected nixpkgs: {locale}')
    unsupported = set(catalogs['supported_locales']) - supported - {'all'}
    require(not unsupported, 'Unsupported NixOS locales: ' + ', '.join(sorted(unsupported)))
    layouts = set()
    section = ''
    for line in Path(catalogs['keymaps']).read_text().splitlines():
        fields = line.split()
        if fields[:1] == ['!']:
            section = fields[1] if len(fields) > 1 else ''
        elif fields and section == 'layout':
            layouts.add(fields[0])
    require(p['KEY_LAYOUT'] in layouts, f'Unknown KEY_LAYOUT in selected nixpkgs: {p["KEY_LAYOUT"]}')


def validate_generated(output, configuration, p):
    """Validate the staged configuration before publishing it; never activate it."""
    nix = shutil.which('nix-instantiate')
    require(nix is not None,
        'Generation requires nix-instantiate and a nixpkgs source in NIX_PATH; install Nix before generating')
    env = os.environ.copy()
    for bypass in ('NIXPKGS_ALLOW_UNFREE', 'NIXPKGS_ALLOW_UNSUPPORTED_SYSTEM', 'NIXPKGS_ALLOW_BROKEN', 'NIXPKGS_ALLOW_INSECURE'):
        env.pop(bypass, None)
    nixpkgs = run_nix([nix, '--find-file', 'nixpkgs'], env=env, context='Cannot resolve nixpkgs (check NIX_PATH)').strip()
    files = sorted(output.rglob('*.nix'))
    for file in files:
        run_nix([nix, '--parse', str(file)], env=env,
            context=f'Invalid Nix syntax in {file.relative_to(output)}')
    with tempfile.TemporaryDirectory(prefix='.nix-validation-', dir=output.parent) as temporary:
        validation_root = Path(temporary)
        placeholder = validation_root / 'secrets-placeholder.yaml'
        placeholder.write_text('{}\n')
        expression = validation_root / 'validate.nix'
        expression.write_text(NIX_VALIDATION_EXPRESSION)
        env.update(NIXOS_GENERATOR_CONFIG=str(configuration), NIXOS_GENERATOR_NIXPKGS=nixpkgs,
            NIXOS_GENERATOR_PARAMETERS=json.dumps(p), NIXOS_GENERATOR_SECRET_PLACEHOLDER=str(placeholder))
        result = json.loads(run_nix([nix, '--eval', '--strict', '--json', '--read-write-mode',
            '--option', 'allow-import-from-derivation', 'false', str(expression)],
            env=env, context='NixOS configuration validation failed'))
        require(not result['failed_assertions'], 'NixOS assertions failed: ' + '; '.join(result['failed_assertions']))
        validate_catalogs(result['catalogs'], p, env)
    return dict(status='validated', nixpkgs=nixpkgs, nixpkgs_version=result['nixpkgs_version'],
        platform=p['PLATFORM'], system_derivation=result['system_derivation'], checked_files=len(files),
        secret_values_checked=False, evaluation_uses_placeholder_secret_paths=True)


def publish(source, destination):
    """Linux renameat2 prevents replacement even if another process wins the race."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    require(rename is not None, 'Atomic non-replacing publication requires Linux renameat2')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise InvalidConfiguration('Output appeared during preparation; preserved')
        raise OSError(code, os.strerror(code), str(destination))


def prepare(template, destination, overrides, args):
    source = template / 'nixos_configs_template'
    require(source.is_dir() and (template / 'env.conf').is_file(), 'Expected env.conf and nixos_configs_template/')
    check_source(source)
    p = validate(DEFAULTS | read_env(template / 'env.conf') | overrides)
    require(not destination.exists() and not destination.is_symlink(), 'Output already exists; it was preserved')
    require(template.resolve() not in destination.resolve().parents and destination.resolve() not in template.resolve().parents, 'Source repository and output must not overlap')
    if args.secrets_dir:
        secret_root = args.secrets_dir.expanduser().resolve()
        target = destination.resolve()
        require(secret_root.is_dir(), '--secrets-dir must name an existing directory')
        require(secret_root != target and secret_root not in target.parents and target not in secret_root.parents,
            'Encrypted secrets input and output must not overlap')
    require(destination.parent.is_dir(), 'Output parent directory must exist')
    layouts = {file.stem: file for file in (source / 'hosts/disk_configurations').rglob('*.nix')}
    layout = p['DISK_LAYOUT']
    if layout != 'none':
        require(layout in layouts, 'Unknown DISK_LAYOUT: choose none or ' + ', '.join(sorted(layouts)))
        require(('bios' in layout) == (p['BOOT_LOADER'] == 'grub'), 'BIOS layouts require grub; UEFI layouts require systemd-boot or lanzaboote')
        require(not (p['ENABLE_SNAPSHOTS'] == 'true' or p['ENABLE_SCRUB'] == 'true') or 'btrfs' in layout, 'Snapshots/scrub need Btrfs')
    if args.hardware_configuration:
        require(args.hardware_configuration.is_file() and not args.hardware_configuration.is_symlink(), 'Hardware input must be a regular file')
    require(layout != 'none' or args.hardware_configuration, 'DISK_LAYOUT=none requires --hardware-configuration with destination filesystem declarations')
    with tempfile.TemporaryDirectory(prefix='.nixos-prepare-', dir=destination.parent) as temporary:
        output = Path(temporary) / 'nixos_configs'
        shutil.copytree(source, output)
        for file in (output / 'secrets').rglob('*.yaml'):
            file.unlink()
        (output / '.sops.yaml').unlink(missing_ok=True)
        category = 'client' if p['HOST_ROLE'] == 'client' else 'server'
        host = output / 'hosts' / category / p['HOSTNAME']
        (output / 'hosts' / category / 'ABC').rename(host)
        other = 'server' if category == 'client' else 'client'
        shutil.rmtree(output / 'hosts' / other)
        (output / 'users/ADMIN').rename(output / 'users' / p['ADMIN_USER'])
        if p['HOST_ROLE'] == 'server':
            (output / 'users/WORKER').rename(output / 'users' / p['WORKER_USER'])
        else:
            shutil.rmtree(output / 'users/WORKER')
        if layout != 'none':
            shutil.copyfile(output / layouts[layout].relative_to(source), host / 'disk-layout.nix')
        values = derived(p) | {'HOST_IMPORTS': optional_imports(p), 'HOST_EXTRA_CONFIG': extra_settings(p)}
        for file in list(output.rglob('*')):
            if not file.is_file() or file.suffix not in ('.nix', '.template'):
                continue
            relative = file.relative_to(output)
            text = render(file.read_text(), values, relative)
            text = text.replace('/users/ADMIN/', '/users/' + p['ADMIN_USER'] + '/').replace('/users/WORKER/', '/users/' + p['WORKER_USER'] + '/')
            preserve = 'secrets' in relative.parts or file.name == '.sops.yaml.template'
            target = file if preserve or file.suffix != '.template' else file.with_suffix('')
            if file.name == 'ABC.yaml.template':
                target = file.with_name(p['HOSTNAME'] + '.yaml.template')
            target.write_text(text)
            if target != file:
                file.unlink()
        if args.hardware_configuration:
            shutil.copyfile(args.hardware_configuration, host / 'hardware-configuration.nix')
        complete = install_secrets(output, p, args)
        verify_placeholders(output)
        # These paths are produced by this program, not extracted from arbitrary Nix text.
        for selected_import in values['HOST_IMPORTS'].splitlines():
            require((host / selected_import.strip()).is_file(), f'missing module {selected_import.strip()}')
        validation = validate_generated(output, host / 'configuration.nix', p)
        report = dict(host=p['HOSTNAME'], role=p['HOST_ROLE'], category=category,
            configuration=str(host.relative_to(output) / 'configuration.nix'),
            encrypted_secrets_supplied=complete, parameters=p, validation=validation)
        (output / 'preparation.json').write_text(json.dumps(report, indent=2) + '\n')
        (output / 'PREPARATION.md').write_text('# Prepared configuration\n\n' +
            ('Encrypted secrets were supplied and checked structurally; authenticity was not checked or decrypted.\n\n' if complete else
             '**Secret setup is incomplete.** Edit the secret templates, encrypt them with SOPS and save common.yaml and the host YAML under secrets/. Never place plaintext values in Nix files.\n\n') +
            'Nix syntax, module imports, option types, assertions, package attributes and nixpkgs catalogs were checked before publication. Evaluation used temporary placeholder secret paths outside this output; the derivation in preparation.json is for validation only. Secret values, recipients and decryption were not verified.\n\n' +
            'Review the hardware declarations, boot device, public age recipients, authorized users, firewall CIDRs and stateVersion. Configure .sops.yaml from its template when needed. No private keys, passwords, encryption, operating-system build, installation or activation were performed.\n')
        require(not destination.exists() and not destination.is_symlink(), 'Output appeared during preparation; preserved')
        publish(output, destination)
    return report


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--template-dir', type=Path, help='Read a local new-schema template without modifying it')
    p.add_argument('--branch', default='26.05', help='Branch to clone afresh when no local template is provided')
    p.add_argument('--output', type=Path, help='New isolated output directory; must not exist')
    p.add_argument('--env-file', type=Path, help='Additional public KEY=value assignments')
    p.add_argument('--set', action='append', default=[], metavar='KEY=VALUE')
    p.add_argument('--hardware-configuration', type=Path)
    p.add_argument('--secrets-dir', type=Path, help='Directory containing existing SOPS-encrypted YAML inputs')
    p.add_argument('--require-secrets', action='store_true')
    p.add_argument('--admin-age-recipient', help='Public editor age recipient')
    p.add_argument('--host-age-recipient', help='Public host age recipient')
    p.add_argument('--list-features', action='store_true')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.list_features:
        print('\n'.join(f'{key}: {value}' for key, value in FEATURES.items()))
        return 0
    try:
        require(args.output is not None, '--output is required')
        overrides = read_env(args.env_file) if args.env_file else {}
        for assignment in args.set:
            require('=' in assignment, '--set expects KEY=value')
            key, value = assignment.split('=', 1)
            require(key in DEFAULTS, f'Unknown parameter {key}')
            overrides[key] = value
        output = args.output.expanduser().absolute()
        require(not output.exists() and not output.is_symlink(), 'Output already exists; it was preserved')
        if args.template_dir:
            report = prepare(args.template_dir.expanduser().resolve(), output, overrides, args)
        else:
            with tempfile.TemporaryDirectory(prefix='nixos-template-') as temporary:
                source = Path(temporary) / 'template'
                subprocess.run(['git', 'clone', '--depth', '1', '--branch', args.branch, '--', REPOSITORY, str(source)], check=True)
                report = prepare(source, output, overrides, args)
        print(f'Prepared {report["role"]}: {output / report["configuration"]}')
        print('Review PREPARATION.md before any installation; no system changes were performed.')
        return 0
    except (InvalidConfiguration, OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
