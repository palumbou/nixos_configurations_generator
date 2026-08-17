#!/bin/bash

# Exit immediately if a command exits with a non-zero status,
# treat unset variables as errors and propagate failures in pipelines
set -euo pipefail

# Define the repository URL, directory and branch.
# The branch matches a template release (e.g. 26.05); it can be overridden
# by passing it as the first argument: ./nixos_configs_generator.sh 25.11
REPO_URL="https://github.com/palumbou/another_nixos_configurations_template"
REPO_DIR="another_nixos_configurations_template"
REPO_BRANCH="${1:-26.05}"

# Check if the repository directory exists at the same level as the script
if [[ -d "$REPO_DIR" ]]; then
  echo "The repository '$REPO_DIR' was found at the same level as the script."
  read -p "Do you want to update it to the latest '$REPO_BRANCH' branch? (y/n): " update_repo
  if [[ "$update_repo" =~ ^[Yy]$ ]]; then
    # Check if git is installed before proceeding with the update
    if ! command -v git &> /dev/null; then
      echo "Error: git is not installed on this system. Cannot update the repository."
      echo "Using the existing repository without updating."
      ANCT_URL="$(pwd)/$REPO_DIR"
    else
      # Check if the directory is a valid git repository
      if [[ -d "$REPO_DIR/.git" ]]; then
        echo "Updating the repository..."
        cd "$REPO_DIR"
        git fetch origin
        git checkout "$REPO_BRANCH"
        git pull origin "$REPO_BRANCH"
        cd ..
        ANCT_URL="$(pwd)/$REPO_DIR"
        echo "Repository updated to the latest version of branch '$REPO_BRANCH'."
      else
        echo "Error: '$REPO_DIR' is not a valid git repository. Exiting."
        exit 1
      fi
    fi
  else
    ANCT_URL="$(pwd)/$REPO_DIR"
    echo "Using the existing repository without updating."
  fi
else
  # Check if git is installed before proceeding
  if ! command -v git &> /dev/null; then
    echo "Error: git is not installed on this system."
    echo "You can manually download the repository (branch '$REPO_BRANCH') from: $REPO_URL"
    read -p "Enter the absolute path of 'another_nixos_configurations_template': " ANCT_URL
    if [[ ! -d "$ANCT_URL" ]]; then
      echo "Invalid path. Directory does not exist. Exiting."
      exit 1
    fi
  else
    # Ask the user if they want to download the repository automatically
    read -p "Do you want to download 'another_nixos_configurations_template' (branch '$REPO_BRANCH') from GitHub automatically? (y/n): " download_repo
    if [[ "$download_repo" =~ ^[Yy]$ ]]; then
      # Clone the requested branch of the repository using git
      echo "Cloning the repository using git..."
      git clone -b "$REPO_BRANCH" "$REPO_URL"
      ANCT_URL="$(pwd)/$REPO_DIR"
      echo "Repository (branch '$REPO_BRANCH') downloaded to: $ANCT_URL"
    else
      # Prompt for the absolute path of the "another_nixos_configurations_template" folder
      echo "You can manually download the repository (branch '$REPO_BRANCH') from: $REPO_URL"
      read -p "Enter the absolute path of 'another_nixos_configurations_template': " ANCT_URL
      if [[ ! -d "$ANCT_URL" ]]; then
        echo "Invalid path. Directory does not exist. Exiting."
        exit 1
      fi
    fi
  fi
fi

# Change directory to the specified path
cd "$ANCT_URL"

# Rename the folder "nixos_configs_template" to "nixos_configs" if it exists
if [[ -d "nixos_configs_template" ]]; then
  mv nixos_configs_template nixos_configs
fi
if [[ ! -d "nixos_configs" ]]; then
  echo "Error: 'nixos_configs' folder not found in '$ANCT_URL'. Exiting."
  exit 1
fi

# Remove the ".template" suffix from all files in the directory tree.
# The sops-related templates keep their suffix on purpose: renaming/copying
# them is part of the secrets setup described in common/config/SECRETS.md
# (and it avoids creating a plaintext secrets/common.yaml automatically).
find nixos_configs -type f -name "*.template" \
  ! -name ".sops.yaml.template" ! -path "*/secrets/*" | while read -r file; do
  mv "$file" "${file%.template}"
done

# Load the variables from the env.conf file.
# Ensure the env.conf file contains variables in the format "export KEY=value".
if [[ ! -f "env.conf" ]]; then
  echo "Error: 'env.conf' not found in '$ANCT_URL'. Exiting."
  exit 1
fi
. env.conf  # Source the env.conf file directly

