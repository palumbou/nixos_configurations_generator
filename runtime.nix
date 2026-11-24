let
  # Fixed 26.05 source for both runtime tools and generated-configuration validation.
  source = builtins.fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/0dc498bfe49baeb18b0f9891e800b53bb2603193.tar.gz";
    sha256 = "09m91kcd36jg2lvvrfy0qwk7frsjn84hfn497bax4rmcrfmj7zdk";
  };
  pkgs = import source { config = {}; overlays = []; };
in
pkgs.mkShellNoCC {
  packages = with pkgs; [ python3 gitMinimal nix bashInteractive coreutils cacert ];
  NIX_PATH = "nixpkgs=${source}";
  SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
  NIX_SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
}
