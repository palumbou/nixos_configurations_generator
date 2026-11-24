# Test del generatore

> **Lingue**: [English](README.md) | [Italiano](README.it.md)

Questa cartella contiene i test automatici del generatore. Servono a verificare che le modifiche non compromettano le funzioni già esistenti e sono conservati nel repository insieme al codice. Non sono necessari per usare il generatore e non vengono copiati nelle configurazioni NixOS prodotte.

## Che cosa viene controllato

- Lettura dei parametri, nomi e ID, percorsi, CIDR, escaping e funzionalità opzionali.
- Isolamento dell’output, sorgenti immutabili, creazione atomica della cartella di output e rifiuto di input non validi.
- Controlli strutturali su input SOPS cifrati sintetici, senza segreti reali o decifratura.
- Launcher shell con eseguibili fittizi controllati, per verificare dipendenze e conservazione degli argomenti senza scaricare pacchetti.
- Validazione NixOS effettiva sul template standalone: profili client/server, ricette disco, ARM, import, filesystem root, localizzazione e attributi di pacchetti non validi.

Le piccole fixture dei test sui file sostituiscono soltanto il confine della validazione semantica Nix. `RealTemplateTests` usa il validatore effettivo e viene saltato se `NIXOS_TEMPLATE_TEST_DIR` non è impostata. Un esito positivo dei soli test con fixture non dimostra che la valutazione NixOS reale funzioni.

## Esecuzione dalla radice del repository

Serve Python 3.10 o successivo. I casi del launcher richiedono anche Bash e gli strumenti di base. Quelli sul template reale richiedono un ambiente Nix funzionante, nixpkgs compatibile e gli eventuali download o dati in cache di sorgenti e cataloghi.

```bash
python3 -m unittest discover -s tests -t . -v
```

Con Nix nativo, l’ambiente degli strumenti con versione fissata può fornire Python:

```bash
nix-shell --pure runtime.nix --run 'python3 -m unittest discover -s tests -t . -v'
```

Per includere la valutazione NixOS effettiva, indicare il repository del template che contiene `env.conf` e `nixos_configs_template/`:

```bash
nix-shell --pure runtime.nix --run \
  'NIXOS_TEMPLATE_TEST_DIR=/percorso/another_nixos_configurations_template python3 -m unittest discover -s tests -t . -v'
```

La stessa suite si può selezionare come modulo con `python3 -m unittest -v tests.test_generator`, oppure eseguire direttamente con `python3 tests/test_generator.py`. I percorsi del generatore e del launcher vengono risolti rispetto a questo repository e non alla directory corrente.

I test lavorano in cartelle temporanee. Non eseguono Disko, build o attivazioni di un sistema operativo, creazione di VM o modifiche a credenziali reali. La valutazione Nix effettiva può scrivere input sintetici innocui e derivazioni nel Nix store e richiedere rete/cache.
