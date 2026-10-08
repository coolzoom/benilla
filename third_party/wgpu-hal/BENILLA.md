# benilla's `wgpu-hal` fork — what differs from upstream, and how to check

Upstream: [`gfx-rs/wgpu`](https://github.com/gfx-rs/wgpu) `wgpu-hal`, MIT OR Apache-2.0, version
`27.0.4`, the version the workspace lock resolves to. Wired in through `[patch.crates-io]` in the
workspace root. The crate is copied from the cargo registry as published (`src/`, `examples/`,
`build.rs`, `Cargo.toml`, `README.md`, the two licence files).

## Why a fork exists at all

The GLES backend gives every texture and sampler a slot: its place among all the bindings of its
kind in the pipeline layout, every bind group and every stage counted. The slot tables are 16
long, and wgpu-core only checks each stage's count against the 16-per-stage limit. A bevy PBR
pipeline's layout on MuMu's emulated GLES carries more than 16 textures across its groups while no
stage exceeds 16, so a slot indexed past the table (`device.rs`, "the len is 16 but the index is
16") and wgpu panicked as the world loaded.

## Patch — `src/gles/mod.rs`, `src/gles/adapter.rs`

The slot tables (`MAX_TEXTURE_SLOTS`, `MAX_SAMPLERS`) are 32 long; the reported per-stage limits
stay at upstream's 16 (`MAX_TEXTURES_PER_STAGE`, `MAX_SAMPLERS_PER_STAGE`). A slot is a texture
unit, and GLES 3.0 guarantees 32 combined texture image units, so slots 16..31 are valid on every
device this backend runs on. No other backend is touched.

## Patch 2 — no GL debug labels on Android, `src/gles/adapter.rs`, `src/gles/device.rs`

glow hands `glPushDebugGroup`, `glDebugMessageInsert` and `glObjectLabel` a label with its length
and no terminating NUL, as GL allows. MuMu's GLES encoder (`libGLESv2_enc.so`) `strlen`s it
instead and read past the end into an unmapped page: a SIGSEGV in the render pass encoder once in
the world. On Android `DEBUG_FNS` stays off and the shader label is skipped; labels only feed GPU
debuggers. Other platforms are unchanged.

## How to check

    diff -ru ~/.cargo/registry/src/index.crates.io-*/wgpu-hal-27.0.4/src third_party/wgpu-hal/src

shows the hunks above and nothing else.
