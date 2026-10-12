# benilla

A from-scratch World of Warcraft 1.12.1 client in Rust and Bevy. The reference client is the
spec: benilla is a faithful, modern implementation of it, not a place to get creative.

Read, in this order:

1. `docs/METHOD.md` — the rules and how we work. Binding for every session.
2. `docs/MAP.md` — what is built right now, generated from the code. Orient here before
   touching anything.
3. `docs/CONTRIBUTING.md` — what gets in and how a change is judged.

The rest of the root is code and data: `crates/` the workspace, `reference/` the 1.12 name
catalogues the tests check against, `scripts/` the gates and instruments, `third_party/`
vendored code.

## Compiling

After a code edit, `./dev.sh check` (`cargo check --profile play -p benilla`). It
reuses `target/play` and does not link. `./dev.sh 2` links the client when it has to
run. Android builds go through `./android.sh 2`.

Both scripts source `scripts/cargo-env.sh`, which pins `CARGO_TARGET_DIR` to this
checkout's `target/` and drops incremental caches whose fingerprint will never be
reused. `./dev.sh trim` also deletes the host `release` and `ship` trees. It leaves
`target/play`, `target/debug` (tests), and the Android release tree.

Do not `cargo build --release` for a daily edit. Release has no incremental
compilation and is a separate copy of the graph. Do not pass `--target-dir`,
`--no-default-features`, or a feature set other than the defaults: each combination
is another copy. Do not export `CARGO_TARGET_DIR` or `RUSTFLAGS`. Do not run a bare
`cargo build`: that is the dev profile, a second full graph, and Cursor's sandbox
points `CARGO_TARGET_DIR` at a new directory.

Lua and XML under `crates/benilla-app/assets/ui` are read from disk while the `dev`
feature is on (the default). Restart the client; do not recompile for those edits.

@docs/METHOD.md
