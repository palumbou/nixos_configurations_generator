# NixOS Configurations Generator

**Notice**: This script depends on the files in the  
[another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template) repository.  
Please read the **README** there before proceeding with this script.

This script facilitates modifying NixOS configuration files templates.  
At the moment, it is quite basic and performs a few main tasks:

1. **Rename Template Folder**  
   - Renames the `nixos_configs_template` folder to `nixos_configs`.

2. **Rename Template Files**  
   - Recursively searches for all files ending with `.template` inside the `nixos_configs` folder.  
   - Renames each file by removing the `.template` suffix.

3. **Load Environment Variables**  
   - Reads the `env.conf` file, which should contain environment variables in the format:  
     ```bash
     export KEY=value
     ```  
   - Makes these variables available for substitution in the script.

4. **Substitute Variables**  
   - Uses `envsubst` to replace placeholders (e.g., `${VARIABLE}`) in the following files:
     - `nixos_configs/common/gui/gnome.nix`
     - `nixos_configs/common/gui/kde.nix`
     - `nixos_configs/common/gui/hyprland.nix`
     - `nixos_configs/common/system.nix`

5. **Prompt for HOSTNAME**  
   - Asks the user to input a hostname.  
   - Validates that the hostname matches a valid pattern for hostnames (no invalid characters, etc.).

6. **Duplicate Host Folder**  
   - Copies the `ABC` folder inside `nixos_configs/hosts/` and renames the copy to the specified hostname.

7. **Set `BASEURL`**  
   - Calculates `BASEURL` as the current working directory minus the `nixos_configs_generator` folder.  
   - Replaces all occurrences of `${BASEURL}` with this value in `nm_configurations.nix`.

8. **Replace Hostname in Files**  
   - Replaces `${HOSTNAME}` with the input hostname in all files within the new host folder.

9. **Prompt for Username**  
   - Asks the user to input a username and the password.
   - Validates that the username is valid for Linux systems (no invalid characters, etc.).

10. **Duplicate User Folder**  
    - Copies the `XYZ` folder inside `nixos_configs/users/` and renames it to match the specified username.  
    - Renames `user.nix` to `<username>.nix` within that new folder.

11. **Replace Placeholders in User File**  
    - Within `<username>.nix`, substitutes:
      - `${USER}` with the provided username  
      - `${DICTIONARY}` with the `DICTIONARY` value from `env.conf`  
      - `${BASEURL}` with the calculated `BASEURL`

Finally, the script exits with `exit 0`.

---

## Usage

1. **Download** the files from the  
   [another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template) repository.  
2. **Edit** the `env.conf` file with the desired values.  
3. **Download** the `nixos_configs_generator.sh` script.  
4. **Check** that it has execution permissions.  
5. **Run** the script and follow the on-screen instructions.

---

## Future Plans

In upcoming releases, I plan to **expand** the script to support more choices and automate additional configuration steps.