# Verify that every variable used by the templates is defined in env.conf
for var in KEY_LAYOUT FONT SSH_PORT TIMEZONE DEFAULT_LOCALE CONSOLE_KEY_LAYOUT \
           NIXOS_VERSION HOSTNAME DISK_DEVICE USER DICTIONARY BASEPATHUSER; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: variable '$var' is not defined in env.conf. Exiting."
    exit 1
  fi
done

# Replace variables in the common configuration files.
# Only the listed variables are substituted in each file, so Nix's own
# "${...}" interpolations are left untouched.
substitute_vars() {
  local file="$1"
  shift
  local sed_args=()
  local var
  for var in "$@"; do
    sed_args+=(-e "s|\${$var}|${!var}|g")
  done
  sed -i "${sed_args[@]}" "$file"
}

substitute_vars nixos_configs/common/config/system.nix TIMEZONE DEFAULT_LOCALE KEY_LAYOUT CONSOLE_KEY_LAYOUT
substitute_vars nixos_configs/common/gui/hyprland.nix FONT
substitute_vars nixos_configs/common/packages/default_packages_services.nix SSH_PORT

# Replace the target disk device in the shared disk (Disko) configuration templates
find nixos_configs/hosts/disk_configurations -type f -name "*.nix" \
  -exec sed -i "s|\${DISK_DEVICE}|$DISK_DEVICE|g" {} \;

# Prompt for the hostname (env.conf value as default) and validate it as a valid hostname
read -p "Enter the hostname [$HOSTNAME]: " input_hostname
HOSTNAME="${input_hostname:-$HOSTNAME}"
if [[ ! "$HOSTNAME" =~ ^[a-zA-Z0-9][-a-zA-Z0-9]{0,62}$ ]]; then
  echo "Invalid hostname. Exiting."
  exit 1
fi

# Copy the "ABC" folder to the new hostname folder
if [[ -d "nixos_configs/hosts/$HOSTNAME" ]]; then
  echo "Error: 'nixos_configs/hosts/$HOSTNAME' already exists. Exiting."
  exit 1
fi
cp -r nixos_configs/hosts/ABC "nixos_configs/hosts/$HOSTNAME"

# Replace the variables in the new host folder:
# ${HOSTNAME} and ${NIXOS_VERSION} in configuration.nix and ${DISK_DEVICE}
# in the disk configuration example
find "nixos_configs/hosts/$HOSTNAME" -type f -exec sed -i \
  -e "s|\${HOSTNAME}|$HOSTNAME|g" \
  -e "s|\${NIXOS_VERSION}|$NIXOS_VERSION|g" \
  -e "s|\${DISK_DEVICE}|$DISK_DEVICE|g" {} \;

# Optionally copy a disk (Disko) layout from "hosts/disk_configurations" into the host folder
read -p "Do you want to copy a disk (Disko) layout into the host '$HOSTNAME' folder? (y/n): " copy_layout
if [[ "$copy_layout" =~ ^[Yy]$ ]]; then
  mapfile -t layouts < <(find nixos_configs/hosts/disk_configurations -type f -name "*.nix" | sort)
  echo "Available disk layouts:"
  select layout in "${layouts[@]}"; do
    if [[ -n "${layout:-}" ]]; then
      cp "$layout" "nixos_configs/hosts/$HOSTNAME/"
      echo "Copied '$(basename "$layout")' into 'nixos_configs/hosts/$HOSTNAME/'."
      echo "Remember to import it (together with the Disko module) in 'configuration.nix' if you plan to use it."
      break
    else
      echo "Invalid selection. Please try again."
    fi
  done
fi

