//! The tuned Bevy boot: the `DefaultPlugins` set every benilla binary stands on. The engine tuning
//! is shared; the `Window` is the caller's.

use bevy::app::{PluginGroupBuilder, TaskPoolOptions, TaskPoolPlugin};
use bevy::prelude::*;

use crate::thread_qos;

/// `WOW_GPU_SERIAL=1`: one thread at a time in the GPU driver, for an emulated GPU (MuMu's
/// goldfish Vulkan encoder) that hangs when two threads call it at once. Pipelines compile on the
/// render thread, rendering is not pipelined, the compute pool has one worker, and the app runs
/// `Render` single-threaded.
pub fn gpu_serial() -> bool {
    std::env::var("WOW_GPU_SERIAL").as_deref() == Ok("1")
}

/// The device's own limits but four storage textures per stage, under which bevy skips
/// `ScreenSpaceAmbientOcclusionPlugin` (it needs five). benilla draws no SSAO, but the plugin
/// compiles its compute pipelines at startup, and an emulated GLES rejects their
/// `textureGatherOffset`. Bevy takes the minimum of each `max_*` field and the maximum of each
/// `min_*`, so every other field is left unbounded.
fn emulator_limits() -> bevy::render::settings::WgpuLimits {
    const M: u32 = u32::MAX;
    bevy::render::settings::WgpuLimits {
        max_storage_textures_per_shader_stage: 4,
        max_texture_dimension_1d: M,
        max_texture_dimension_2d: M,
        max_texture_dimension_3d: M,
        max_texture_array_layers: M,
        max_bind_groups: M,
        max_bindings_per_bind_group: M,
        max_dynamic_uniform_buffers_per_pipeline_layout: M,
        max_dynamic_storage_buffers_per_pipeline_layout: M,
        max_sampled_textures_per_shader_stage: M,
        max_samplers_per_shader_stage: M,
        max_storage_buffers_per_shader_stage: M,
        max_uniform_buffers_per_shader_stage: M,
        max_binding_array_elements_per_shader_stage: M,
        max_binding_array_sampler_elements_per_shader_stage: M,
        max_uniform_buffer_binding_size: M,
        max_storage_buffer_binding_size: M,
        max_vertex_buffers: M,
        max_buffer_size: u64::MAX,
        max_vertex_attributes: M,
        max_vertex_buffer_array_stride: M,
        min_uniform_buffer_offset_alignment: 0,
        min_storage_buffer_offset_alignment: 0,
        max_inter_stage_shader_components: M,
        max_color_attachments: M,
        max_color_attachment_bytes_per_sample: M,
        max_compute_workgroup_storage_size: M,
        max_compute_invocations_per_workgroup: M,
        max_compute_workgroup_size_x: M,
        max_compute_workgroup_size_y: M,
        max_compute_workgroup_size_z: M,
        max_compute_workgroups_per_dimension: M,
        min_subgroup_size: 0,
        max_subgroup_size: M,
        max_push_constant_size: M,
        max_non_sampler_bindings: M,
        max_task_workgroup_total_count: M,
        max_task_workgroups_per_dimension: M,
        max_mesh_output_layers: M,
        max_mesh_multiview_count: M,
        max_blas_primitive_count: M,
        max_blas_geometry_count: M,
        max_tlas_instance_count: M,
        max_acceleration_structures_per_shader_stage: M,
    }
}

/// `DefaultPlugins` with benilla's engine tuning applied, around the caller's primary window.
pub fn tuned_default_plugins(primary_window: Window) -> PluginGroupBuilder {
    let serial = gpu_serial();
    let plugins = DefaultPlugins
        .set(WindowPlugin {
            primary_window: Some(primary_window),
            ..default()
        })
        // Deliberately no `AssetPlugin::file_path`: a baked source path resolves only on the build
        // machine. Every shader is embedded (`embedded://<crate>/shaders/…`), so no root is read.
        // Quiet wgpu/naga; the ring keeps the last stderr lines for the crash report (`log_ring`).
        .set(bevy::log::LogPlugin {
            filter: "wgpu=error,naga=warn".into(),
            custom_layer: |_| Some(Box::new(crate::log_ring::LogRing)),
            ..default()
        })
        // Asset loads parse synchronously on the IO pool, and Bevy's default 4 threads saturate on
        // a dense teleport. Workers spawn at default QoS, behind any background build:
        // compute is user-interactive, IO and async compute user-initiated, and
        // `ThreadQosPlugin` promotes the render thread from inside.
        .set(TaskPoolPlugin {
            task_pool_options: TaskPoolOptions {
                io: bevy::app::TaskPoolThreadAssignmentPolicy {
                    min_threads: 2,
                    max_threads: 8,
                    percent: 0.5,
                    on_thread_spawn: Some(std::sync::Arc::new(|| {
                        thread_qos::promote_current_thread(thread_qos::QosClass::UserInitiated)
                    })),
                    on_thread_destroy: None,
                },
                async_compute: bevy::app::TaskPoolThreadAssignmentPolicy {
                    on_thread_spawn: Some(std::sync::Arc::new(|| {
                        thread_qos::promote_current_thread(thread_qos::QosClass::UserInitiated)
                    })),
                    ..TaskPoolOptions::default().async_compute
                },
                compute: bevy::app::TaskPoolThreadAssignmentPolicy {
                    on_thread_spawn: Some(std::sync::Arc::new(|| {
                        thread_qos::promote_current_thread(thread_qos::QosClass::UserInteractive)
                    })),
                    // `WOW_THREADS=1` serialises the frame's systems, a diagnostic: a defect that
                    // survives it is not a race between two systems.
                    max_threads: if serial || std::env::var("WOW_THREADS").as_deref() == Ok("1") {
                        1
                    } else {
                        TaskPoolOptions::default().compute.max_threads
                    },
                    ..TaskPoolOptions::default().compute
                },
                ..default()
            },
        })
        .set(bevy::render::RenderPlugin {
            render_creation: bevy::render::settings::WgpuSettings {
                constrained_limits: serial.then(emulator_limits),
                ..default()
            }
            .into(),
            synchronous_pipeline_compilation: serial,
            ..default()
        })
        // Sound is kira behind our own mixer; `bevy_audio` is off by feature (workspace
        // `Cargo.toml`). Kept though they look idle: gizmos (bowstring, fishing line), sprites (the
        // FrameXML quad pass), picking, TextPlugin (glue text), PostProcessPlugin (glow bloom) and
        // ScenePlugin (avian's collider backend reads `SceneSpawner`); the ForwardDecal family is
        // registered inside `PbrPlugin::build`, so it cannot be disabled on its own.
        //
        // M2/WMO/ADT load through our own `mpq://` loaders; there is no glTF.
        .disable::<bevy::gltf::GltfPlugin>()
        // No bevy AA: no Fxaa/TAA/SMAA/CAS component anywhere (MSAA is core render, unaffected).
        .disable::<bevy::anti_alias::AntiAliasPlugin>()
        // No gamepad input; 1.12's bindings are keyboard/mouse.
        .disable::<bevy::gilrs::GilrsPlugin>();
    if serial {
        plugins.disable::<bevy::render::pipelined_rendering::PipelinedRenderingPlugin>()
    } else {
        plugins
    }
}
