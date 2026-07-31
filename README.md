# Orange Maroc CLI

Minimal, dependency-free CLI for viewing Orange Maroc plan allowances and
additional top-up balances through the Max it mobile API.

## Usage

Install the `orange` command under `~/.local/bin`:

```console
make install
```

```console
orange
orange plan
orange topups
orange --json
orange plan --json
orange login
orange logout
```

Use another credentials file with `--config path/to/config.toml`.

On the first run, `orange` asks for the account email and password, verifies
them, and stores them in `~/.local/share/orange/config.toml` with permissions
`600`. `orange login` replaces the saved login after confirmation, while
`orange logout` confirms and clears it. If saved credentials are rejected,
balance commands offer to start the login flow again.

The config is created on demand after a successful login. Reinstalling or
upgrading does not overwrite a saved login.

Remove the installed command and data with `make uninstall`.

The API always reports remaining allowances. It can optionally provide initial
and consumed values in each item's `gauge`, and JSON output preserves those
fields. Orange currently returns `gauge: null` for Yoxo balances on the tested
account, so consumed and total values cannot be calculated reliably.
