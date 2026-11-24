# NixOS Configurations Generator

> **Languages**: [English](README.md) | [Italiano](README.it.md)

This tool uses the files in the separate [another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template) repository to prepare a NixOS configuration in an isolated directory. It supports `hosts/client/ABC` and `hosts/server/ABC`, the base/client/server roles, a separate administrator and worker account, and independent optional features.

The launcher targets Linux on `x86_64` and `aarch64`, including machines without NixOS, Nix, Python or Git installed. It uses an available `nix-shell`, or obtains the pinned `nix-portable` release when Nix is absent. In both cases, [runtime.nix](runtime.nix) prepares Python, Git, Nix, Bash, coreutils and CA certificates from a fixed Nixpkgs 26.05 revision. Python uses only the standard library. The entire generator runs in this environment, including its Nix subprocesses and catalog reads; no packages are installed into the host system and no `sudo` is used.

Bootstrap requires Bash and standard coreutils, including `sha256sum`. When the portable executable is not cached, it also needs `curl` or `wget`. The launcher downloads `nix-portable` **v012** for the host architecture, verifies its fixed SHA256 and caches it under `${XDG_CACHE_HOME:-$HOME/.cache}/nixos-configurations-generator/nix-portable/v012/ARCH/nix-portable`. The upstream portable runtime keeps its state and store under `~/.nix-portable` by default; its `NP_LOCATION` setting can choose another parent directory. Internet access is needed for the initial downloads and whenever required sources or packages are not already cached. This bootstrap is not an offline bundle.

The runtime sets `NIX_PATH` to its pinned Nixpkgs source, so validation does not depend on a channel configured on the host. The template is still cloned separately from the chosen branch. The same launcher accepts `--help`, `--list-features` and generation arguments; preparing its environment may download dependencies even for help or feature listing.

Select the bootstrap with the environment variable `NIXOS_GENERATOR_RUNTIME`:

| Value | Behavior |
|---|---|
| `auto` (default) | Use a `nix-shell` found on the host; otherwise use nix-portable. |
| `native` | Require the host's `nix-shell`; fail if it is unavailable. |
| `portable` | Use nix-portable even when the host has Nix installed. |

For example, `NIXOS_GENERATOR_RUNTIME=portable ./nixos_configs_generator.sh --help` selects the portable environment. This is a launcher variable, not a template parameter for `--set` or `env.conf`. Each mode enters the declared Nix environment; an installed host Python does not bypass it.

The output directory is created in a single operation using Linux `renameat2`, without overwriting an existing destination, even if another process creates it concurrently. Validation evaluates NixOS without building or activating an operating system. The tool never runs Disko, installs NixOS, activates a service or calls `nixos-rebuild`.

## Prepare a client

```bash
./nixos_configs_generator.sh \
  --template-dir /path/to/another_nixos_configurations_template \
  --output /path/to/new-client \
  --set HOSTNAME=desk --set HOST_ROLE=client --set DESKTOP=kde \
  --set FEATURES=development,photo_editing
```

The output directory must not already exist; its parent must exist. Source repositories, existing output directories and supplied inputs are never edited. Files are prepared and validated in a temporary directory; only after all checks pass is the entire directory moved to the path specified by `--output`. No shell code from `env.conf` is executed.

Without `--template-dir`, the tool makes a fresh temporary clone of the template repository, using branch `26.05` or `--branch NAME`. It accepts the documented client/server template structure.

## Prepare a server

```bash
./nixos_configs_generator.sh \
  --template-dir /path/to/another_nixos_configurations_template \
  --output /path/to/new-server \
  --set HOST_ROLE=server --set HOSTNAME=node \
  --set SSH_ALLOWED_CIDRS=192.0.2.0/24,2001:db8::/64 \
  --set DISK_LAYOUT=btrfs-worker-luks --set DISK_DEVICE=/dev/disk/by-id/EXAMPLE \
  --set ENABLE_SNAPSHOTS=true --set ENABLE_SCRUB=true \
  --set ENABLE_RDP=true --set ENABLE_BATTERY=true \
  --set FEATURES=development,distrobox,virtualization_tools,libvirt
```

