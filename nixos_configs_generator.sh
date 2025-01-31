#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Prompt for the absolute path of the "another_nixos_configurations_template" folder
read -p "Enter the absolute path of 'another_nixos_configurations_template': " ANCT_URL
if [[ ! -d "$ANCT_URL" ]]; then
  echo "Invalid path. Directory does not exist. Exiting."
  exit 1
fi

# Change directory to the specified path
cd "$ANCT_URL"

# Rename the folder "nixos_configs_template" to "nixos_configs"
mv nixos_configs_template nixos_configs

# Remove the ".template" suffix from all files in the directory tree
find nixos_configs -type f -name "*.template" | while read -r file; do
  mv "$file" "${file%.template}"
done

# Replace variables in specific files using envsubst and the env.conf file
# Ensure the env.conf file contains variables in the format "export KEY=value"
. env.conf  # Source the env.conf file directly

for file in nixos_configs/common/gui/gnome.nix \
            nixos_configs/common/gui/kde.nix \
            nixos_configs/common/gui/hyprland.nix \
            nixos_configs/common/system.nix; do
  envsubst < "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
done

# Prompt for the hostname and validate it as a valid hostname
read -p "Enter the hostname: " HOSTNAME
if [[ ! "$HOSTNAME" =~ ^[a-zA-Z0-9][-a-zA-Z0-9]{0,62}$ ]]; then
  echo "Invalid hostname. Exiting."
  exit 1
fi

# Copy the "ABC" folder to the new hostname folder
cp -r nixos_configs/hosts/ABC "nixos_configs/hosts/$HOSTNAME"

# Replace the variable ${BASEURL} in nm_configurations.nix
BASEURL=$(pwd | sed 's:/nixos_configs_generator::')
sed -i "s|\${BASEURL}|$BASEURL|g" "nixos_configs/hosts/$HOSTNAME/nm_configurations.nix"

# Replace the variable ${HOSTNAME} in the new hostname folder files
find "nixos_configs/hosts/$HOSTNAME" -type f -exec sed -i "s|\${HOSTNAME}|$HOSTNAME|g" {} \;

# Prompt for the username and validate it as a valid Linux username
read -p "Enter the username: " username
if [[ ! "$username" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
  echo "Invalid username. Exiting."
  exit 1
fi

# Prompt for the user's password
read -sp "Enter the password for $username: " password
echo
USER_PWD=$(echo "$password" | mkpasswd -m sha-512)

# Copy the "XYZ" folder to the new username folder
cp -r nixos_configs/users/XYZ "nixos_configs/users/$username"

# Rename the file "user.nix" to "<username>.nix"
mv "nixos_configs/users/$username/user.nix" "nixos_configs/users/$username/${username}.nix"

# Replace variables ${USER}, ${DICTIONARY}, ${BASEURL}, and ${USER_PWD} in the renamed file
sed -i "s|\${USER}|$username|g" "nixos_configs/users/$username/${username}.nix"
dictionary=$(grep "^export DICTIONARY" env.conf | cut -d'=' -f2)
sed -i "s|\${DICTIONARY}|$dictionary|g" "nixos_configs/users/$username/${username}.nix"
sed -i "s|\${BASEURL}|$BASEURL|g" "nixos_configs/users/$username/${username}.nix"
sed -i "s|\${USER_PWD}|$USER_PWD|g" "nixos_configs/users/$username/${username}.nix"

# Ask if the user should be imported into the host configuration
read -p "Do you want to import the user into the host '$HOSTNAME' configuration? (y/n): " import_user
if [[ "$import_user" =~ ^[Yy]$ ]]; then
  sed -i "s|../../users/XYZ/user.nix|../../users/$username/${username}.nix|g" "nixos_configs/hosts/$HOSTNAME/configuration.nix"
  echo "User $username successfully imported into $HOSTNAME configuration."
else
  echo "Skipping user import into $HOSTNAME configuration."
fi

# Notify the user of successful completion
echo "Script completed successfully."
exit 0
