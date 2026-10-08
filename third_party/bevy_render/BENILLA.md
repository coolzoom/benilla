# benilla's `bevy_render` fork — what differs from upstream, and how to check

Upstream: [`bevyengine/bevy`](https://github.com/bevyengine/bevy) `crates/bevy_render`, MIT OR
Apache-2.0, version `0.18.1`, the version the workspace lock resolves to. Wired in through
`[patch.crates-io]` in the workspace root, the way `kira` and `lua-src` are. The crate is copied
from the cargo registry as published (`src/`, `Cargo.toml`, `README.md`, the two licence files).

## Why a fork exists at all

The Android build runs on GLES where Vulkan is unusable, as on MuMu's emulated GPU. MuMu's EGL
offers only non-sRGB surface formats (`Rgba8Unorm`), and upstream then configures the surface
with an sRGB `view_formats` entry and views every frame as sRGB. Viewing a surface in another
format needs `DownlevelFlags::SURFACE_VIEW_FORMATS`, which GLES lacks, so `Surface::configure`
fails validation and the app panics before its first frame.

## Patch 1 — `src/view/window/mod.rs`

- `create_surfaces` asks for the sRGB view only where the adapter reports
  `SURFACE_VIEW_FORMATS`; otherwise the surface is configured with no extra view format.
- `ExtractedWindow::set_swapchain_texture` takes the surface's configured view format and views
  the frame in it, instead of adding the sRGB suffix to every frame.

## Patch 2 — the sRGB stage, `src/view/window/mod.rs` and `src/renderer/mod.rs`

A non-sRGB surface with no sRGB view would take the frame linear and show it dark. Where the
surface format has an sRGB twin and no view format was configured, `set_swapchain_texture` hands
the render graph an sRGB stage texture of the frame's size (`SrgbEncode`) as the window's view,
and `ExtractedWindow::present`, now given the device and queue by `render`, encodes the stage into
the frame with one fullscreen pass before presenting. A pass, not a copy: GLES surfaces allow only
`COLOR_TARGET`. Screenshots read the stage, as they read the window's view upstream.

On every adapter with an sRGB surface, or with `SURFACE_VIEW_FORMATS`, the behaviour is
upstream's byte for byte.

## Patch 3 — one point-shadow cube on GL, `src/renderer/mod.rs` and `pipeline_cache.rs`

`renderer::point_shadow_cube_only` is true on the GL backend, where sampling a depth cube array at
a level needs `GL_EXT_texture_shadow_lod`, which MuMu's GLES lacks. There `PipelineCache::new` adds
`NO_CUBE_ARRAY_TEXTURES_SUPPORT`, as it does for the iOS simulator; the `bevy_pbr` fork binds and
views the point-shadow map to match (`third_party/bevy_pbr/BENILLA.md`).

## Patch 4 — `NO_DEPTH_TEXTURE_LOAD` on GL, `pipeline_cache.rs`

naga's GLSL writer rejects a WGSL `textureLoad` from a depth texture, which fails the pipeline and,
with wgpu errors fatal, the app. On the GL backend `PipelineCache::new` adds the global shader def
`NO_DEPTH_TEXTURE_LOAD`, so a benilla shader can take another path there (`shadow_hook.wgsl`'s
torch blocker search).

## How to check

    diff -ru ~/.cargo/registry/src/index.crates.io-*/bevy_render-0.18.1/src third_party/bevy_render/src

shows the hunks above and nothing else.
