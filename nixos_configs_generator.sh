#!/usr/bin/env bash
set -euo pipefail
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

[[ "$(uname -s)" == Linux ]] || fail "This generator requires Linux."
[[ -f "$script_dir/runtime.nix" ]] || fail "Missing runtime.nix beside the launcher."
[[ -f "$script_dir/nixos_configs_generator.py" ]] || fail "Missing generator beside the launcher."

runtime_mode="${NIXOS_GENERATOR_RUNTIME:-auto}"
case "$runtime_mode" in
  auto|native|portable) ;;
  *) fail "NIXOS_GENERATOR_RUNTIME must be auto, native or portable." ;;
esac

# Quote every argument as shell data, including spaces and literal substitutions.
printf -v launch_command '%q ' exec python3 "$script_dir/nixos_configs_generator.py" "$@"
# Keep the store configuration supplied by nix-portable inside the pure shell.
shell_arguments=(
  --pure
  --keep NIX_CONF_DIR
  --keep NIX_CONFIG
  --keep NIX_REMOTE
  --keep NIX_USER_CONF_FILES
  --keep XDG_CACHE_HOME
  --keep http_proxy --keep https_proxy --keep no_proxy
  --keep HTTP_PROXY --keep HTTPS_PROXY --keep NO_PROXY
  "$script_dir/runtime.nix" --run "$launch_command"
)

if [[ "$runtime_mode" != portable ]] && command -v nix-shell >/dev/null 2>&1; then
  exec nix-shell "${shell_arguments[@]}"
fi
[[ "$runtime_mode" != native ]] || fail "Native mode requires nix-shell; use auto or portable when Nix is not installed."

# The upstream executable is downloaded separately and retains its own licenses.
portable_version=v012
portable_arch="$(uname -m)"
case "$portable_arch" in
  x86_64) portable_sha256=b409c55904c909ac3aeda3fb1253319f86a89ddd1ba31a5dec33d4a06414c72a ;;
  aarch64|arm64)
    portable_arch=aarch64
    portable_sha256=af41d8defdb9fa17ee361220ee05a0c758d3e6231384a3f969a314f9133744ea
    ;;
  *) fail "nix-portable supports only Linux x86_64 and aarch64; detected $portable_arch." ;;
esac
command -v sha256sum >/dev/null 2>&1 || fail "Portable bootstrap requires sha256sum (coreutils)."
cache_root="${XDG_CACHE_HOME:-${HOME:?HOME or XDG_CACHE_HOME must be set}/.cache}"
[[ "$cache_root" == /* ]] || fail "XDG_CACHE_HOME must be an absolute path."
portable_directory="$cache_root/nixos-configurations-generator/nix-portable/$portable_version/$portable_arch"
portable_binary="$portable_directory/nix-portable"
portable_url="https://github.com/DavHau/nix-portable/releases/download/$portable_version/nix-portable-$portable_arch"

has_expected_hash() {
  local digest
  digest="$(sha256sum < "$1")" || return 1
  [[ "${digest%% *}" == "$portable_sha256" ]]
}

if [[ -L "$portable_binary" || ( -e "$portable_binary" && ! -f "$portable_binary" ) ]]; then
  fail "The nix-portable cache entry must be a regular file: $portable_binary"
fi
if [[ ! -f "$portable_binary" ]] || ! has_expected_hash "$portable_binary"; then
  if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    fail "Downloading nix-portable requires curl or wget; no verified cached executable is available."
  fi
  mkdir -p -- "$portable_directory"
  download_file="$(mktemp "$portable_directory/.download.XXXXXXXX")"
  cleanup_download() {
    [[ -z "$download_file" ]] || rm -f -- "$download_file"
  }
  trap cleanup_download EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  printf 'Downloading nix-portable %s for %s.\n' "$portable_version" "$portable_arch" >&2
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --connect-timeout 30 \
      --output "$download_file" "$portable_url"
  else
    wget --https-only --timeout=30 --tries=3 --output-document="$download_file" "$portable_url"
  fi
  has_expected_hash "$download_file" || fail "nix-portable SHA256 mismatch; the downloaded file was not executed."
  chmod u+x -- "$download_file"
  mv -f -- "$download_file" "$portable_binary"
  download_file=''
  trap - EXIT INT TERM
fi
[[ -x "$portable_binary" ]] || chmod u+x -- "$portable_binary"
exec "$portable_binary" nix-shell "${shell_arguments[@]}"
