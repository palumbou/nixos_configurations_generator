# NixOS Configurations Generator

> **Lingue**: [English](README.md) | [Italiano](README.it.md)

Questo strumento usa i file del repository separato [another_nixos_configurations_template](https://github.com/palumbou/another_nixos_configurations_template) per preparare una configurazione NixOS in una directory isolata. Supporta `hosts/client/ABC`, `hosts/server/ABC`, i ruoli base/client/server, amministratore e account operativo separati e funzionalità opzionali indipendenti.

Il launcher è pensato per Linux su `x86_64` e `aarch64`, anche su macchine senza NixOS, Nix, Python o Git installati. Usa un `nix-shell` disponibile oppure recupera la release fissata di `nix-portable` quando Nix è assente. In entrambi i casi, [runtime.nix](runtime.nix) prepara Python, Git, Nix, Bash, coreutils e certificati CA da una revisione fissata di Nixpkgs 26.05. Python usa soltanto la libreria standard. L'intero generatore viene eseguito in questo ambiente, compresi i processi Nix e la lettura dei cataloghi; non vengono installati pacchetti nel sistema ospitante e non viene usato `sudo`.

Per il bootstrap servono Bash e le normali coreutils, incluso `sha256sum`. Quando l'eseguibile portabile non è già in cache, serve anche `curl` oppure `wget`. Il launcher scarica `nix-portable` **v012** per l'architettura ospitante, verifica il suo SHA256 fissato e lo conserva sotto `${XDG_CACHE_HOME:-$HOME/.cache}/nixos-configurations-generator/nix-portable/v012/ARCH/nix-portable`. Il runtime upstream mantiene stato e store in `~/.nix-portable` per impostazione predefinita; la sua variabile `NP_LOCATION` permette di scegliere un'altra directory padre. La connessione Internet serve per i download iniziali e quando sorgenti o pacchetti necessari non sono già in cache. Questo bootstrap non è un pacchetto offline.

Il runtime imposta `NIX_PATH` sulla propria sorgente Nixpkgs fissata, quindi le verifiche non dipendono dai canali configurati sull'host. Il template continua a essere scaricato separatamente dal branch scelto. Lo stesso launcher accetta `--help`, `--list-features` e gli argomenti di generazione; preparare l'ambiente può richiedere download anche per la guida o l'elenco delle funzionalità.

La variabile d'ambiente `NIXOS_GENERATOR_RUNTIME` sceglie il bootstrap:

| Valore | Comportamento |
|---|---|
| `auto` (predefinito) | Usa un `nix-shell` trovato sull'host; altrimenti usa nix-portable. |
| `native` | Richiede il `nix-shell` dell'host; si interrompe se non è disponibile. |
| `portable` | Usa nix-portable anche quando Nix è già installato sull'host. |

Per esempio, `NIXOS_GENERATOR_RUNTIME=portable ./nixos_configs_generator.sh --help` sceglie l'ambiente portabile. È una variabile del launcher, non un parametro del template per `--set` o `env.conf`. Ogni modalità entra nell'ambiente Nix dichiarato; un Python installato sull'host non lo sostituisce.

La cartella di output viene creata con un’unica operazione tramite `renameat2` di Linux, senza sovrascrivere una destinazione esistente, anche se creata contemporaneamente da un altro processo. La verifica valuta NixOS senza compilare o attivare un sistema operativo. Lo strumento non esegue Disko, installazioni, attivazioni o `nixos-rebuild`.

## Client e server

```bash
./nixos_configs_generator.sh \
  --template-dir /percorso/another_nixos_configurations_template \
  --output /percorso/nuovo-client \
  --set HOSTNAME=desk --set HOST_ROLE=client --set DESKTOP=kde \
  --set FEATURES=development,photo_editing

./nixos_configs_generator.sh \
  --template-dir /percorso/another_nixos_configurations_template \
  --output /percorso/nuovo-server \
  --set HOST_ROLE=server --set HOSTNAME=node \
  --set SSH_ALLOWED_CIDRS=192.0.2.0/24,2001:db8::/64 \
  --set DISK_LAYOUT=btrfs-worker-luks --set DISK_DEVICE=/dev/disk/by-id/EXAMPLE \
  --set ENABLE_SNAPSHOTS=true --set ENABLE_SCRUB=true \
  --set ENABLE_RDP=true --set ENABLE_BATTERY=true \
  --set FEATURES=development,distrobox,virtualization_tools,libvirt
```

La directory di output deve essere nuova e la sua directory padre deve esistere. Sorgenti e input rimangono invariati. I file vengono preparati e verificati in una cartella temporanea; solo se i controlli passano, l’intera cartella viene spostata nel percorso indicato con `--output`. Non viene eseguito codice shell da `env.conf`.

Senza `--template-dir` viene scaricata una copia temporanea nuova del repository, dal branch `26.05` o da `--branch NOME`. Viene accettata la struttura client/server documentata.

Sostituisci gli indirizzi e identificativi disco di esempio con quelli della destinazione. `HOST_ROLE=server` sceglie la categoria server. Un server usa `DESKTOP=none`; Xfce/RDP resta una scelta separata. La politica batteria server appartiene all'host, senza importare quella client. Parametri build/zram vuoti derivano dal ruolo: client `4/0`, `30/lz4`; server `2/4`, `50/zstd`. Valori espliciti prevalgono.

I file dell'amministratore conservano i nomi `admin.nix` e `client.nix`, dentro `users/ADMIN_USER/`. Il server aggiunge `users/WORKER_USER/worker.nix`. Nomi non validi, collisioni UID/GID e percorsi non sicuri vengono rifiutati. Sono riservati nomi di servizi/gruppi come syncthing, docker, libvirtd e nixbld, inclusi gli account build numerati. UID/GID devono essere tra 1000 e 60000, escludendo la fascia Nix build riservata 30000..31000. Gli import puntano alle directory scelte.

I percorsi di lavoro vengono normalizzati prima dei controlli. `WORK_ROOT` non può sovrapporsi a directory di sistema, home degli account o stato Syncthing; la cartella dati Syncthing non può contenere la configurazione/database né esserne contenuta. Il percorso predefinito `/srv/worker/data` resta separato dallo stato del servizio.

## Parametri e scelte

I valori di `env.conf` nel template sono le impostazioni iniziali. `--env-file PERCORSO` li sovrascrive; ogni `--set CHIAVE=VALORE` prevale su entrambi. I file vengono letti come dati, senza espansioni shell. Nomi sconosciuti, assegnazioni duplicate nello stesso file, enum, booleani, reti o valori numerici non validi interrompono la preparazione senza creare la cartella di output. Usa soltanto dati pubblici: niente password, hash, PSK o chiavi private nei parametri.

`--list-features` elenca i moduli senza scaricare il template né produrre configurazioni. `FEATURES` è una lista separata da virgole: `photo_editing`, `video_editing`, `development`, `recording`, `container_tools`, `distrobox`, `virtualization_tools`, `extra_packages_services`, `kde_packages`, `gamestation_packages`, `external_monitor`, `unstable_temporary_packages`, `docker`, `libvirt`, `audio`, `audio_airplay`, `audio_chromecast`, `bluetooth`. Distrobox importa Docker; gli strumenti di virtualizzazione non abilitano automaticamente libvirt. Le funzionalità audio di streaming importano anche il modulo audio quando non è fornito da un desktop locale.

`DESKTOP` accetta `none`, `kde`, `gnome`, `hyprland`. RDP, WiFi, Syncthing, snapshot/scrub/Assistant Btrfs e batteria hanno flag indipendenti. Btrfs Assistant richiede snapshot e un desktop locale oppure RDP. Snapshot e scrub richiedono Btrfs quando viene scelta una ricetta disco; anche con hardware fornito devono esistere configurazioni snapshot effettive quando sono richieste. Per ARM serve `CPU_VENDOR=generic`; Steam è supportato solo su `x86_64-linux`.

`CHARGE_LIMIT_MODE` accetta `none` (predefinito, nessun limite di carica) oppure `thresholds` (soglie percentuali generiche opzionali di inizio/fine carica). La soglia iniziale deve essere inferiore a quella finale; le impostazioni specifiche dell'hardware appartengono alla configurazione dell'host.

`DISK_LAYOUT` vuoto seleziona `single-disk-ext4` per i client oppure `btrfs-worker-luks` per i server. `none` esplicito richiede `--hardware-configuration` con i filesystem della destinazione. Altrimenti accetta il nome senza `.nix` di una ricetta sotto `hosts/disk_configurations/`. Tutte le ricette rimangono disponibili nell'output e quella selezionata viene copiata nell'host come `disk-layout.nix`. Le ricette BIOS richiedono GRUB; quelle UEFI richiedono systemd-boot oppure Lanzaboote. `/dev/sda` diventa `sda`, `/dev/disk/by-id/...` diventa `disk/by-id/...`, perché le ricette aggiungono `/dev/`. Nessuna ricetta viene eseguita.

`SSH_ALLOWED_CIDRS` e `RDP_ALLOWED_CIDRS` accettano liste IPv4/IPv6 separate da virgole, senza identificatori scope IPv6. Il server richiede CIDR SSH. RDP richiede CIDR e usa quelli SSH se la propria lista è vuota. Sul client, CIDR SSH vuoti conservano il comportamento firewall nativo; quelli compilati attivano il filtro dell'host. I filtri seguono le porte `SSH_PORT` e `RDP_PORT`. I servizi SSH/RDP abilitati devono usare porte diverse e non possono usare le porte Syncthing `22222` o `8843` quando Syncthing è abilitato.

Gli SSID WiFi sono inseriti come stringhe Nix con escaping; vengono rifiutati caratteri di controllo e, per reti abilitate, SSID oltre 32 byte UTF-8. Gli esempi Syncthing disabilitano discovery locale/globale e relay: un Device ID compilato richiede un endpoint fisso `tcp://`, `tcp4://` o `tcp6://` con porta valida. Con ID vuoto non vengono creati device o cartella remoti. Il percorso dei dati di lavoro sul server deve essere `WORK_ROOT/data`; il client può usare un altro percorso assoluto. Non vengono aperte porte Syncthing in ingresso.

| Parametro | Default prima dei valori derivati dal ruolo |
|---|---|
| `HOST_ROLE` | `client` |
| `HOSTNAME` | `nixos` |
| `DESKTOP` | `none` |
| `FEATURES` | `(empty)` |
| `ADMIN_USER` | `admin` |
| `ADMIN_UID` | `1000` |
| `ADMIN_GID` | `1000` |
| `WORKER_USER` | `worker` |
| `WORKER_UID` | `1100` |
| `WORKER_GID` | `1100` |
| `WORK_GROUP` | `worker-work` |
| `WORK_GID` | `1200` |
| `WORK_ROOT` | `/srv/worker` |
| `TIMEZONE` | `Europe/Rome` |
| `DEFAULT_LOCALE` | `it_IT.UTF-8` |
| `KEY_LAYOUT` | `it` |
| `FONT` | `nerd-fonts.code-new-roman` |
| `NIXOS_VERSION` | `26.05` |
| `SSH_PORT` | `22` |
| `SSH_ALLOWED_CIDRS` | `(empty)` |
| `DICTIONARY` | `it_IT` |
| `BASEPATHUSER` | `/home` |
| `ENABLE_RDP` | `false` |
| `RDP_PORT` | `3389` |
| `RDP_ALLOWED_CIDRS` | `(empty)` |
| `ENABLE_WIFI` | `false` |
| `WIFI_SSID` | `(empty)` |
| `ENABLE_SYNCTHING` | `false` |
| `SYNCTHING_DEVICE_ID` | `(empty)` |
| `SYNCTHING_ADDRESS` | `dynamic` |
| `SYNCTHING_FOLDER_PATH` | `(empty)` |
| `SYNCTHING_FOLDER_ID` | `work-data` |
| `ENABLE_SNAPSHOTS` | `false` |
| `ENABLE_SCRUB` | `false` |
| `ENABLE_BTRFS_ASSISTANT` | `false` |
| `ENABLE_BATTERY` | `false` |
| `MAX_JOBS` | `(empty)` |
| `BUILD_CORES` | `(empty)` |
| `ENABLE_ZRAM` | `true` |
| `ZRAM_PERCENT` | `(empty)` |
| `ZRAM_ALGORITHM` | `(empty)` |
| `DISK_LAYOUT` | `(empty)` |
| `DISK_DEVICE` | `sda` |
| `SWAP_SIZE` | `16G` |
| `BOOT_LOADER` | `systemd-boot` |
| `CPU_VENDOR` | `generic` |
| `PLATFORM` | `x86_64-linux` |
| `CHARGE_LIMIT_MODE` | `none` |
| `CHARGE_START_THRESHOLD` | `75` |
| `CHARGE_STOP_THRESHOLD` | `80` |

## Hardware e segreti cifrati

`--hardware-configuration PERCORSO` copia una dichiarazione hardware fornita. In sua assenza rimane l'esempio hardware generico, da verificare sulla macchina reale. `DISK_LAYOUT=none` viene rifiutato senza `--hardware-configuration`; la dichiarazione fornita deve comprendere i filesystem della destinazione. Le ricette predefinite dichiarano il filesystem root senza eseguire operazioni sui dischi. `PLATFORM` viene sempre registrato come default dell’host; architetture diverse dichiarate nell’hardware fornito vengono rifiutate. Scegliere GRUB richiede anche una ricetta BIOS esplicita; il layout vuoto predefinito è UEFI.

Senza `--secrets-dir`, rimangono soltanto `secrets/*.yaml.template` e `.sops.yaml.template`; `PREPARATION.md` indica che il setup è incompleto. Segui la guida SOPS dell'output, compila gli esempi localmente e cifrali prima di creare i file YAML attivi. Nessun file di segreti in chiaro viene creato automaticamente; non vengono richieste o generate password o chiavi private.

```bash
./nixos_configs_generator.sh \
  --template-dir /percorso/template --output /percorso/nuovo-output \
  --set HOSTNAME=desk \
  --secrets-dir /percorso/input-cifrati --require-secrets
```

La directory deve contenere `common.yaml` e `HOSTNAME.yaml`. Vengono controllati struttura SOPS cifrata, valori principali cifrati e campi richiesti: `admin_hashedPassword`, `admin_ssh_publicKey` nel comune; `worker_hashedPassword`, `worker_ssh_publicKey` nell'host server; `wifi_env` quando WiFi è abilitato. Vengono copiati soltanto i due YAML. Nessun valore viene decifrato; autenticità crittografica, destinatari e correttezza operativa non sono verificabili da questo controllo. File in chiaro o campi richiesti mancanti vengono rifiutati. `--require-secrets` rende obbligatori gli input cifrati.

Puoi fornire insieme `--admin-age-recipient age1...` e `--host-age-recipient age1...` per preparare `.sops.yaml` dal template usando soltanto destinatari pubblici. Altrimenti configura quel file manualmente. Le chiavi private restano fuori dal repository e dall'output. La destinazione deve già possedere l'identità SSH host corretta per SOPS; questo strumento non la crea né la installa.

## Output e verifica

L'output contiene solo la categoria host selezionata, le directory account esplicite, i moduli condivisi e le ricette. I template dei parametri diventano file `.nix`; quelli SOPS conservano il suffisso. I placeholder maiuscoli dichiarati vengono sostituiti, le interpolazioni native Nix conservate; placeholder sconosciuti o residui interrompono la preparazione. Gli esempi nella documentazione restano generici e possono riferirsi alla struttura sorgente originale.

Prima di spostare i file generati nella cartella indicata con `--output`, il generatore analizza la sintassi di ogni file Nix e valuta la configurazione NixOS dell’host selezionato. Controlla così gli import effettivi dei moduli, i tipi delle opzioni, le asserzioni, la compatibilità della piattaforma e gli attributi dei pacchetti scelti. Fuso orario, locale e layout tastiera vengono verificati nei cataloghi del nixpkgs selezionato. Un controllo fallito non lascia la directory di output. Il recupero dei moduli con versione fissata o dei dati dei cataloghi può richiedere accesso alla rete oppure una cache Nix già disponibile. Gli output mancanti dei cataloghi vengono recuperati dai sostituti Nix, con builder locali e remoti disabilitati.

Per la valutazione i percorsi dei file SOPS vengono sostituiti con un placeholder sintetico `{}` esterno all'output. La sua directory sorgente temporanea viene eliminata al termine della verifica; la copia innocua nel Nix store può restare in cache. La valutazione Nix non decifra né controlla i valori dei segreti reali; gli YAML cifrati forniti ricevono soltanto i controlli strutturali descritti sopra. Destinatari, autenticità e decifratura vanno verificati separatamente sulla destinazione. `preparation.json` registra scelte pubbliche, nixpkgs selezionato ed esiti dei controlli. La derivazione di sistema riportata riguarda solo la verifica con percorsi segreti placeholder e non è un artefatto per l'installazione. `PREPARATION.md` registra i prerequisiti restanti. Una valutazione riuscita non sostituisce la build o i controlli sulla macchina reale.

## Test

I test automatici sono conservati sotto [tests/](tests/README.it.md). La loro guida spiega cosa controllano, come eseguire le suite unitarie e quelle sul template reale e quali prerequisiti servono. Sono file per lo sviluppo: il generatore non li esegue e non li copia nell'output.

## Fonti e licenze

Il bootstrap portabile utilizza [nix-portable](https://github.com/DavHau/nix-portable), sviluppato da DavHau, nella release [v012](https://github.com/DavHau/nix-portable/releases/tag/v012). La sua implementazione è distribuita con [licenza MIT](https://raw.githubusercontent.com/DavHau/nix-portable/v012/LICENSE), copyright (c) 2021 DavHau. Il launcher scarica l'eseguibile originale upstream; né l'eseguibile né il codice di implementazione upstream sono inclusi in questo repository.

Il generatore conserva la propria [licenza CC BY-NC 4.0](LICENSE). Questa licenza riguarda codice e documentazione propri del generatore; nix-portable e i programmi inclusi o scaricati mantengono le rispettive licenze. Non vengono ridistribuiti sotto CC BY-NC. Chi ridistribuisce codice o eseguibili upstream deve conservare le attribuzioni applicabili e rispettare le licenze dei componenti inclusi.