Example addresses and disk identifiers must be replaced for the destination. `HOST_ROLE=server` selects the server category. Servers require `DESKTOP=none`; Xfce/RDP is optional and separate. Server battery policy stays in its host rather than importing the client power policy. Empty build/zram parameters derive as client `4/0`, `30/lz4`, or server `2/4`, `50/zstd`. Explicit values override these defaults.

The administrator files keep the names `admin.nix` and `client.nix`, under `users/ADMIN_USER/`. A server additionally receives `users/WORKER_USER/worker.nix`. Account names, UID/GID collisions and unsafe paths are rejected. Service/group names such as syncthing, docker, libvirtd and nixbld (including numbered build accounts) are reserved. UID/GID values must be 1000..60000 and must stay outside the reserved Nix build range 30000..31000. Host imports are rewritten to the selected account directories.

Work paths are normalized before checking them. `WORK_ROOT` must not overlap system directories, account homes or Syncthing state; the Syncthing data folder cannot contain or be contained by its configuration/database directory. The default `/srv/worker/data` remains separate from service state.

## Options and public parameters

Assignments in the template's `env.conf` are defaults. `--env-file PATH` overrides them, and repeated `--set KEY=VALUE` overrides both. Unknown names, duplicate assignments inside one env file, invalid enums, booleans, networks, identifiers and numerical values fail without creating the output directory. Values are read as data, without shell expansion. Public values only: never pass passwords, PSKs, hashes or private keys through parameters.

`--list-features` prints available optional modules without cloning the template or producing configuration output. `FEATURES` is a comma-separated list: `photo_editing`, `video_editing`, `development`, `recording`, `container_tools`, `distrobox`, `virtualization_tools`, `extra_packages_services`, `kde_packages`, `gamestation_packages`, `external_monitor`, `unstable_temporary_packages`, `docker`, `libvirt`, `audio`, `audio_airplay`, `audio_chromecast`, `bluetooth`. Distrobox imports Docker itself; virtualization tools do not enable libvirt automatically. Audio streaming features also import the audio module when no local desktop supplies it.

`DESKTOP` accepts `none`, `kde`, `gnome`, `hyprland`. Independent flags cover RDP, WiFi, Syncthing, Btrfs snapshots/scrub/Assistant and battery policy. Btrfs Assistant requires snapshots and a local or RDP desktop. Snapshots and scrub with a selected disk recipe require Btrfs; supplied hardware must also provide an effective snapshot configuration when snapshots are requested. ARM targets require `CPU_VENDOR=generic`; Steam is supported only on `x86_64-linux`.

`CHARGE_LIMIT_MODE` accepts `none` (default, no charge limits) or `thresholds` (optional generic start/stop percentages). The threshold mode requires the start percentage to be below the stop percentage; hardware-specific settings belong in the host configuration.

`DISK_LAYOUT` defaults to an empty value, selecting `single-disk-ext4` for clients or `btrfs-worker-luks` for servers. Explicit `none` requires `--hardware-configuration` with the destination filesystem declarations. Otherwise use the basename of a recipe under `hosts/disk_configurations/`, without `.nix`. All source recipes remain available in the output; the selected one is copied to the host as `disk-layout.nix`. BIOS recipes require GRUB, UEFI recipes require systemd-boot or Lanzaboote. `/dev/sda` normalizes to `sda`, and `/dev/disk/by-id/...` to `disk/by-id/...`, because recipes supply `/dev/` themselves. No disk recipe is executed.

