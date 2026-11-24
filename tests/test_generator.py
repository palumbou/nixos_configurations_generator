"""Behavioral tests; fixtures contain no usable keys, passwords or encrypted secrets."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Also support direct execution from outside the repository root.
sys.path.insert(0, str(PROJECT_ROOT))
import nixos_configs_generator as g


class GeneratorTests(unittest.TestCase):
    """Filesystem and parameter units use skeletal modules, not a NixOS system.

    Only the semantic-validation boundary is replaced here. RealTemplateTests
    always execute the actual validator against the committed template.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nixos-generator-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'template'
        self.tree = self.repo / 'nixos_configs_template'
        self.tree.mkdir(parents=True)
        self.repo.joinpath('env.conf').write_text('export HOST_ROLE=client\nexport SSH_ALLOWED_CIDRS=192.0.2.0/24\n')
        modules = ['roles/base.nix', 'roles/client.nix', 'roles/server.nix',
                   'common/config/disko.nix', 'common/config/secrets.nix',
                   'common/config/btrfs_snapshots.nix', 'common/config/btrfs_scrub.nix',
                   'common/config/battery_management.nix', 'common/packages/btrfs_assistant.nix',
                   'common/gui/kde.nix', 'common/gui/gnome.nix', 'common/gui/hyprland.nix',
                   'common/gui/xfce-rdp.nix', 'hosts/secure_boot/secure_boot.nix'] + list(g.FEATURES.values())
        for name in modules:
            self.write(name, '{ ... }: {}\n')
        for category in ('client', 'server'):
            profile = 'client' if category == 'client' else 'admin'
            self.write(f'hosts/{category}/ABC/configuration.nix.template',
                '{ lib, ... }: {\n imports = [\n'
                '  ./hardware-configuration.nix\n'
                '  ../../../users/ADMIN/' + profile + '.nix\n'
                '${HOST_IMPORTS}\n ];\n'
                ' networking.hostName = "${HOSTNAME}";\n'
                ' system.stateVersion = "${NIXOS_VERSION}";\n'
                '${HOST_EXTRA_CONFIG}\n}\n')
            self.write(f'hosts/{category}/ABC/hardware-configuration.nix.template', '{ ... }: {}\n')
            self.write(f'hosts/{category}/ABC/nm_configurations.nix.template',
                '{ ... }: {\n networking.hostName = ${WIFI_SSID_NIX};\n}\n')
        self.write('users/ADMIN/admin.nix.template', '{ ... }: {\n users.users.${ADMIN_USER}.uid = ${ADMIN_UID};\n}\n')
        self.write('users/ADMIN/client.nix.template', '{ ... }: {\n imports = [\n ./admin.nix\n ];\n}\n')
        self.write('users/WORKER/worker.nix.template', '{ ... }: {\n users.users.${WORKER_USER}.uid = ${WORKER_UID};\n users.groups.${WORK_GROUP}.gid = ${WORK_GID};\n}\n')
        self.write('secrets/common.yaml.template', 'admin_hashedPassword: REPLACE\n')
        self.write('secrets/ABC.yaml.template', 'worker_hashedPassword: REPLACE\n')
        self.write('.sops.yaml.template', 'keys:\n - REPLACE_WITH_EDITOR_AGE_RECIPIENT\n - REPLACE_WITH_HOST_AGE_RECIPIENT\n')
        self.write('hosts/disk_configurations/btrfs/btrfs-worker-luks.nix', '{ ... }: { device = "/dev/${DISK_DEVICE}"; }\n')
        self.write('hosts/disk_configurations/ext4/single-disk-ext4-bios.nix', '{ ... }: {}\n')
        self.write('hosts/disk_configurations/ext4/single-disk-ext4.nix', '{ ... }: {}\n')
        self.output = self.root / 'output'
        semantic_validation = patch.object(g, 'validate_generated', return_value={
            'status': 'synthetic-unit-fixture',
            'system_derivation': '/synthetic-unit-fixture.drv',
        })
        self.semantic_validation = semantic_validation.start()
        self.addCleanup(semantic_validation.stop)

    def write(self, name, content):
        file = self.tree / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)

    def arguments(self, **changes):
        defaults = dict(hardware_configuration=None, secrets_dir=None, require_secrets=False,
                        admin_age_recipient=None, host_age_recipient=None)
        return argparse.Namespace(**(defaults | changes))

    def prepare(self, values=None, **args):
        return g.prepare(self.repo, self.output, values or {}, self.arguments(**args))

    def hashes(self):
        return {str(p.relative_to(self.repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.repo.rglob('*') if p.is_file()}

    def test_client_isolated_directories_static_names_and_source_immutable(self):
        before = self.hashes()
        result = self.prepare({'HOSTNAME': 'desk', 'ADMIN_USER': 'editor', 'DESKTOP': 'kde'})
        self.assertEqual(self.hashes(), before)
        self.assertEqual(result['configuration'], 'hosts/client/desk/configuration.nix')
        self.assertTrue((self.output / 'users/editor/admin.nix').is_file())
        self.assertTrue((self.output / 'users/editor/client.nix').is_file())
        self.assertFalse((self.output / 'users/WORKER').exists())
        self.assertFalse((self.output / 'hosts/server').exists())
        text = (self.output / result['configuration']).read_text()
        self.assertIn('../../../users/editor/client.nix', text)
        self.assertIn('../../../common/gui/kde.nix', text)
        self.assertNotIn('${HOST', text)
        self.assertFalse((self.output / 'secrets/common.yaml').exists())
        self.assertIn('incomplete', (self.output / 'PREPARATION.md').read_text())
        self.assertEqual(result['validation']['status'], 'synthetic-unit-fixture')

    def test_failed_semantic_validation_never_publishes_or_changes_inputs(self):
        before = self.hashes()
        self.semantic_validation.side_effect = g.InvalidConfiguration('invalid root filesystem')
        with self.assertRaisesRegex(g.InvalidConfiguration, 'invalid root filesystem'):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.hashes(), before)
        self.assertEqual(list(self.root.glob('.nixos-prepare-*')), [])

    def test_server_features_accounts_groups_disk_and_boot(self):
        self.prepare({'HOST_ROLE': 'server', 'HOSTNAME': 'node', 'ADMIN_USER': 'ops',
            'WORKER_USER': 'runner', 'WORK_GROUP': 'team', 'WORK_GID': '1400',
            'FEATURES': 'docker,libvirt,distrobox', 'DISK_LAYOUT': 'btrfs-worker-luks',
            'DISK_DEVICE': '/dev/disk/by-id/example', 'BOOT_LOADER': 'lanzaboote'})
        host = self.output / 'hosts/server/node'
        text = (host / 'configuration.nix').read_text()
        self.assertIn('common/services/docker.nix', text)
        self.assertIn('../../secure_boot/secure_boot.nix', text)
        self.assertNotIn('common/gui/kde', text)
        self.assertIn('/dev/disk/by-id/example', (host / 'disk-layout.nix').read_text())
        worker = (self.output / 'users/runner/worker.nix').read_text()
        self.assertIn('users.users.runner.uid = 1100', worker)
        self.assertIn('users.groups.team.gid = 1400', worker)
        self.assertTrue((self.output / 'secrets/node.yaml.template').is_file())
        config = json.loads((self.output / 'preparation.json').read_text())['parameters']
        self.assertEqual(config['ZRAM_PERCENT'], '50')
        self.assertEqual(config['ZRAM_ALGORITHM'], 'zstd')
        self.assertEqual(config['MAX_JOBS'], '2')
        self.assertEqual(config['BUILD_CORES'], '4')
        self.assertEqual(config['SYNCTHING_FOLDER_PATH'], '/srv/worker/data')

    def test_server_role_preserves_worker_account_defaults_and_rejects_old_role(self):
        values = g.validate(g.DEFAULTS | {'HOST_ROLE': 'server', 'SSH_ALLOWED_CIDRS': '192.0.2.0/24'})
        expected = {
            'ADMIN_UID': '1000', 'ADMIN_GID': '1000',
            'WORKER_USER': 'worker', 'WORKER_UID': '1100', 'WORKER_GID': '1100',
            'WORK_GROUP': 'worker-work', 'WORK_GID': '1200', 'WORK_ROOT': '/srv/worker',
            'DISK_LAYOUT': 'btrfs-worker-luks', 'MAX_JOBS': '2', 'BUILD_CORES': '4',
            'ZRAM_PERCENT': '50', 'ZRAM_ALGORITHM': 'zstd',
            'SYNCTHING_FOLDER_PATH': '/srv/worker/data',
        }
        for key, value in expected.items():
            self.assertEqual(values[key], value, key)
        with self.assertRaisesRegex(g.InvalidConfiguration, 'HOST_ROLE must be one of client, server'):
            self.prepare({'HOST_ROLE': 'worker'})
        self.assertFalse(self.output.exists())

    def test_ipv4_ipv6_rules_and_ssid_are_typed_and_escaped(self):
        p = g.validate(g.DEFAULTS | {'SSH_ALLOWED_CIDRS': '192.0.2.7/24,2001:db8::1/64',
            'ENABLE_WIFI': 'true', 'WIFI_SSID': 'name "quote" ${notNix}'})
        values = g.derived(p)
        self.assertEqual(values['SSH_ALLOWED_IPV4_NIX'], '[ "192.0.2.0/24" ]')
        self.assertEqual(values['SSH_ALLOWED_IPV6_NIX'], '[ "2001:db8::/64" ]')
        self.assertEqual(values['RDP_ALLOWED_IPV4_NIX'], values['SSH_ALLOWED_IPV4_NIX'])
        self.assertIn('\\"quote\\"', values['WIFI_SSID_NIX'])
        self.assertIn('\\${notNix}', values['WIFI_SSID_NIX'])

    def test_wifi_control_characters_are_rejected_without_output(self):
        for control in [chr(value) for value in range(32)] + [chr(127)]:
            with self.subTest(control=repr(control)), self.assertRaisesRegex(g.InvalidConfiguration, 'control characters'):
                self.prepare({'ENABLE_WIFI': 'true', 'WIFI_SSID': 'example' + control + 'network'})
            self.assertFalse(self.output.exists())

    def test_active_wifi_ssid_limit_counts_utf8_bytes(self):
        for ssid in ('x' * 32, '\u00e9' * 16):
            with self.subTest(valid_ssid=ssid):
                p = g.validate(g.DEFAULTS | {'ENABLE_WIFI': 'true', 'WIFI_SSID': ssid})
                self.assertEqual(p['WIFI_SSID'], ssid)
                self.assertEqual(len(p['WIFI_SSID'].encode('utf-8')), 32)
        for ssid in ('x' * 33, '\u00e9' * 17):
            with self.subTest(invalid_ssid=ssid):
                with self.assertRaisesRegex(g.InvalidConfiguration, '32 UTF-8 bytes'):
                    self.prepare({'ENABLE_WIFI': 'true', 'WIFI_SSID': ssid})
                self.assertFalse(self.output.exists())

    def test_invalid_values_never_publish_output(self):
        scenarios = [{'ADMIN_UID': '1100'}, {'WORK_GID': '1000'}, {'ADMIN_USER': '../x'},
            {'HOST_ROLE': 'worker'}, {'FEATURES': 'unknown'}, {'SSH_PORT': '0'},
            {'SSH_ALLOWED_CIDRS': 'not-a-network'}, {'ENABLE_WIFI': 'true'},
            {'FONT': 'pkgs.x; abort "bad"'}, {'WORK_ROOT': '/../etc'},
            {'HOST_ROLE': 'server', 'DESKTOP': 'kde'},
            {'ENABLE_RDP': 'true', 'SSH_ALLOWED_CIDRS': '', 'RDP_ALLOWED_CIDRS': ''},
            {'HOST_ROLE': 'server', 'SSH_ALLOWED_CIDRS': ''},
            {'HOST_ROLE': 'server', 'SYNCTHING_FOLDER_PATH': '/tmp/other-data'},
            {'SYNCTHING_DEVICE_ID': 'AAAAAAA-' * 7 + 'AAAAAAA', 'SYNCTHING_ADDRESS': 'dynamic'},
            {'SYNCTHING_DEVICE_ID': 'AAAAAAA-' * 7 + 'AAAAAAA', 'SYNCTHING_ADDRESS': 'tcp://example.invalid:99999'},
            {'PLATFORM': 'aarch64-linux', 'CPU_VENDOR': 'intel'},
            {'PLATFORM': 'aarch64-linux', 'CPU_VENDOR': 'amd'},
            {'PLATFORM': 'aarch64-linux', 'FEATURES': 'gamestation_packages'},
            {'DISK_LAYOUT': 'single-disk-ext4-bios', 'BOOT_LOADER': 'systemd-boot'},
            {'DISK_LAYOUT': 'btrfs-worker-luks', 'BOOT_LOADER': 'grub'}]
        for values in scenarios:
            with self.subTest(values=values), self.assertRaises((g.InvalidConfiguration, ValueError)):
                self.prepare(values)
            self.assertFalse(self.output.exists())

    def test_existing_output_and_symlink_are_preserved(self):
        self.output.mkdir()
        sentinel = self.output / 'keep'
        sentinel.write_text('untouched')
        with self.assertRaises(g.InvalidConfiguration):
            self.prepare()
        self.assertEqual(sentinel.read_text(), 'untouched')
        other = self.root / 'alias'
        other.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises(g.InvalidConfiguration):
            g.prepare(self.repo, other, {}, self.arguments())
        self.assertTrue(other.is_symlink())

    def test_ipv6_scope_values_cannot_be_used_as_firewall_cidrs(self):
        for key in ('SSH_ALLOWED_CIDRS', 'RDP_ALLOWED_CIDRS'):
            for value in ('fe80::%eth0/64', 'fe80::%example } accept #/64'):
                with self.subTest(parameter=key, value=value):
                    with self.assertRaises(g.InvalidConfiguration):
                        self.prepare({key: value})
                    self.assertFalse(self.output.exists())

    def test_active_services_cannot_share_known_listening_ports(self):
        scenarios = [
            {'ENABLE_RDP': 'true', 'RDP_PORT': '22'},
            {'ENABLE_SYNCTHING': 'true', 'SSH_PORT': '22222'},
            {'ENABLE_SYNCTHING': 'true', 'SSH_PORT': '8843'},
            {'ENABLE_SYNCTHING': 'true', 'ENABLE_RDP': 'true', 'RDP_PORT': '22222'},
            {'ENABLE_SYNCTHING': 'true', 'ENABLE_RDP': 'true', 'RDP_PORT': '8843'},
        ]
        for changes in scenarios:
            with self.subTest(values=changes):
                with self.assertRaises(g.InvalidConfiguration):
                    self.prepare(changes)
                self.assertFalse(self.output.exists())

    def test_disabled_services_do_not_reserve_their_listening_ports(self):
        scenarios = [
            {'ENABLE_RDP': 'false', 'RDP_PORT': '22'},
            {'ENABLE_SYNCTHING': 'false', 'SSH_PORT': '22222'},
            {'ENABLE_SYNCTHING': 'false', 'SSH_PORT': '8843'},
            {'ENABLE_SYNCTHING': 'false', 'ENABLE_RDP': 'true', 'RDP_PORT': '22222'},
            {'ENABLE_SYNCTHING': 'false', 'ENABLE_RDP': 'true', 'RDP_PORT': '8843'},
        ]
        for changes in scenarios:
            with self.subTest(values=changes):
                p = g.validate(g.DEFAULTS | {'SSH_ALLOWED_CIDRS': '192.0.2.0/24'} | changes)
                for name, value in changes.items():
                    self.assertEqual(p[name], value)

    def test_catalog_cache_miss_cannot_enable_local_or_remote_builders(self):
        store = self.root / 'nix-store'
        build_marker = self.root / 'unexpected-builder-permission'
        store.write_text('#!' + sys.executable + '\n'
            'import os,sys\nfrom pathlib import Path\n'
            'options = {}\narguments = iter(sys.argv[1:])\n'
            'for argument in arguments:\n'
            '    if argument == "--option":\n'
            '        name = next(arguments)\n'
            '        options[name] = next(arguments)\n'
            'if options.get("max-jobs") != "0" or options.get("builders") != "":\n'
            '    Path(os.environ["BUILD_MARKER"]).write_text("builder permitted")\n'
            '    sys.exit("a builder would be permitted")\n'
            'sys.exit("synthetic cache miss: no substitute available")\n')
        store.chmod(0o755)
        original_which = shutil.which

        def find_command(name):
            return str(store) if name == 'nix-store' else original_which(name)

        with patch.object(g.shutil, 'which', side_effect=find_command):
            with self.assertRaisesRegex(g.InvalidConfiguration, 'synthetic cache miss'):
                g.validate_catalogs({'outputs': [str(self.root / 'missing-catalog')]},
                    g.DEFAULTS, dict(os.environ, BUILD_MARKER=str(build_marker)))
        self.assertFalse(build_marker.exists())

    def test_atomic_publisher_preserves_an_output_created_concurrently(self):
        staged = self.root / 'staged'
        staged.mkdir()
        self.output.mkdir()
        with self.assertRaisesRegex(g.InvalidConfiguration, 'appeared'):
            g.publish(staged, self.output)
        self.assertTrue(staged.is_dir())
        self.assertTrue(self.output.is_dir())

    def test_output_must_not_be_inside_input_repository(self):
        with self.assertRaises(g.InvalidConfiguration):
            g.prepare(self.repo, self.repo / 'generated', {}, self.arguments())

    def test_output_must_not_modify_encrypted_secrets_input_directory(self):
        secrets = self.root / 'encrypted-input'
        secrets.mkdir()
        sentinel = secrets / 'keep'
        sentinel.write_text('unchanged')
        for base in (secrets, self.root / 'encrypted-alias'):
            if base != secrets:
                base.symlink_to(secrets, target_is_directory=True)
            destination = base / 'new-output'
            with self.subTest(base=base), self.assertRaisesRegex(g.InvalidConfiguration, 'must not overlap'):
                g.prepare(self.repo, destination, {}, self.arguments(secrets_dir=secrets))
            self.assertFalse(destination.exists())
        self.assertEqual(list(secrets.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), 'unchanged')

    def test_unknown_placeholder_aborts_and_preserves_nix_interpolations(self):
        self.write('common/config/unknown.nix.template', '{ x = "${UNDECLARED}"; }')
        with self.assertRaisesRegex(g.InvalidConfiguration, 'UNDECLARED'):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual(g.render('${lib.foo} \'\'${HOME}', {}, 'example'), '${lib.foo} \'\'${HOME}')

    def test_missing_import_aborts_atomically(self):
        (self.tree / 'common/gui/kde.nix').unlink()
        with self.assertRaisesRegex(g.InvalidConfiguration, 'missing module'):
            self.prepare({'DESKTOP': 'kde'})
        self.assertFalse(self.output.exists())

    def test_env_is_data_and_unknown_parameters_are_errors(self):
        path = self.root / 'input.conf'
        marker = self.root / 'must-not-exist'
        path.write_text(f'export WIFI_SSID="$(touch {marker})"\n')
        self.assertEqual(g.read_env(path)['WIFI_SSID'], f'$(touch {marker})')
        self.assertFalse(marker.exists())
        path.write_text('export OLD_USER=admin\n')
        with self.assertRaisesRegex(g.InvalidConfiguration, 'unknown parameter'):
            g.read_env(path)

    def test_encrypted_inputs_checked_without_decrypting(self):
        secrets = self.root / 'encrypted'
        secrets.mkdir()
        (secrets / 'common.yaml').write_text('admin_hashedPassword: ENC[fixture]\nadmin_ssh_publicKey: ENC[fixture]\nsops:\n    mac: ENC[fixture]\n')
        (secrets / 'nixos.yaml').write_text('wifi_env: ENC[fixture]\nsops:\n    mac: ENC[fixture]\n')
        self.prepare(secrets_dir=secrets, require_secrets=True)
        self.assertEqual((self.output / 'secrets/common.yaml').read_bytes(), (secrets / 'common.yaml').read_bytes())

    def test_plaintext_or_incomplete_secrets_rejected_without_output(self):
        secrets = self.root / 'bad'
        secrets.mkdir()
        (secrets / 'common.yaml').write_text('admin_hashedPassword: plaintext\nsops:\n    mac: ENC[fixture]\n')
        with self.assertRaises(g.InvalidConfiguration):
            self.prepare(secrets_dir=secrets)
        self.assertFalse(self.output.exists())
        with self.assertRaises(g.InvalidConfiguration):
            self.prepare(require_secrets=True)
        self.assertFalse(self.output.exists())

    def test_old_schema_rejected(self):
        (self.tree / 'hosts/server/ABC/configuration.nix.template').unlink()
        with self.assertRaisesRegex(g.InvalidConfiguration, 'Unsupported template schema'):
            self.prepare()

    def test_server_battery_preserves_server_policy_without_client_module(self):
        self.prepare({'HOST_ROLE': 'server', 'ENABLE_BATTERY': 'true'})
        text = (self.output / 'hosts/server/nixos/configuration.nix').read_text()
        self.assertNotIn('battery_management.nix', text)

    def test_work_paths_canonicalized_and_never_overlap_system_or_account_state(self):
        bad = ('/', '/boot', '/home/.', '/nix/.', '/srv/../boot', '/boot/worker',
               '/dev/worker', '/proc', '/sys', '/usr', '/etc', '/run', '/var',
               '/opt', '/srv', '/bin', '/sbin', '/lib', '/lib64',
               '/bin/worker', '/sbin/worker', '/lib/worker', '/lib64/worker',
               '/home/admin', '/home/admin/Sync', '/home/worker', '/var/lib',
               '/var/lib/syncthing', '/var/lib/syncthing/shared', '/srv/worker;abort')
        for path in bad:
            with self.subTest(path=path), self.assertRaises(g.InvalidConfiguration):
                self.prepare({'HOST_ROLE': 'server', 'WORK_ROOT': path})
            self.assertFalse(self.output.exists())
        p = g.validate(g.DEFAULTS | {'WORK_ROOT': '/srv//work/./data/..'})
        self.assertEqual(p['WORK_ROOT'], '/srv/work')
        self.assertEqual(p['SYNCTHING_FOLDER_PATH'], '/home/admin/Sync/work-data')
        for path in ('/opt/work', '/srv/work'):
            with self.subTest(dedicated_path=path):
                p = g.validate(g.DEFAULTS | {'WORK_ROOT': path})
                self.assertEqual(p['WORK_ROOT'], path)

    def test_syncthing_data_must_not_contain_its_database_or_configuration(self):
        for path in ('/home', '/var', '/opt', '/srv', '/bin', '/sbin', '/lib', '/lib64',
                     '/bin/data', '/sbin/data', '/lib/data', '/lib64/data',
                     '/home/admin', '/home/admin/.config', '/var/lib/syncthing/data'):
            with self.subTest(path=path), self.assertRaises(g.InvalidConfiguration):
                self.prepare({'SYNCTHING_FOLDER_PATH': path})
        self.assertFalse(self.output.exists())
        for path in ('/opt/sync-data', '/srv/sync-data'):
            with self.subTest(dedicated_path=path):
                p = g.validate(g.DEFAULTS | {'SYNCTHING_FOLDER_PATH': path})
                self.assertEqual(p['SYNCTHING_FOLDER_PATH'], path)

    def test_grub_device_list_overrides_disko_without_legacy_device_duplication(self):
        self.prepare({'DISK_LAYOUT': 'single-disk-ext4-bios', 'BOOT_LOADER': 'grub'})
        text = (self.output / 'hosts/client/nixos/configuration.nix').read_text()
        self.assertIn('boot.loader.grub.devices = lib.mkForce [ "/dev/sda" ];', text)
        self.assertNotIn('boot.loader.grub.device =', text)

    def test_default_storage_is_role_derived_and_none_requires_hardware_input(self):
        self.assertEqual(g.validate(g.DEFAULTS)['DISK_LAYOUT'], 'single-disk-ext4')
        self.assertEqual(g.validate(g.DEFAULTS | {'HOST_ROLE': 'server', 'SSH_ALLOWED_CIDRS': '192.0.2.0/24'})['DISK_LAYOUT'], 'btrfs-worker-luks')
        with self.assertRaisesRegex(g.InvalidConfiguration, 'requires --hardware-configuration'):
            self.prepare({'DISK_LAYOUT': 'none'})
        self.assertFalse(self.output.exists())
        hardware = self.root / 'supplied-hardware.nix'
        hardware.write_text('{ ... }: { fileSystems."/" = { device = "/dev/example"; fsType = "ext4"; }; }\n')
        self.prepare({'DISK_LAYOUT': 'none'}, hardware_configuration=hardware)
        host = self.output / 'hosts/client/nixos'
        self.assertEqual((host / 'hardware-configuration.nix').read_bytes(), hardware.read_bytes())
        self.assertNotIn('./disk-layout.nix', (host / 'configuration.nix').read_text())

    def test_service_names_and_nix_build_ids_cannot_collide_with_accounts(self):
        for key in ('ADMIN_USER', 'WORKER_USER', 'WORK_GROUP'):
            for value in ('syncthing', 'docker', 'libvirtd', 'nixbld', 'nixbld1', 'nixbld32', 'kvm', 'networkmanager'):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(g.InvalidConfiguration, 'Reserved'):
                    self.prepare({key: value})
                self.assertFalse(self.output.exists())
        for key in ('ADMIN_UID', 'ADMIN_GID', 'WORKER_UID', 'WORKER_GID', 'WORK_GID'):
            for value in ('30000', '30001', '30032', '31000'):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(g.InvalidConfiguration, 'reserved Nix'):
                    self.prepare({key: value})
                self.assertFalse(self.output.exists())

    def test_rdp_can_supply_assistant_graphical_session(self):
        values = g.validate(g.DEFAULTS | {'ENABLE_RDP': 'true', 'ENABLE_SNAPSHOTS': 'true',
            'ENABLE_BTRFS_ASSISTANT': 'true', 'SSH_ALLOWED_CIDRS': '2001:db8::/64'})
        self.assertIn('common/packages/btrfs_assistant.nix', g.optional_imports(values))

    def test_charge_policy_is_optional_generic_and_rejects_removed_mode(self):
        self.assertEqual(g.validate(g.DEFAULTS)['CHARGE_LIMIT_MODE'], 'none')
        values = g.validate(g.DEFAULTS | {'CHARGE_LIMIT_MODE': 'thresholds',
            'CHARGE_START_THRESHOLD': '75', 'CHARGE_STOP_THRESHOLD': '80'})
        self.assertEqual(values['CHARGE_LIMIT_MODE'], 'thresholds')
        self.assertEqual((values['CHARGE_START_THRESHOLD'], values['CHARGE_STOP_THRESHOLD']), ('75', '80'))
        with self.assertRaisesRegex(g.InvalidConfiguration, 'CHARGE_LIMIT_MODE must be one of none, thresholds'):
            self.prepare({'CHARGE_LIMIT_MODE': 'lenovo-conservation'})
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(g.InvalidConfiguration, 'Charge start must be below stop'):
            g.validate(g.DEFAULTS | {'CHARGE_LIMIT_MODE': 'thresholds',
                'CHARGE_START_THRESHOLD': '80', 'CHARGE_STOP_THRESHOLD': '75'})

    def test_audio_streaming_without_desktop_includes_audio_dependency_once(self):
        values = g.validate(g.DEFAULTS | {'FEATURES': 'audio_airplay,audio_chromecast,audio,bluetooth'})
        imports = g.optional_imports(values)
        self.assertEqual(imports.count('../../../common/config/audio.nix'), 1)
        self.assertIn('common/network/default_bluetooth.nix', imports)

    def test_public_recipient_validation_does_not_accept_private_keys(self):
        with self.assertRaises(g.InvalidConfiguration):
            self.prepare(admin_age_recipient='AGE-SECRET-KEY-fixture', host_age_recipient='fixture')
        self.assertFalse(self.output.exists())

    def test_feature_listing_requires_no_output_and_cli_errors_are_explicit(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(g.main(['--list-features']), 0)
        self.assertIn('virtualization_tools', output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(g.main(['--template-dir', str(self.repo), '--output', str(self.output), '--set', 'UNKNOWN=x']), 2)
        self.assertFalse(self.output.exists())

    def test_default_acquisition_is_a_fresh_clone_then_new_schema_validation(self):
        before = self.hashes()
        calls = []
        original_run = subprocess.run
        def clone(command, **kwargs):
            if command[:2] != ['git', 'clone']:
                return original_run(command, **kwargs)
            self.assertTrue(kwargs['check'])
            self.assertEqual(command[:5], ['git', 'clone', '--depth', '1', '--branch'])
            self.assertEqual(command[5], 'new-structure')
            self.assertEqual(command[6:8], ['--', g.REPOSITORY])
            calls.append(command)
            import shutil
            shutil.copytree(self.repo, command[-1])
            return subprocess.CompletedProcess(command, 0)
        with patch.object(g.subprocess, 'run', side_effect=clone), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(g.main(['--branch', 'new-structure', '--output', str(self.output)]), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.hashes(), before)
        self.assertTrue((self.output / 'hosts/client/nixos/configuration.nix').is_file())


class LauncherRegressionTests(unittest.TestCase):
    """Exercise launcher control flow without real downloads or Nix execution."""

    def setUp(self):
        bash = shutil.which('bash')
        if not bash:
            self.skipTest('Bash is required for launcher tests')
        self.bash = str(Path(bash).resolve())
        self.temporary = tempfile.TemporaryDirectory(prefix='nixos-launcher-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / 'project space $ literal'
        self.project.mkdir()
        self.launcher = self.project / 'nixos_configs_generator.sh'
        shutil.copy2(PROJECT_ROOT / self.launcher.name, self.launcher)
        # The fake Nix shell does not evaluate this file.
        (self.project / 'runtime.nix').write_text('# synthetic launcher fixture\n')
        (self.project / 'nixos_configs_generator.py').write_text(
            'import json,os,shutil,sys\nfrom pathlib import Path\n'
            'Path(os.environ["CAPTURE"]).write_text(json.dumps({\n'
            ' "args":sys.argv[1:],\n'
            ' "tools":{name:shutil.which(name) for name in '
            '("git","nix-instantiate","nix-store")}}))\n')
        self.capture = self.root / 'captured.json'
        self.trace = self.root / 'runtime-calls'
        self.arguments_capture = self.root / 'runtime-arguments'
        self.download_trace = self.root / 'download-calls'
        self.home = self.root / 'home'
        self.home.mkdir()
        self.cache = self.root / 'cache'
        self.portable = self.cache / 'nixos-configurations-generator/nix-portable/v012/x86_64/nix-portable'
        self.payload = self.root / 'portable-payload'
        self.executable(self.payload, self.runtime_code('portable', portable=True))
        self.runtime_bin = self.root / 'runtime-bin'
        self.runtime_bin.mkdir()
        self.executable(self.runtime_bin / 'python3',
            '#!' + self.bash + '\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
        for name in ('git', 'nix-instantiate', 'nix-store'):
            self.executable(self.runtime_bin / name, '#!' + self.bash + '\nexit 0\n')
        self.empty = self.bin('empty')
        self.native = self.bin('native', native=True)

    def executable(self, path, code):
        path.write_text(code)
        path.chmod(0o755)

    def runtime_code(self, label, portable=False):
        prefix = '[[ "$1" == nix-shell ]] || exit 91\nshift\n' if portable else ''
        return ('#!' + self.bash + '\n'
            'printf "' + label + '\\n" >> "$TRACE"\n'
            'printf "%s\\0" "$@" > "$RUNTIME_ARGUMENTS"\n'
            'if [[ -n "${CASE_RUNTIME_FAILURE:-}" ]]; then exit "$CASE_RUNTIME_FAILURE"; fi\n'
            + prefix +
            'export PATH="$RUNTIME_BIN:$PATH"\n'
            'while (( $# )); do\n'
            '  if [[ "$1" == --run ]]; then\n'
            '    shift\n'
            '    exec ' + shlex.quote(self.bash) + ' -c "$1"\n'
            '  fi\n'
            '  shift\n'
            'done\nexit 90\n')

    def bin(self, name, native=False, downloader=None, host_python=False):
        target = self.root / name
        target.mkdir()
        # Supply ordinary host helpers, while Nix/Python/network are controlled.
        for command in ('bash', 'dirname', 'mkdir', 'mktemp', 'mv', 'rm', 'rmdir',
                        'chmod', 'cp', 'cat', 'awk', 'sed', 'head', 'stat', 'readlink', 'flock'):
            actual = shutil.which(command)
            if actual:
                (target / command).symlink_to(Path(actual).resolve())
        self.executable(target / 'uname', '#!' + self.bash + '\n'
            'if [[ "${1:-}" == -s ]]; then printf "%s\\n" "${CASE_OS:-Linux}"; '
            'else printf "%s\\n" "${CASE_ARCH:-x86_64}"; fi\n')
        self.executable(target / 'sha256sum', '#!' + self.bash + '\n'
            'if [[ "${CASE_BAD_CHECKSUM:-}" == 1 ]]; then\n'
            '  if [[ " $* " == *" --check "* || " $* " == *" -c "* ]]; then exit 1; fi\n'
            '  printf "%064d  %s\\n" 0 "${1:-fixture}"\n'
            'else\n'
            '  if [[ " $* " == *" --check "* || " $* " == *" -c "* ]]; then exit 0; fi\n'
            '  printf "%s  %s\\n" "$EXPECTED_PORTABLE_SHA" "${1:-fixture}"\n'
            'fi\n')
        if native:
            self.executable(target / 'nix-shell', self.runtime_code('native'))
        if host_python:
            # Host Python must not bypass the pinned Nix runtime.
            self.executable(target / 'python3', '#!' + self.bash + '\nexit 97\n')
        if downloader:
            self.downloader(target, downloader)
        return target

    def downloader(self, target, name):
        code = ('#!' + self.bash + '\n'
            'printf "' + name + '\\n" >> "$DOWNLOAD_TRACE"\n'
            'output=\n'
            'while (( $# )); do\n'
            '  case "$1" in\n'
            '    -o|--output|-O|--output-document) shift; output="$1" ;;\n'
            '    --output=*|--output-document=*) output="${1#*=}" ;;\n'
            '  esac\n'
            '  shift\n'
            'done\n'
            'if [[ -n "${CASE_DOWNLOAD_FAILURE:-}" ]]; then\n'
            '  [[ -z "$output" || "$output" == - ]] || printf "partial download" > "$output"\n'
            '  exit "$CASE_DOWNLOAD_FAILURE"\n'
            'fi\n'
            'if [[ -n "$output" && "$output" != - ]]; then cp -- "$PORTABLE_PAYLOAD" "$output"; '
            'else cat -- "$PORTABLE_PAYLOAD"; fi\n')
        self.executable(target / name, code)

    def cached_portable(self, architecture='x86_64'):
        self.portable = self.cache / ('nixos-configurations-generator/nix-portable/v012/' + architecture + '/nix-portable')
        self.portable.parent.mkdir(parents=True)
        shutil.copy2(self.payload, self.portable)

    def run_launcher(self, path, args=(), mode='auto', environment=None, relative=False):
        # The digest fake tests flow; real release hashes are checked separately.
        digests = re.findall(r'\b[0-9a-f]{64}\b', self.launcher.read_text())
        self.assertEqual(len(digests), 2, 'Launcher must pin a SHA256 for each portable architecture')
        architecture = (environment or {}).get('CASE_ARCH', 'x86_64')
        digest = digests[1 if architecture in ('aarch64', 'arm64') else 0]
        env = dict(PATH=str(path), HOME=str(self.home), XDG_CACHE_HOME=str(self.cache),
            CAPTURE=str(self.capture), TRACE=str(self.trace),
            RUNTIME_ARGUMENTS=str(self.arguments_capture), DOWNLOAD_TRACE=str(self.download_trace),
            RUNTIME_BIN=str(self.runtime_bin), PORTABLE_PAYLOAD=str(self.payload),
            EXPECTED_PORTABLE_SHA=digest, NIXOS_GENERATOR_RUNTIME=mode, NOSYSBASHRC='1')
        env.update(environment or {})
        launcher = self.launcher.relative_to(self.root) if relative else self.launcher
        return subprocess.run([self.bash, str(launcher), *args], env=env, cwd=self.root,
            text=True, capture_output=True, timeout=15)

    def assert_started(self, result, args, label):
        self.assertEqual(result.returncode, 0, result.stderr)
        captured = json.loads(self.capture.read_text())
        self.assertEqual(captured['args'], list(args))
        for name, path in captured['tools'].items():
            self.assertEqual(path, str(self.runtime_bin / name))
        self.assertEqual(self.trace.read_text().splitlines(), [label])
        arguments = self.arguments_capture.read_bytes().split(b'\0')
        self.assertIn(b'--pure', arguments)
        self.assertIn(b'NIX_CONF_DIR', arguments)
        self.assertIn(os.fsencode(self.project / 'runtime.nix'), arguments)

    def test_native_runtime_is_used_even_when_host_python_exists(self):
        path = self.bin('native-with-python', native=True, host_python=True)
        args = ['--help', 'literal argument']
        self.assert_started(self.run_launcher(path, args), args, 'native')
        self.assertFalse(self.download_trace.exists())

    def test_explicit_native_mode_does_not_fall_back_to_download(self):
        result = self.run_launcher(self.empty, mode='native')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('nix-shell', result.stderr)
        self.assertFalse(self.download_trace.exists())
        self.assertFalse(self.capture.exists())

    def test_invalid_runtime_mode_is_rejected(self):
        result = self.run_launcher(self.native, mode='invalid-runtime')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('NIXOS_GENERATOR_RUNTIME', result.stderr)
        self.assertFalse(self.trace.exists())

    def test_relative_launcher_handles_cdpath(self):
        args = ['--help', 'literal argument']
        result = self.run_launcher(self.native, args,
            environment={'CDPATH': str(self.root)}, relative=True)
        self.assert_started(result, args, 'native')

    def test_cached_portable_runtime_preserves_arguments(self):
        self.cached_portable()
        marker = self.root / 'injected'
        args = ['--set', 'WIFI_SSID=quote" $HOME $(printf hacked > "' + str(marker) + '")',
                '--output', 'directory with spaces', 'line1\nline2', 'single\'quote']
        self.assert_started(self.run_launcher(self.empty, args), args, 'portable')
        self.assertFalse(marker.exists())
        self.assertFalse(self.download_trace.exists())

    def test_explicit_portable_mode_ignores_available_native_nix(self):
        self.cached_portable()
        args = ['--list-features']
        self.assert_started(self.run_launcher(self.native, args, mode='portable'), args, 'portable')

    def test_arm64_host_alias_uses_aarch64_portable_cache(self):
        self.cached_portable(architecture='aarch64')
        args = ['--list-features']
        result = self.run_launcher(self.empty, args, environment={'CASE_ARCH': 'arm64'})
        self.assert_started(result, args, 'portable')
        self.assertFalse(self.download_trace.exists())

    def test_missing_portable_downloads_with_curl_then_reuses_cache(self):
        path = self.bin('with-curl', downloader='curl')
        args = ['--list-features']
        self.assert_started(self.run_launcher(path, args), args, 'portable')
        self.assertTrue(self.portable.is_file())
        self.assertEqual(self.download_trace.read_text().splitlines(), ['curl'])
        self.trace.unlink()
        self.assert_started(self.run_launcher(path, args), args, 'portable')
        self.assertEqual(self.download_trace.read_text().splitlines(), ['curl'])

    def test_missing_curl_can_use_wget(self):
        path = self.bin('with-wget', downloader='wget')
        args = ['--list-features']
        self.assert_started(self.run_launcher(path, args), args, 'portable')
        self.assertEqual(self.download_trace.read_text().splitlines(), ['wget'])

    def test_bad_cached_checksum_prevents_runtime_execution(self):
        self.cached_portable()
        result = self.run_launcher(self.empty, environment={'CASE_BAD_CHECKSUM': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())
        self.assertFalse(self.capture.exists())

    def test_bad_download_checksum_is_not_cached_or_executed(self):
        path = self.bin('bad-download', downloader='curl')
        result = self.run_launcher(path, environment={'CASE_BAD_CHECKSUM': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.portable.exists())
        self.assertFalse(self.trace.exists())
        self.assertFalse(self.capture.exists())

    def test_download_failure_never_executes_a_partial_runtime(self):
        path = self.bin('failed-download', downloader='curl')
        result = self.run_launcher(path, environment={'CASE_DOWNLOAD_FAILURE': '42'})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.portable.exists())
        self.assertFalse(self.trace.exists())
        self.assertEqual(list(self.portable.parent.glob('.download.*')), [])

    def test_absent_downloaders_report_a_prerequisite(self):
        result = self.run_launcher(self.empty)
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stderr, 'curl|wget')
        self.assertFalse(self.trace.exists())

    def test_unsupported_portable_architecture_is_rejected(self):
        result = self.run_launcher(self.empty, environment={'CASE_ARCH': 'riscv64'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('riscv64', result.stderr)
        self.assertFalse(self.download_trace.exists())
        self.assertFalse(self.trace.exists())

    def test_non_linux_host_is_rejected_before_bootstrap(self):
        result = self.run_launcher(self.native, environment={'CASE_OS': 'Darwin'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Linux', result.stderr)
        self.assertFalse(self.download_trace.exists())
        self.assertFalse(self.trace.exists())

    def test_relative_cache_directory_is_rejected(self):
        result = self.run_launcher(self.empty, environment={'XDG_CACHE_HOME': 'relative-cache'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('absolute', result.stderr)
        self.assertFalse(self.download_trace.exists())
        self.assertFalse(self.trace.exists())

    def test_runtime_failure_is_propagated(self):
        result = self.run_launcher(self.native, environment={'CASE_RUNTIME_FAILURE': '42'})
        self.assertEqual(result.returncode, 42)
        self.assertFalse(self.capture.exists())


@unittest.skipUnless(os.environ.get('NIXOS_TEMPLATE_TEST_DIR'), 'Set NIXOS_TEMPLATE_TEST_DIR for real-template integration tests')
class RealTemplateTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(os.environ['NIXOS_TEMPLATE_TEST_DIR']).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix='nixos-real-validation-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assertIsNotNone(shutil.which('nix-instantiate'),
            'Real-template validation requires nix-instantiate')
        self.source_hashes = self.hashes()
        self.addCleanup(lambda: self.assertEqual(self.hashes(), self.source_hashes))

    def hashes(self):
        return {str(p.relative_to(self.repo)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.repo.rglob('*') if p.is_file() and '.git' not in p.relative_to(self.repo).parts}

    def arguments(self, **changes):
        defaults = dict(hardware_configuration=None, secrets_dir=None, require_secrets=False,
            admin_age_recipient=None, host_age_recipient=None)
        return argparse.Namespace(**(defaults | changes))

    def reject(self, name, values, expected, **arguments):
        output = self.root / name
        with self.assertRaises(g.InvalidConfiguration) as error:
            g.prepare(self.repo, output, dict(HOSTNAME=name) | values, self.arguments(**arguments))
        self.assertRegex(str(error.exception), expected)
        self.assertFalse(output.exists(), 'Invalid configuration must never be published')
        self.assertEqual(list(self.root.glob('.nixos-prepare-*')), [])

    def test_unknown_font_and_dictionary_are_rejected_before_publication(self):
        self.reject('bad-font', {'DESKTOP': 'hyprland', 'FONT': 'missing_font_for_audit'},
            'missing_font_for_audit')
        self.reject('bad-dictionary', {'DICTIONARY': 'missing_dictionary_for_audit'},
            'missing_dictionary_for_audit')

    def test_localization_values_must_exist(self):
        cases = [
            ('bad-timezone', {'TIMEZONE': 'Mars/Olympus'}, 'Mars/Olympus'),
            ('bad-locale', {'DEFAULT_LOCALE': 'missing_LOCALE.UTF-8'}, 'missing_LOCALE'),
            ('bad-keyboard', {'KEY_LAYOUT': 'missing_keyboard_for_audit'}, 'missing_keyboard_for_audit'),
        ]
        for name, values, expected in cases:
            with self.subTest(parameter=name):
                self.reject(name, values, expected)

    def test_unsupported_cpu_and_feature_architectures_are_rejected(self):
        self.reject('arm-intel', {'PLATFORM': 'aarch64-linux', 'CPU_VENDOR': 'intel'},
            'CPU_VENDOR.*requires PLATFORM=x86_64-linux')
        self.reject('arm-steam', {'PLATFORM': 'aarch64-linux', 'FEATURES': 'gamestation_packages'},
            'gamestation_packages.*requires PLATFORM=x86_64-linux')

    def test_generic_arm_server_is_supported_without_building_it(self):
        output = self.root / 'arm-server'
        report = g.prepare(self.repo, output, {
            'HOSTNAME': 'arm-server', 'HOST_ROLE': 'server',
            'PLATFORM': 'aarch64-linux', 'CPU_VENDOR': 'generic',
            'SSH_ALLOWED_CIDRS': '192.0.2.0/24',
        }, self.arguments())
        self.assertEqual(report['validation']['status'], 'validated')
        self.assertEqual(report['validation']['platform'], 'aarch64-linux')
        self.assertTrue(report['validation']['system_derivation'].endswith('.drv'))

    def test_inline_missing_hardware_import_is_rejected(self):
        hardware = self.root / 'inline-hardware.nix'
        hardware.write_text('{ ... }: { imports = [ ./missing-hardware.nix ]; }\n')
        self.reject('bad-import', {'DISK_LAYOUT': 'none'}, 'missing-hardware',
            hardware_configuration=hardware)

    def test_hardware_without_root_filesystem_is_rejected(self):
        hardware = self.root / 'empty-hardware.nix'
        hardware.write_text('{ ... }: {}\n')
        self.reject('missing-root', {'DISK_LAYOUT': 'none'},
            '(?i)root file ?system|fileSystems.*(?:missing|does not|specif)',
            hardware_configuration=hardware)

    def test_supplied_hardware_must_match_the_requested_platform(self):
        hardware = self.root / 'different-platform.nix'
        hardware.write_text('{ ... }: {\n'
            ' nixpkgs.hostPlatform = "aarch64-linux";\n'
            ' fileSystems."/" = { device = "/dev/disk/by-label/ROOT"; fsType = "ext4"; };\n'
            ' fileSystems."/boot" = { device = "/dev/disk/by-label/BOOT"; fsType = "vfat"; };\n'
            '}\n')
        self.reject('different-hardware', {'DISK_LAYOUT': 'none', 'PLATFORM': 'x86_64-linux'},
            'supplied hardware platform differs from PLATFORM', hardware_configuration=hardware)

    def test_malformed_nix_hardware_is_rejected(self):
        hardware = self.root / 'invalid-hardware.nix'
        hardware.write_text('{ ... }: { broken = ; }\n')
        self.reject('bad-syntax', {'DISK_LAYOUT': 'none'}, '(?i)syntax error|unexpected.*;',
            hardware_configuration=hardware)

    def test_requested_snapshots_require_an_effective_snapshot_configuration(self):
        hardware = self.root / 'ext4-hardware.nix'
        hardware.write_text('{ ... }: {\n'
            ' fileSystems."/" = { device = "/dev/disk/by-label/ROOT"; fsType = "ext4"; };\n'
            ' fileSystems."/boot" = { device = "/dev/disk/by-label/BOOT"; fsType = "vfat"; };\n'
            '}\n')
        self.reject('plain-hardware', {'DISK_LAYOUT': 'none', 'ENABLE_SNAPSHOTS': 'true'},
            'ENABLE_SNAPSHOTS', hardware_configuration=hardware)

    def test_root_filesystem_can_be_declared_in_an_imported_module(self):
        # The extra module is a normal source input copied with the host tree.
        fixture_repo = self.root / 'template-copy'
        shutil.copytree(self.repo / 'nixos_configs_template', fixture_repo / 'nixos_configs_template')
        shutil.copyfile(self.repo / 'env.conf', fixture_repo / 'env.conf')
        extra = fixture_repo / 'nixos_configs_template/hosts/client/ABC/extra-root.nix'
        extra.write_text('{ ... }: {\n'
            ' fileSystems."/" = { device = "/dev/disk/by-label/ROOT"; fsType = "ext4"; };\n'
            ' fileSystems."/boot" = { device = "/dev/disk/by-label/BOOT"; fsType = "vfat"; };\n'
            '}\n')
        hardware = self.root / 'imported-root-hardware.nix'
        hardware.write_text('{ ... }: { imports = [ ./extra-root.nix ]; }\n')
        output = self.root / 'imported-root'
        report = g.prepare(fixture_repo, output, {'HOSTNAME': 'imported-root', 'DISK_LAYOUT': 'none'},
            self.arguments(hardware_configuration=hardware))
        self.assertEqual(report['validation']['status'], 'validated')
        self.assertTrue(report['validation']['system_derivation'].endswith('.drv'))
        self.assertTrue((output / report['configuration']).is_file())
        self.assertTrue((output / 'hosts/client/imported-root/extra-root.nix').is_file())

    def test_supplied_ciphertext_is_preserved_without_a_cryptographic_claim(self):
        # Structurally encrypted, deliberately unusable values; no real key is used.
        secrets = self.root / 'encrypted-input'
        secrets.mkdir()
        common = ('admin_hashedPassword: ENC[fixture]\nadmin_ssh_publicKey: ENC[fixture]\n'
            'sops:\n    mac: ENC[fixture]\n')
        host = ('worker_hashedPassword: ENC[fixture]\nworker_ssh_publicKey: ENC[fixture]\n'
            'sops:\n    mac: ENC[fixture]\n')
        (secrets / 'common.yaml').write_text(common)
        (secrets / 'cipher-server.yaml').write_text(host)
        output = self.root / 'cipher-server'
        report = g.prepare(self.repo, output, {
            'HOSTNAME': 'cipher-server', 'HOST_ROLE': 'server',
            'SSH_ALLOWED_CIDRS': '192.0.2.0/24',
        }, self.arguments(secrets_dir=secrets, require_secrets=True))
        self.assertEqual(report['validation']['status'], 'validated')
        self.assertFalse(report['validation']['secret_values_checked'])
        self.assertTrue(report['encrypted_secrets_supplied'])
        self.assertEqual((output / 'secrets/common.yaml').read_text(), common)
        self.assertEqual((output / 'secrets/cipher-server.yaml').read_text(), host)

    def test_client_server_desktop_feature_and_recipe_matrix(self):
        repo = Path(os.environ['NIXOS_TEMPLATE_TEST_DIR']).resolve()
        scenarios = {
            'client-kde': dict(DESKTOP='kde', FEATURES=','.join(g.FEATURES),
                DISK_LAYOUT='btrfs-subvolumes-luks', ENABLE_SNAPSHOTS='true',
                ENABLE_SCRUB='true', ENABLE_BTRFS_ASSISTANT='true', ENABLE_BATTERY='true'),
            'client-gnome': dict(DESKTOP='gnome', DISK_LAYOUT='single-disk-ext4'),
            'client-hyprland': dict(DESKTOP='hyprland', DISK_LAYOUT='single-disk-ext4'),
            'client-headless': dict(DESKTOP='none', DISK_LAYOUT='single-disk-ext4-bios', BOOT_LOADER='grub'),
            'server-full': dict(HOST_ROLE='server', SSH_ALLOWED_CIDRS='192.0.2.0/24,2001:db8::/64',
                DISK_LAYOUT='btrfs-worker-luks', ENABLE_SNAPSHOTS='true', ENABLE_SCRUB='true',
                ENABLE_RDP='true', ENABLE_BATTERY='true', ENABLE_WIFI='true', WIFI_SSID='Example "Network"',
                FEATURES='development,distrobox,virtualization_tools,libvirt', ENABLE_SYNCTHING='true',
                SYNCTHING_DEVICE_ID='AAAAAAA-' * 7 + 'AAAAAAA', SYNCTHING_ADDRESS='tcp://example.invalid:22000'),
            'server-lanzaboote': dict(HOST_ROLE='server', SSH_ALLOWED_CIDRS='192.0.2.0/24',
                DISK_LAYOUT='btrfs-worker-luks', BOOT_LOADER='lanzaboote'),
        }
        for recipe in (repo / 'nixos_configs_template/hosts/disk_configurations').rglob('*.nix'):
            scenarios['layout-' + recipe.stem.replace('_', '-')] = dict(
                DISK_LAYOUT=recipe.stem, BOOT_LOADER='grub' if 'bios' in recipe.stem else 'systemd-boot')
        args = argparse.Namespace(hardware_configuration=None, secrets_dir=None, require_secrets=False,
            admin_age_recipient=None, host_age_recipient=None)
        with tempfile.TemporaryDirectory(prefix='nixos-real-template-test-') as temporary:
            for name, values in scenarios.items():
                with self.subTest(name=name):
                    destination = Path(temporary) / name
                    report = g.prepare(repo, destination, dict(HOSTNAME=name) | values, args)
                    self.assertTrue((destination / report['configuration']).is_file())
                    self.assertEqual(report['validation']['status'], 'validated')
                    self.assertTrue(report['validation']['system_derivation'].endswith('.drv'))
                    self.assertFalse(report['validation']['secret_values_checked'])
                    self.assertFalse(report['encrypted_secrets_supplied'])
                    self.assertFalse((destination / 'secrets/common.yaml').exists())
                    self.assertFalse((destination / 'secrets' / (name + '.yaml')).exists())


if __name__ == '__main__':
    unittest.main()