# Prompt for the username (env.conf value as default) and validate it as a valid Linux username
read -p "Enter the username [$USER]: " input_username
username="${input_username:-$USER}"
if [[ ! "$username" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
  echo "Invalid username. Exiting."
  exit 1
fi

# The user's password hash no longer lives in the .nix files: it is read at
# activation from the sops-encrypted secrets/common.yaml (key
# "user_hashedPassword", see common/config/SECRETS.md). Optionally generate
# the hash now and store it in the plaintext secrets/common.yaml.template,
# ready to be copied and encrypted during the secrets setup.
read -p "Do you want to generate the password hash for '$username' now and store it in 'secrets/common.yaml.template'? (y/n): " gen_hash
if [[ "$gen_hash" =~ ^[Yy]$ ]]; then
  # Prompt for the user's password twice and validate
  while true; do
    read -sp "Enter the password for $username: " password1
    echo
    read -sp "Re-enter the password for $username: " password2
    echo
    # Check if the two passwords match
    if [[ "$password1" == "$password2" ]]; then
      break  # Exit the loop if passwords match
    else
      echo "Error: Passwords do not match. Please try again."
    fi
  done
  # Generate the hashed password using mkpasswd, openssl, or python3
  if command -v mkpasswd &> /dev/null; then
    # Check if mkpasswd supports the -m option for SHA-512
    if mkpasswd -m sha-512 <<< "test" &> /dev/null; then
      USER_PWD=$(echo "$password1" | mkpasswd -m sha-512)
    else
      echo "Warning: mkpasswd does not support the required options. Trying openssl..."
      if command -v openssl &> /dev/null; then
        USER_PWD=$(echo -n "$password1" | openssl passwd -6 -stdin)
      elif command -v python3 &> /dev/null; then
        echo "Warning: openssl not found. Falling back to python3..."
        USER_PWD=$(printf '%s' "$password1" | python3 -c "import crypt, sys; print(crypt.crypt(sys.stdin.read(), crypt.mksalt(crypt.METHOD_SHA512)))")
      else
        echo "Error: No suitable tool found to generate the password hash. Exiting."
        exit 1
      fi
    fi
  elif command -v openssl &> /dev/null; then
    echo "Warning: mkpasswd not found. Using openssl..."
    USER_PWD=$(echo -n "$password1" | openssl passwd -6 -stdin)
  elif command -v python3 &> /dev/null; then
    echo "Warning: mkpasswd and openssl not found. Using python3..."
    USER_PWD=$(printf '%s' "$password1" | python3 -c "import crypt, sys; print(crypt.crypt(sys.stdin.read(), crypt.mksalt(crypt.METHOD_SHA512)))")
  else
    echo "Error: No suitable tool found to generate the password hash. Exiting."
    exit 1
  fi
  # The hash may contain characters that are special in a sed replacement: escape them
  escaped_pwd=$(printf '%s' "$USER_PWD" | sed 's/[&|\\]/\\&/g')
  sed -i "s|^user_hashedPassword:.*|user_hashedPassword: $escaped_pwd|" nixos_configs/secrets/common.yaml.template
  echo "Hash stored in 'nixos_configs/secrets/common.yaml.template'."
  echo "Remember to copy it to 'secrets/common.yaml' and encrypt it with sops (see common/config/SECRETS.md)."
else
  echo "Skipping: generate it later with 'mkpasswd -m sha-512' and store it with 'sops secrets/common.yaml' (see common/config/SECRETS.md)."
fi

# Copy the "XYZ" folder to the new username folder
if [[ -d "nixos_configs/users/$username" ]]; then
  echo "Error: 'nixos_configs/users/$username' already exists. Exiting."
  exit 1
fi
cp -r nixos_configs/users/XYZ "nixos_configs/users/$username"

# Rename the file "user.nix" to "<username>.nix"
mv "nixos_configs/users/$username/user.nix" "nixos_configs/users/$username/${username}.nix"

# Replace variables ${USER}, ${DICTIONARY} and ${BASEPATHUSER} in the renamed
# file (the password hash is not substituted here: user.nix reads it from the
# sops-encrypted secrets file at activation)
sed -i \
  -e "s|\${USER}|$username|g" \
  -e "s|\${DICTIONARY}|$DICTIONARY|g" \
  -e "s|\${BASEPATHUSER}|$BASEPATHUSER|g" \
  "nixos_configs/users/$username/${username}.nix"

# Ask if the user should be imported into the host configuration
read -p "Do you want to import the user into the host '$HOSTNAME' configuration? (y/n): " import_user
if [[ "$import_user" =~ ^[Yy]$ ]]; then
  sed -i "s|../../users/XYZ/user.nix|../../users/$username/${username}.nix|g" "nixos_configs/hosts/$HOSTNAME/configuration.nix"
  echo "User $username successfully imported into $HOSTNAME configuration."
else
  echo "Skipping user import into $HOSTNAME configuration."
fi

# Notify the user of successful completion and of the remaining manual steps
echo "Script completed successfully."
echo
echo "Remaining manual steps (see the template HOWTO for details):"
echo "  - review 'nixos_configs/hosts/$HOSTNAME/configuration.nix' and enable the desired"
echo "    imports (GUI: Gnome/KDE/Hyprland, gaming, workstation, Syncthing, external"
echo "    monitor, GRUB, Disko disk layout, Secure Boot, ...)"
echo "  - set the bootloader device or the Disko/hardware configuration for your machine"
echo "  - set up the secrets (see 'nixos_configs/common/config/SECRETS.md'): generate the"
echo "    admin age key, rename '.sops.yaml.template' to '.sops.yaml' and fill in the keys,"
echo "    then copy 'secrets/common.yaml.template' to 'secrets/common.yaml', fill in the"
echo "    values (WiFi PSKs, password hash) and encrypt it with sops"
echo "  - declare the WiFi networks of the host in 'nm_configurations.nix'"
exit 0