`SSH_ALLOWED_CIDRS` and `RDP_ALLOWED_CIDRS` accept comma-separated IPv4/IPv6 CIDRs without IPv6 scope identifiers. Servers require SSH CIDRs. RDP requires CIDRs and inherits SSH CIDRs when its own list is empty. Client SSH keeps its module's native firewall behavior if SSH CIDRs are empty; nonempty CIDRs enable the host filter. The service port remains defined by `SSH_PORT` or `RDP_PORT` and filters follow it. Enabled SSH/RDP services must use different ports and cannot use Syncthing's ports `22222` or `8843` when Syncthing is enabled.

WiFi SSIDs are escaped as Nix string data; control characters and enabled-network SSIDs longer than 32 UTF-8 bytes are rejected. Syncthing has local/global discovery and relay behavior disabled in the examples: a nonempty device ID requires a fixed `tcp://`, `tcp4://` or `tcp6://` address including a valid port. Empty device IDs do not create a remote folder/device. Server workspace folder paths must equal `WORK_ROOT/data`; clients may choose another absolute folder path. These declarations do not open incoming Syncthing ports.

| Parameter | Default before role-derived values |
|---|---|
| `HOST_ROLE` | `client` |
| `HOSTNAME` | `nixos` |
| `DESKTOP` | `none` |
| `FEATURES` | `(empty)` |
| `ADMIN_USER` | `admin` |
| `ADMIN_UID` | `1000` |
| `ADMIN_GID` | `1000` |
| `WORKER_USER` | `worker` |
| `WORKER_UID` | `1100` |
| `WORKER_GID` | `1100` |
| `WORK_GROUP` | `worker-work` |
| `WORK_GID` | `1200` |
| `WORK_ROOT` | `/srv/worker` |
| `TIMEZONE` | `Europe/Rome` |
| `DEFAULT_LOCALE` | `it_IT.UTF-8` |
| `KEY_LAYOUT` | `it` |
| `FONT` | `nerd-fonts.code-new-roman` |
| `NIXOS_VERSION` | `26.05` |
| `SSH_PORT` | `22` |
| `SSH_ALLOWED_CIDRS` | `(empty)` |
| `DICTIONARY` | `it_IT` |
| `BASEPATHUSER` | `/home` |
| `ENABLE_RDP` | `false` |
| `RDP_PORT` | `3389` |
| `RDP_ALLOWED_CIDRS` | `(empty)` |
| `ENABLE_WIFI` | `false` |
| `WIFI_SSID` | `(empty)` |
| `ENABLE_SYNCTHING` | `false` |
| `SYNCTHING_DEVICE_ID` | `(empty)` |
| `SYNCTHING_ADDRESS` | `dynamic` |
| `SYNCTHING_FOLDER_PATH` | `(empty)` |
| `SYNCTHING_FOLDER_ID` | `work-data` |
| `ENABLE_SNAPSHOTS` | `false` |
| `ENABLE_SCRUB` | `false` |
| `ENABLE_BTRFS_ASSISTANT` | `false` |
| `ENABLE_BATTERY` | `false` |
| `MAX_JOBS` | `(empty)` |
| `BUILD_CORES` | `(empty)` |
| `ENABLE_ZRAM` | `true` |
| `ZRAM_PERCENT` | `(empty)` |
| `ZRAM_ALGORITHM` | `(empty)` |
| `DISK_LAYOUT` | `(empty)` |
| `DISK_DEVICE` | `sda` |
| `SWAP_SIZE` | `16G` |
| `BOOT_LOADER` | `systemd-boot` |
| `CPU_VENDOR` | `generic` |
| `PLATFORM` | `x86_64-linux` |
| `CHARGE_LIMIT_MODE` | `none` |
| `CHARGE_START_THRESHOLD` | `75` |
| `CHARGE_STOP_THRESHOLD` | `80` |

## Hardware and encrypted secrets

`--hardware-configuration PATH` copies a supplied hardware declaration into the selected host. Without it, output includes a generic hardware example; review it for the real machine. `DISK_LAYOUT=none` is rejected without `--hardware-configuration`; the supplied declaration must include the destination filesystems. The generated recipe defaults provide a root filesystem without executing any storage operation. `PLATFORM` is always recorded as the host default; conflicting target architectures in supplied hardware are rejected. Selecting GRUB also requires explicitly choosing a BIOS recipe; the empty layout default is UEFI.

