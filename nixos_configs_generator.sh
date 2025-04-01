#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Define the repository URL and directory
REPO_URL="https://github.com/palumbou/another_nixos_configurations_template"
REPO_DIR="another_nixos_configurations_template"

# Check if the repository directory exists at the same level as the script
if [[ -d "$REPO_DIR" ]]; then
  echo "The repository '$REPO_DIR' was found at the same level as the script."
  read -p "Do you want to update it? (y/n): " update_repo
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
        git pull
        cd ..
        ANCT_URL="$(pwd)/$REPO_DIR"
        echo "Repository updated to the latest version."
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
    echo "You can manually download the repository from: $REPO_URL"
    read -p "Enter the absolute path of 'another_nixos_configurations_template': " ANCT_URL
    if [[ ! -d "$ANCT_URL" ]]; then
      echo "Invalid path. Directory does not exist. Exiting."
      exit 1
    fi
  else
    # Ask the user if they want to download the repository automatically
    read -p "Do you want to download 'another_nixos_configurations_template' from GitHub automatically? (y/n): " download_repo
    if [[ "$download_repo" =~ ^[Yy]$ ]]; then
      # Clone the repository using git
      echo "Cloning the repository using git..."
      git clone "$REPO_URL"
      ANCT_URL="$(pwd)/$REPO_DIR"
      echo "Repository downloaded to: $ANCT_URL"
    else
      # Prompt for the absolute path of the "another_nixos_configurations_template" folder
      echo "You can manually download the repository from: $REPO_URL"
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
            nixos_configs/common/config/system.nix; do
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

# Replace the variable ${BASEPATHNM} in nm_configurations.nix
BASEPATHNM=$(pwd | sed 's:/nixos_configs_generator::')
sed -i "s|\${BASEPATHNM}|$BASEPATHNM|g" "nixos_configs/hosts/$HOSTNAME/nm_configurations.nix"

# Replace the variable ${HOSTNAME} in the new hostname folder files
find "nixos_configs/hosts/$HOSTNAME" -type f -exec sed -i "s|\${HOSTNAME}|$HOSTNAME|g" {} \;

# Prompt for the username and validate it as a valid Linux username
read -p "Enter the username: " username
if [[ ! "$username" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
  echo "Invalid username. Exiting."
  exit 1
fi

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
      USER_PWD=$(python3 -c "import crypt; print(crypt.crypt('$password1', crypt.mksalt(crypt.METHOD_SHA512)))")
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
  USER_PWD=$(python3 -c "import crypt; print(crypt.crypt('$password1', crypt.mksalt(crypt.METHOD_SHA512)))")
else
  echo "Error: No suitable tool found to generate the password hash. Exiting."
  exit 1
fi

# Copy the "XYZ" folder to the new username folder
cp -r nixos_configs/users/XYZ "nixos_configs/users/$username"

# Rename the file "user.nix" to "<username>.nix"
mv "nixos_configs/users/$username/user.nix" "nixos_configs/users/$username/${username}.nix"

# Replace variables ${USER}, ${DICTIONARY}, ${BASEPATHUSER}, and ${USER_PWD} in the renamed file
sed -i "s|\${USER}|$username|g" "nixos_configs/users/$username/${username}.nix"
dictionary=$(grep "^export DICTIONARY" env.conf | cut -d'=' -f2)
sed -i "s|\${DICTIONARY}|$dictionary|g" "nixos_configs/users/$username/${username}.nix"
sed -i "s|\${BASEPATHUSER}|$BASEPATHUSER|g" "nixos_configs/users/$username/${username}.nix"
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
