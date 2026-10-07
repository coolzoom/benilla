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
  the frame in it, falling back to the frame's own format, instead of adding the sRGB suffix to
  every frame.

On every adapter with an sRGB surface, or with `SURFACE_VIEW_FORMATS`, the behaviour is
upstream's byte for byte. Without either, the frame is written linear into a non-sRGB surface:
the picture renders, darker than it should.

## How to check

    diff -ru ~/.cargo/registry/src/index.crates.io-*/bevy_render-0.18.1/src third_party/bevy_render/src

shows the hunks above and nothing else.
