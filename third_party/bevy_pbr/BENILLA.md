# benilla's `bevy_pbr` fork — what differs from upstream, and how to check

Upstream: [`bevyengine/bevy`](https://github.com/bevyengine/bevy) `crates/bevy_pbr`, MIT OR
Apache-2.0, version `0.18.1`, the version the workspace lock resolves to. Wired in through
`[patch.crates-io]` in the workspace root, beside the `bevy_render` fork it leans on. The crate is
copied from the cargo registry as published (`src/`, `Cargo.toml`, `README.md`, the two licence
files).

## Why a fork exists at all

Upstream samples the point-light shadow map as a depth cube array at a fixed level
(`textureSampleCompareLevel`), which naga's GLSL backend can only write with
`GL_EXT_texture_shadow_lod`. MuMu's emulated GLES lacks it, so the first PBR pipeline in the world
fails to compile and wgpu panics. Upstream already has the way round, for WebGL: one cube, not an
array, and the `NO_CUBE_ARRAY_TEXTURES_SUPPORT` shader branch, chosen at compile time by the
`webgl` feature on wasm.

## Patch — one point-shadow cube on GL, at run time

`bevy_render::renderer::point_shadow_cube_only` (the `bevy_render` fork) is true on the GL backend.
There the `bevy_render` pipeline cache adds `NO_CUBE_ARRAY_TEXTURES_SUPPORT`, and here:

- `src/render/mesh_view_bindings.rs` binds the point-shadow texture (binding 2) as a cube;
- `src/render/light.rs` (`prepare_lights`) views the shadow map as a cube and caps the shadowed
  point lights at one, as the WebGL path does.

WoW has no point-light shadows, so nothing the client draws loses one. On every other backend the
behaviour is upstream's byte for byte.

## Patch 2 — the sun's shadow map has at least two layers on GL

`prepare_lights` sizes the directional shadow map to the enabled cascades, and benilla's sun has
one. wgpu-hal's GLES backend makes a one-layer texture a `TEXTURE_2D`, which the `D2Array` view and
the shader's `sampler2DArrayShadow` cannot sample, so every sun shadow vanished. On GL the map is
allocated with at least two layers; the second is never drawn or read.

## How to check

    diff -ru ~/.cargo/registry/src/index.crates.io-*/bevy_pbr-0.18.1/src third_party/bevy_pbr/src

shows the hunks above and nothing else.
