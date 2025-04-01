# NixOS Configurations Generator

> **Lingue disponibili**: [English](README.md) | [Italiano (corrente)](README.it.md)

**Nota**: Questo script dipende dai file presenti nel repository  
[another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template).  
Leggi il **README** presente in quel repository prima di utilizzare questo script.

Questo script facilita la modifica dei template dei file di configurazione di NixOS.  
Attualmente è piuttosto basilare e svolge alcune operazioni principali:

1. **Rinomina la cartella template**
   - Rinomina la cartella `nixos_configs_template` in `nixos_configs` all'interno della cartella `another_nixos_configurations_template`.

2. **Rinomina file template**
   - Cerca ricorsivamente tutti i file che terminano con `.template` nella cartella `nixos_configs`.  
   - Rinomina ciascun file rimuovendo il suffisso `.template`.

3. **Carica variabili d'ambiente**
   - Legge il file `env.conf`, che deve contenere variabili d'ambiente nel formato:
     ```bash
     export KEY=value
     ```
   - Rende queste variabili disponibili per la sostituzione nello script.

4. **Sostituisce variabili**
   - Usa `envsubst` per sostituire placeholder (es. `${VARIABLE}`) nei seguenti file:
     - `nixos_configs/common/gui/gnome.nix`
     - `nixos_configs/common/gui/kde.nix`
     - `nixos_configs/common/gui/hyprland.nix`
     - `nixos_configs/common/system.nix`

5. **Chiede l'hostname**
   - Richiede all'utente di inserire un hostname.  
   - Valida che l'hostname corrisponda a un pattern valido (senza caratteri non consentiti).

6. **Duplica cartella host**
   - Copia la cartella `ABC` dentro `nixos_configs/hosts/` e rinomina la copia usando l'hostname specificato.

7. **Imposta `BASEPATHNM`**
   - Calcola `BASEPATHNM` come la directory di lavoro corrente meno la cartella `nixos_configs_generator`.  
   - Sostituisce tutte le occorrenze di `${BASEPATHNM}` con questo valore nel file `nm_configurations.nix`.

8. **Sostituisce l'hostname nei file**
   - Sostituisce `${HOSTNAME}` con l'hostname inserito dall'utente in tutti i file nella nuova cartella host.

9. **Chiede username e password**
   - Chiede all'utente di inserire un nome utente e una password.  
   - Valida che il nome utente sia valido per sistemi Linux (senza caratteri non consentiti).

10. **Duplica cartella utente**
    - Copia la cartella `XYZ` dentro `nixos_configs/users/` e la rinomina con il nome utente specificato.  
    - Rinomina il file `user.nix` in `<username>.nix` nella nuova cartella utente.

11. **Sostituisce placeholder nel file utente**
    - Nel file `<username>.nix`, sostituisce:
      - `${USER}` con il nome utente fornito  
      - `${DICTIONARY}` con il valore `DICTIONARY` presente in `env.conf`  
      - `${BASEPATHUSER}` con il valore calcolato di `BASEPATHUSER`

Infine, lo script termina con `exit 0`.

---

## Utilizzo

1. **Scarica** i file dal repository [another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template) o lascia che sia lo script a effettuare automaticamente il clone del repository.
2. **Modifica** il file `env.conf` con i valori desiderati.
3. **Scarica** lo script `nixos_configs_generator.sh`.
4. **Verifica** che lo script abbia i permessi di esecuzione.
5. **Esegui** lo script e segui le istruzioni a schermo.

---

## Piani Futuri

Nelle prossime versioni prevedo di **ampliare** lo script per supportare ulteriori scelte e automatizzare ulteriori fasi della configurazione.