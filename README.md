# NixOS Configurations Generator

> **Available languages**: [English (current)](README.md) | [Italiano](README.it.md)

**Notice**: This script depends on the files in the
[another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template) repository.
Please read the **README** there before proceeding with this script.

This script automates the customization of the NixOS configuration file templates.
It targets the **25.11** branch of the template repository; a different branch can be
selected by passing it as the first argument:

```bash
./nixos_configs_generator.sh 25.05
```

It performs the following tasks:

1. **Get the Template Repository**
   - Uses the `another_nixos_configurations_template` folder if it is already present next to the script (optionally updating it to the selected branch), otherwise clones the selected branch from GitHub or asks for the path of a manually downloaded copy.

2. **Rename Template Folder**
   - Renames the `nixos_configs_template` folder to `nixos_configs` inside the `another_nixos_configurations_template` folder.

3. **Rename Template Files**
   - Recursively searches for all files ending with `.template` inside the `nixos_configs` folder.
   - Renames each file by removing the `.template` suffix.

4. **Load Environment Variables**
   - Reads the `env.conf` file (in the template repository root), which should contain environment variables in the format:
     ```bash
     export KEY=value
     ```
   - Checks that every variable used by the templates is defined, and makes them available for substitution.

5. **Substitute Variables**
   - Substitutes (via `sed`) only the listed variables — so Nix's own `${...}` interpolations are left untouched — in the following files:
     - `nixos_configs/common/config/system.nix`: `${TIMEZONE}`, `${DEFAULT_LOCALE}`, `${KEY_LAYOUT}`, `${CONSOLE_KEY_LAYOUT}`
     - `nixos_configs/common/gui/hyprland.nix`: `${FONT}`
     - `nixos_configs/common/packages/default_packages_services.nix`: `${SSH_PORT}`
   - Replaces `${DISK_DEVICE}` in all the disk (Disko) templates under `nixos_configs/hosts/disk_configurations/`.

6. **Prompt for HOSTNAME**
   - Asks the user to input a hostname (the `HOSTNAME` value from `env.conf` is offered as default).
   - Validates that the hostname matches a valid pattern for hostnames (no invalid characters, etc.).

7. **Duplicate Host Folder**
   - Copies the `ABC` folder inside `nixos_configs/hosts/` and renames the copy to the specified hostname.
   - In the new host folder, replaces:
     - `${HOSTNAME}` with the chosen hostname (`configuration.nix`)
     - `${NIXOS_VERSION}` with the value from `env.conf` (`system.stateVersion` in `configuration.nix`)
     - `${BASEPATHNM}` with the value from `env.conf` (`nm_configurations.nix`)
     - `${DISK_DEVICE}` with the value from `env.conf` (disk configuration example)

8. **Optional Disk Layout**
   - Optionally lets the user pick one of the disk (Disko) layouts from `nixos_configs/hosts/disk_configurations/` (ext4/btrfs, with or without LUKS) and copies it into the new host folder.

9. **Prompt for Username and Password**
   - Asks the user to input a username (the `USER` value from `env.conf` is offered as default) and validates it as a valid Linux username.
   - If `USER_PWD` in `env.conf` still contains the `<HASHED_PASSWORD>` placeholder, asks for the password (with confirmation) and generates a SHA-512 hash using `mkpasswd`, `openssl` or `python3` (whichever is available). If `USER_PWD` already contains a real hash, it is used as-is and no password is asked.

10. **Duplicate User Folder**
    - Copies the `XYZ` folder inside `nixos_configs/users/` and renames it to match the specified username.
    - Renames `user.nix` to `<username>.nix` within that new folder.
    - Within `<username>.nix`, substitutes `${USER}`, `${DICTIONARY}`, `${BASEPATHUSER}` and `${USER_PWD}`.

11. **Import the User into the Host**
    - Optionally replaces the `../../users/XYZ/user.nix` import in the host `configuration.nix` with the new user file.

Finally, the script prints the remaining manual steps and exits with `exit 0`.

---

## Requirements

- `bash`
- `git` (optional: only needed to clone/update the template repository automatically)
- one of `mkpasswd`, `openssl` or `python3` (only if the password hash is not already set in `env.conf`; note that the `crypt` module used by the `python3` fallback was removed in Python 3.13)

---

## Usage

1. **Download** the files from the [another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template) repository (branch **25.11**) or let the script automatically clone the repository.
2. **Edit** the `env.conf` file with the desired values.
3. **Download** the `nixos_configs_generator.sh` script.
4. **Check** that it has execution permissions.
5. **Run** the script (optionally passing the template branch as first argument) and follow the on-screen instructions.

---

## Manual Steps After the Script

The script prepares the files, but some choices remain manual (see the template **HOWTO**):

- enable the desired imports in `nixos_configs/hosts/<hostname>/configuration.nix` (GUI: Gnome/KDE/Hyprland, gaming, workstation, Syncthing, external monitor, GRUB, Disko disk layout, Secure Boot, ...);
- set the bootloader device (or the Disko/hardware configuration) for your machine;
- customize `syncthing.nix`, `nm_configurations.nix`, dotfiles and the other optional modules.

---

## Future Plans

In upcoming releases, I plan to **expand** the script to support more choices and automate additional configuration steps.