Without `--secrets-dir`, output deliberately retains only `secrets/*.yaml.template` and `.sops.yaml.template`. `PREPARATION.md` marks secret setup incomplete. Follow the output's SOPS documentation, fill the examples locally and encrypt them before creating the active YAML files. No plaintext secret file is automatically created, and no password or private key is requested or generated.

For already encrypted inputs, pass:

```bash
./nixos_configs_generator.sh \
  --template-dir /path/to/template --output /path/to/new-output \
  --set HOSTNAME=desk \
  --secrets-dir /path/to/encrypted-inputs --require-secrets
```

The directory must contain `common.yaml` and `HOSTNAME.yaml`. The tool checks an encrypted SOPS envelope, encrypted top-level values, and required keys: common `admin_hashedPassword`, `admin_ssh_publicKey`; server host `worker_hashedPassword`, `worker_ssh_publicKey`; optional WiFi `wifi_env`. It copies only those two YAML files, never decrypts them, and cannot verify cryptographic authenticity, recipients or whether their values are operationally correct. It rejects plaintext or missing required fields. `--require-secrets` makes the supplied encrypted files mandatory.

Optionally pass both `--admin-age-recipient age1...` and `--host-age-recipient age1...` to prepare `.sops.yaml` from its template using public recipients. Otherwise configure that file manually. Private keys remain outside the repository and output. The target must already have its proper SSH host identity for SOPS decryption; this tool does not create or install it.

## Output and validation

The output contains only the selected host category, explicit account directories, shared modules and recipes. Source parameter templates become `.nix` files; SOPS templates retain their suffix. Declared uppercase placeholders are rendered, Nix's own interpolation is preserved, and unknown/unresolved placeholders abort preparation. Documentation examples stay generic and can still refer to the original source examples.

Before moving the generated files to the directory specified by `--output`, the generator parses every Nix file and evaluates the selected host’s NixOS configuration. This checks actual module imports, option types, assertions, platform compatibility and selected package attributes. Timezone, locale and keymap values are checked against the selected nixpkgs catalogs. A failed check leaves no output directory. Fetching pinned modules or obtaining catalog data may require network access or an existing Nix cache. Missing catalog outputs are obtained through Nix substitutes, with local and remote builders disabled.

For evaluation, SOPS file paths are overridden with a synthetic `{}` placeholder outside the output. Its temporary source directory is removed after validation; its harmless Nix store copy can remain cached. Actual secret values are never decrypted or checked by Nix evaluation; supplied encrypted YAML receives only the structural checks described above. Verify recipients, authenticity and decryption separately on the destination. `preparation.json` records public choices, the selected nixpkgs and validation results. Its system derivation refers only to validation with placeholder secret paths and is not an installation artifact. `PREPARATION.md` records remaining setup work. Successful evaluation does not replace a build or runtime checks on the target.

## Tests

The automated tests are kept under [tests/](tests/README.md). Their guide describes what they check, how to run the unit and real-template suites, and which prerequisites each requires. Tests are development files: the generator does not run them or copy them into its output.

## Sources and licenses

The portable bootstrap uses [nix-portable](https://github.com/DavHau/nix-portable), developed by DavHau, from release [v012](https://github.com/DavHau/nix-portable/releases/tag/v012). Its implementation is distributed under the [MIT license](https://raw.githubusercontent.com/DavHau/nix-portable/v012/LICENSE), copyright (c) 2021 DavHau. The launcher downloads the original upstream executable; neither that executable nor upstream implementation code is vendored in this repository.

This generator retains its [CC BY-NC 4.0 license](LICENSE). That license covers the generator's own code and documentation; nix-portable and the programs it contains or downloads retain their respective licenses. They are not relicensed under CC BY-NC. Redistribution of upstream code or executables must preserve the applicable notices and comply with the licenses of the included components.
