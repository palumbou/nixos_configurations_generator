# Generator tests

> **Languages**: [English](README.md) | [Italiano](README.it.md)

This directory contains automated tests for the generator. They check that changes do not break existing functionality and are kept in the repository with the source code. They are not required to run the generator and are not copied into generated NixOS configurations.

## What is checked

- Parameter parsing, names and IDs, paths, CIDRs, escaping and optional features.
- Output isolation, immutable inputs, atomic creation of the output directory and rejection of invalid inputs.
- Structural checks on synthetic encrypted SOPS inputs; no real secrets or decryption.
- The shell launcher, using controlled fake executables to exercise dependency handling and argument preservation without downloading packages.
- Actual NixOS validation against the standalone template, including client/server profiles, disk recipes, ARM, imports, root filesystems, localization and invalid package attributes.

The small filesystem fixtures replace only the Nix semantic-validation boundary. `RealTemplateTests` uses the real validator and is skipped unless `NIXOS_TEMPLATE_TEST_DIR` is set. A successful fixture-only run does not establish that real NixOS evaluation works.

## Run from the repository root

Use Python 3.10 or newer. The launcher cases also need Bash and basic system tools. The real-template cases need a working Nix environment, compatible nixpkgs, and any required source/catalog downloads or cache entries.

```bash
python3 -m unittest discover -s tests -t . -v
```

With native Nix, the pinned tool environment can provide Python:

```bash
nix-shell --pure runtime.nix --run 'python3 -m unittest discover -s tests -t . -v'
```

To include actual NixOS evaluation, point the environment variable at the template repository containing `env.conf` and `nixos_configs_template/`:

```bash
nix-shell --pure runtime.nix --run \
  'NIXOS_TEMPLATE_TEST_DIR=/path/to/another_nixos_configurations_template python3 -m unittest discover -s tests -t . -v'
```

The same suite can be selected as a module with `python3 -m unittest -v tests.test_generator`, or run directly with `python3 tests/test_generator.py`. Paths to the generator and launcher are resolved from this repository, rather than the current directory.

Tests work in temporary directories. They do not run Disko, build or activate an operating system, create VMs, or alter real credentials. Actual Nix evaluation can write harmless synthetic inputs and derivations to the Nix store and can require network/cache access.
