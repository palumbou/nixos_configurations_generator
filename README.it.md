# NixOS Configurations Generator

> **Lingue disponibili**: [English](README.md) | [Italiano (corrente)](README.it.md)

**Nota**: Questo script dipende dai file presenti nel repository
[another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template).
Leggi il **README** presente in quel repository prima di utilizzare questo script.

Questo script automatizza la personalizzazione dei template dei file di configurazione di NixOS.
È allineato al branch **26.05** del repository template; è possibile selezionare un branch
diverso passandolo come primo argomento:

```bash
./nixos_configs_generator.sh 25.11
```

Svolge le seguenti operazioni:

1. **Recupera il repository template**
   - Usa la cartella `another_nixos_configurations_template` se già presente accanto allo script (aggiornandola facoltativamente al branch selezionato), altrimenti clona il branch selezionato da GitHub oppure chiede il percorso di una copia scaricata manualmente.

2. **Rinomina la cartella template**
   - Rinomina la cartella `nixos_configs_template` in `nixos_configs` all'interno della cartella `another_nixos_configurations_template`.

3. **Rinomina file template**
   - Cerca ricorsivamente tutti i file che terminano con `.template` nella cartella `nixos_configs`.
   - Rinomina ciascun file rimuovendo il suffisso `.template`.
   - I template relativi a sops (`.sops.yaml.template` e `secrets/common.yaml.template`) mantengono di proposito il suffisso: rinominarli/copiarli fa parte del setup dei segreti descritto in `common/config/SECRETS.it.md` del template.

4. **Carica variabili d'ambiente**
   - Legge il file `env.conf` (nella root del repository template), che deve contenere variabili d'ambiente nel formato:
     ```bash
     export KEY=value
     ```
   - Verifica che tutte le variabili usate dai template siano definite e le rende disponibili per la sostituzione.

5. **Sostituisce variabili**
   - Sostituisce (tramite `sed`) solo le variabili elencate - così le interpolazioni `${...}` proprie di Nix restano intatte - nei seguenti file:
     - `nixos_configs/common/config/system.nix`: `${TIMEZONE}`, `${DEFAULT_LOCALE}`, `${KEY_LAYOUT}`, `${CONSOLE_KEY_LAYOUT}`
     - `nixos_configs/common/gui/hyprland.nix`: `${FONT}`
     - `nixos_configs/common/packages/default_packages_services.nix`: `${SSH_PORT}`
   - Sostituisce `${DISK_DEVICE}` in tutti i template disco (Disko) presenti in `nixos_configs/hosts/disk_configurations/`.

6. **Chiede l'hostname**
   - Richiede all'utente di inserire un hostname (il valore `HOSTNAME` di `env.conf` viene proposto come default).
   - Valida che l'hostname corrisponda a un pattern valido (senza caratteri non consentiti).

7. **Duplica cartella host**
   - Copia la cartella `ABC` dentro `nixos_configs/hosts/` e rinomina la copia usando l'hostname specificato.
   - Nella nuova cartella host sostituisce:
     - `${HOSTNAME}` con l'hostname scelto (`configuration.nix`)
     - `${NIXOS_VERSION}` con il valore di `env.conf` (`system.stateVersion` in `configuration.nix`)
     - `${DISK_DEVICE}` con il valore di `env.conf` (esempio di configurazione disco)

8. **Layout disco opzionale**
   - Permette facoltativamente di scegliere uno dei layout disco (Disko) da `nixos_configs/hosts/disk_configurations/` (ext4/btrfs, con o senza LUKS) e lo copia nella nuova cartella host.

9. **Chiede username e password**
   - Chiede all'utente di inserire un nome utente (il valore `USER` di `env.conf` viene proposto come default) e lo valida come nome utente Linux valido.
   - Facoltativamente chiede la password (con conferma), genera un hash SHA-512 usando `mkpasswd`, `openssl` o `python3` (quello disponibile) e lo salva come valore di `user_hashedPassword` in `secrets/common.yaml.template`. L'hash non entra mai nei file `.nix`: all'attivazione `user.nix` lo legge dal file `secrets/common.yaml` cifrato con sops, che viene creato da quel template durante il setup dei segreti (vedi `common/config/SECRETS.it.md` del template).

10. **Duplica cartella utente**
    - Copia la cartella `XYZ` dentro `nixos_configs/users/` e la rinomina con il nome utente specificato.
    - Rinomina il file `user.nix` in `<username>.nix` nella nuova cartella utente.
    - Nel file `<username>.nix` sostituisce `${USER}`, `${DICTIONARY}` e `${BASEPATHUSER}`.

11. **Importa l'utente nell'host**
    - Facoltativamente sostituisce l'import `../../users/XYZ/user.nix` nel `configuration.nix` dell'host con il nuovo file utente.

Infine, lo script stampa i passaggi manuali rimanenti e termina con `exit 0`.

---

## Requisiti

- `bash`
- `git` (opzionale: serve solo per clonare/aggiornare automaticamente il repository template)
- uno tra `mkpasswd`, `openssl` o `python3` (solo se lasci che sia lo script a generare l'hash della password; nota che il modulo `crypt` usato dal fallback `python3` è stato rimosso in Python 3.13)

---

## Utilizzo

1. **Scarica** i file dal repository [another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template) (branch **26.05**) o lascia che sia lo script a effettuare automaticamente il clone del repository.
2. **Modifica** il file `env.conf` con i valori desiderati.
3. **Scarica** lo script `nixos_configs_generator.sh`.
4. **Verifica** che lo script abbia i permessi di esecuzione.
5. **Esegui** lo script (eventualmente passando il branch del template come primo argomento) e segui le istruzioni a schermo.

---

## Passaggi manuali dopo lo script

Lo script prepara i file, ma alcune scelte restano manuali (vedi l'**HOWTO** del template):

- abilitare gli import desiderati in `nixos_configs/hosts/<hostname>/configuration.nix` (GUI: Gnome/KDE/Hyprland, gaming, workstation, Syncthing, monitor esterno, GRUB, layout disco Disko, Secure Boot, ...);
- impostare il device del bootloader (o la configurazione Disko/hardware) per la propria macchina;
- configurare i segreti seguendo `common/config/SECRETS.it.md` del template: generare la chiave age admin, rinominare `.sops.yaml.template` in `.sops.yaml` e inserire le chiavi, poi copiare `secrets/common.yaml.template` in `secrets/common.yaml`, compilare i valori (PSK WiFi, hash della password se non generato dallo script) e cifrarlo con sops;
- dichiarare le reti WiFi di ogni host nel suo `nm_configurations.nix` (le PSK sono referenziate come variabili `$WIFI_*` dal file dei segreti cifrato);
- personalizzare `syncthing.nix`, i dotfiles e gli altri moduli opzionali.

---

## Piani Futuri

Nelle prossime versioni prevedo di **ampliare** lo script per supportare ulteriori scelte e automatizzare ulteriori fasi della configurazione.
