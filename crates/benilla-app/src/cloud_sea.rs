//! iNilla (cloud sea): a ray-marched volumetric cloud sea for the custom maps that declare one.
//!
//! No 1.12 map has volumetric clouds; this lane exists for our custom content (the `patch/`
//! scenes) and draws nothing on any other map. A map's entry in [`SEAS`] describes the forms:
//! a billowing sea slab (held down along the approach lane so the view from the spawn stays
//! open), towers boiling up out of it and helical bands spiralling around a centre. The
//! density field is procedural and moves: the sea drifts with the wind, the towers' detail
//! rises, the bands turn.
//!
//! Passes, after the fog pass and before the volumetric light (whose shafts sit on top):
//! 1. **march**, quarter resolution ([`DIVISOR`]): the view ray clipped to the slab, a per-pixel jittered start,
//!    steps growing with distance; each sample lit by the sun through four self-shadow taps
//!    and by a height-graded sky fill, faded into the zone fog. Writes premultiplied colour
//!    and the transmittance left over.
//! 2. **composite**, full resolution: a depth-aware bilinear upsample, `scene × T + cloud`.
//!
//! `WOW_CLOUDSEA=0` turns it off for a session; `WOW_CLOUDSEA_DEBUG=1` shows the opacity.
use crate::volumetric_fog::FogLabel;
use crate::volumetric_light::VolLightLabel;
use benilla_world::{lighting::WowLighting, view::WorldCamera, world_map::CurrentMap};
use bevy::{
    core_pipeline::{
        core_3d::graph::{Core3d, Node3d},
        FullscreenShader,
    },
    ecs::query::QueryItem,
    prelude::*,
    render::{
        camera::ExtractedCamera,
        diagnostic::RecordDiagnostics,
        extract_component::{ExtractComponent, ExtractComponentPlugin},
        render_graph::{
            NodeRunError, RenderGraphContext, RenderGraphExt, RenderLabel, ViewNode, ViewNodeRunner,
        },
        render_resource::{binding_types::*, *},
        renderer::{RenderContext, RenderDevice, RenderQueue},
        texture::{CachedTexture, TextureCache},
        view::{Msaa, ViewDepthTexture, ViewTarget, ViewUniform, ViewUniformOffset, ViewUniforms},
        Render, RenderApp, RenderStartup, RenderSystems,
    },
};

pub(crate) struct CloudSeaPlugin;

const MAX_TOWERS: usize = 12;
const MAX_RINGS: usize = 6;

/// A helical band: centre, radius, band thickness (yd), height span, signed turns (the sign is
/// the winding), and the direction (WoW radians) of an opening left in it, if any.
struct Ring {
    centre: Vec2,
    radius: f32,
    thickness: f32,
    z: (f32, f32),
    turns: f32,
    gap: Option<f32>,
}

/// One map's cloud sea, all positions in WoW world coordinates.
struct Sea {
    map: u32,
    /// Floor z, mean top z, ceiling z (the tallest tower's reach).
    slab: Vec3,
    /// The approach lane, start to end, its half width and the highest the sea may rise in it.
    lane: (Vec2, Vec2, f32, f32),
    /// x, y, top z, base radius.
    towers: &'static [Vec4],
    rings: &'static [Ring],
}

/// `patch/scenes/tiangong` (map 800, 天宫云阙): the layout of `scene.py`, rotated by its yaw
/// (30°) about the scene origin (−266.667, −266.667).
const SEAS: &[Sea] = &[Sea {
    map: 800,
    slab: Vec3::new(20.0, 112.0, 480.0),
    lane: (
        Vec2::new(-673.7, -501.7),
        Vec2::new(-162.7, -206.7),
        60.0,
        104.0,
    ),
    towers: &[
        Vec4::new(-650.6, 158.3, 330.0, 85.0),
        Vec4::new(-90.6, -811.6, 300.0, 85.0),
        Vec4::new(-345.8, 230.4, 380.0, 85.0),
        Vec4::new(124.2, -583.7, 360.0, 85.0),
        Vec4::new(140.3, 268.5, 420.0, 85.0),
        Vec4::new(410.3, -199.2, 400.0, 85.0),
        Vec4::new(433.5, 160.7, 460.0, 90.0),
        Vec4::new(-961.6, -182.9, 260.0, 80.0),
        Vec4::new(-551.6, -893.1, 280.0, 80.0),
    ],
    rings: &[
        Ring {
            centre: Vec2::new(-426.3, -70.2),
            radius: 115.0,
            thickness: 30.0,
            z: (70.0, 205.0),
            turns: 1.4,
            gap: None,
        },
        Ring {
            centre: Vec2::new(-176.3, -503.2),
            radius: 115.0,
            thickness: 30.0,
            z: (70.0, 205.0),
            turns: -1.4,
            gap: None,
        },
        Ring {
            centre: Vec2::new(79.7, -66.7),
            radius: 150.0,
            thickness: 36.0,
            z: (90.0, 260.0),
            turns: 1.6,
            gap: None,
        },
        // Around the palace platform, open toward the bridge (scene yaw 30° + 180°).
        Ring {
            centre: Vec2::new(-115.1, -179.2),
            radius: 205.0,
            thickness: 34.0,
            z: (140.0, 190.0),
            turns: -0.85,
            gap: Some(3.6652),
        },
    ],
}];

/// March samples (upper bound; the steps grow with distance and stop at full opacity).
const STEPS: f32 = 128.0;
/// The march runs at 1/DIVISOR of the view in each axis; the clouds are soft enough not to show it.
const DIVISOR: u32 = 4;
/// Rays stop this far out (yd); the fog has taken the sea well before.
const MARCH_CAP: f32 = 3200.0;
/// Extinction per yard at full density.
const EXTINCTION: f32 = 0.09;
/// Sea drift (yd/s), the towers' rise (yd/s), the bands' spin (rad/s).
const WIND: Vec4 = Vec4::new(4.5, 1.8, 3.5, 0.025);
/// The animation clock wraps here (s) to keep the noise coordinates precise.
const TIME_WRAP: f32 = 3600.0;
/// Direct light gain over the zone's diffuse, and the sky fill over the ambient/fog mix.
const SUN_GAIN: f32 = 1.35;
const FILL_GAIN: f32 = 0.85;

#[derive(Resource, Clone, Copy)]
struct CloudSeaSwitch {
    on: bool,
    debug: bool,
}

#[derive(Component, Clone, Copy, PartialEq, ExtractComponent, ShaderType)]
struct CloudSeaView {
    sun: Vec4,
    sun_colour: Vec4,
    ambient: Vec4,
    fog: Vec4,
    slab: Vec4,
    corridor: Vec4,
    lane: Vec4,
    wind: Vec4,
    counts: Vec4,
    towers: [Vec4; MAX_TOWERS],
    rings: [Vec4; MAX_RINGS],
    rings_b: [Vec4; MAX_RINGS],
}

fn wow_from_bevy(b: Vec3) -> Vec3 {
    Vec3::new(-b.z, -b.x, b.y)
}

impl CloudSeaView {
    fn new(sea: &Sea, lighting: &WowLighting, time: f32, debug: bool) -> Self {
        let mut towers = [Vec4::ZERO; MAX_TOWERS];
        for (slot, t) in towers.iter_mut().zip(sea.towers) {
            *slot = *t;
        }
        let mut rings = [Vec4::ZERO; MAX_RINGS];
        let mut rings_b = [Vec4::ZERO; MAX_RINGS];
        for (i, r) in sea.rings.iter().take(MAX_RINGS).enumerate() {
            rings[i] = Vec4::new(r.centre.x, r.centre.y, r.radius, r.thickness);
            rings_b[i] = Vec4::new(r.z.0, r.z.1, r.turns, r.gap.unwrap_or(100.0));
        }
        let toward = if lighting.sun_dir != Vec3::ZERO {
            -lighting.sun_dir
        } else {
            lighting.celestial_dir()
        };
        let sun = wow_from_bevy(toward).normalize_or(Vec3::Z);
        let fog = Vec3::from_array(lighting.fog_color);
        let fill = Vec3::from_array(lighting.ambient).lerp(fog, 0.35) * FILL_GAIN;
        let fog_end = lighting.fog_end().max(200.0);
        let (a, b, half_width, lane_top) = sea.lane;
        Self {
            sun: sun.extend(time),
            sun_colour: (Vec3::from_array(lighting.diffuse) * SUN_GAIN).extend(fog_end),
            ambient: fill.extend(STEPS),
            fog: fog.extend(fog_end * 0.35),
            slab: sea.slab.extend(MARCH_CAP),
            corridor: Vec4::new(a.x, a.y, b.x, b.y),
            lane: Vec4::new(half_width, lane_top, EXTINCTION, debug as u8 as f32),
            wind: WIND,
            counts: Vec4::new(
                sea.towers.len().min(MAX_TOWERS) as f32,
                sea.rings.len().min(MAX_RINGS) as f32,
                DIVISOR as f32,
                0.0,
            ),
            towers,
            rings,
            rings_b,
        }
    }
}

impl Plugin for CloudSeaPlugin {
    fn build(&self, app: &mut App) {
        let flag = |k: &str| std::env::var(k).ok().map(|v| v.trim() != "0");
        app.insert_resource(CloudSeaSwitch {
            on: flag("WOW_CLOUDSEA").unwrap_or(true),
            debug: flag("WOW_CLOUDSEA_DEBUG").unwrap_or(false),
        })
        .add_plugins(ExtractComponentPlugin::<CloudSeaView>::default())
        .add_systems(Last, update_views);
        if !app.is_plugin_added::<AssetPlugin>() || benilla_world::gl_backend() {
            return;
        }
        // `WOW_CLOUDSEA_WGSL=<path>` reads the shader from disk at startup, for tuning without a relink.
        let source = std::env::var("WOW_CLOUDSEA_WGSL")
            .ok()
            .and_then(|path| std::fs::read_to_string(path).ok())
            .unwrap_or_else(|| include_str!("cloud_sea.wgsl").to_owned());
        let shader = app
            .world_mut()
            .resource_mut::<Assets<Shader>>()
            .add(Shader::from_wgsl(source, "cloud_sea.wgsl"));
        let Some(render_app) = app.get_sub_app_mut(RenderApp) else {
            return;
        };
        render_app
            .insert_resource(CloudSeaShader(shader))
            .init_resource::<SpecializedRenderPipelines<CloudSeaPipeline>>()
            .add_systems(RenderStartup, init_pipeline)
            .add_systems(
                Render,
                (
                    prepare_pipelines.in_set(RenderSystems::Prepare),
                    prepare_resources.in_set(RenderSystems::PrepareResources),
                ),
            )
            .add_render_graph_node::<ViewNodeRunner<CloudSeaNode>>(Core3d, CloudSeaLabel)
            .add_render_graph_edges(Core3d, (FogLabel, CloudSeaLabel, VolLightLabel))
            .add_render_graph_edges(
                Core3d,
                (
                    Node3d::EndMainPass,
                    CloudSeaLabel,
                    Node3d::StartMainPassPostProcessing,
                ),
            );
    }
}

fn update_views(
    mut commands: Commands,
    switch: Res<CloudSeaSwitch>,
    map: Option<Res<CurrentMap>>,
    lighting: Res<WowLighting>,
    time: Res<Time>,
    mut cameras: Query<(Entity, &Camera, &mut Camera3d, Option<&CloudSeaView>), With<WorldCamera>>,
) {
    let sea = map
        .filter(|_| switch.on)
        .and_then(|m| SEAS.iter().find(|s| s.map == m.0));
    let clock = time.elapsed_secs_wrapped() % TIME_WRAP;
    for (entity, camera, mut camera3d, old) in &mut cameras {
        let Some(sea) = sea.filter(|_| camera.is_active) else {
            if old.is_some() {
                commands.entity(entity).remove::<CloudSeaView>();
            }
            continue;
        };
        camera3d.depth_texture_usages.0 |= TextureUsages::TEXTURE_BINDING.bits();
        commands
            .entity(entity)
            .insert(CloudSeaView::new(sea, &lighting, clock, switch.debug));
    }
}

#[derive(Resource)]
struct CloudSeaShader(Handle<Shader>);

/// The march target, 1/[`DIVISOR`] size: premultiplied cloud colour, transmittance.
const HALF_FORMAT: TextureFormat = TextureFormat::Rgba16Float;

#[derive(Resource)]
struct CloudSeaPipeline {
    /// `[single, multisampled]` depth.
    march_layouts: [BindGroupLayoutDescriptor; 2],
    composite_layouts: [BindGroupLayoutDescriptor; 2],
    shader: Handle<Shader>,
    fullscreen: FullscreenShader,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
enum CloudSeaKey {
    March {
        multisampled: bool,
    },
    Composite {
        format: TextureFormat,
        multisampled: bool,
    },
}

#[derive(Component)]
struct ViewCloudSeaPipelines {
    march: CachedRenderPipelineId,
    composite: CachedRenderPipelineId,
}

#[derive(Component)]
struct CloudSeaTexture(CachedTexture);

#[derive(Component)]
struct CloudSeaUniform(UniformBuffer<CloudSeaView>);

#[derive(Debug, Hash, PartialEq, Eq, Clone, RenderLabel)]
struct CloudSeaLabel;

fn depth_entry(multisampled: bool) -> BindGroupLayoutEntryBuilder {
    if multisampled {
        texture_depth_2d_multisampled()
    } else {
        texture_depth_2d()
    }
}

fn init_pipeline(
    mut commands: Commands,
    shader: Res<CloudSeaShader>,
    fullscreen: Res<FullscreenShader>,
) {
    let march_layouts = [false, true].map(|multisampled| {
        BindGroupLayoutDescriptor::new(
            "cloud_sea_march_layout",
            &BindGroupLayoutEntries::sequential(
                ShaderStages::FRAGMENT,
                (
                    depth_entry(multisampled),
                    uniform_buffer::<ViewUniform>(true),
                    uniform_buffer::<CloudSeaView>(false),
                ),
            ),
        )
    });
    let composite_layouts = [false, true].map(|multisampled| {
        BindGroupLayoutDescriptor::new(
            "cloud_sea_composite_layout",
            &BindGroupLayoutEntries::sequential(
                ShaderStages::FRAGMENT,
                (
                    texture_2d(TextureSampleType::Float { filterable: false }),
                    depth_entry(multisampled),
                    texture_2d(TextureSampleType::Float { filterable: false }),
                    uniform_buffer::<ViewUniform>(true),
                    uniform_buffer::<CloudSeaView>(false),
                ),
            ),
        )
    });
    commands.insert_resource(CloudSeaPipeline {
        march_layouts,
        composite_layouts,
        shader: shader.0.clone(),
        fullscreen: fullscreen.clone(),
    });
}

impl SpecializedRenderPipeline for CloudSeaPipeline {
    type Key = CloudSeaKey;

    fn specialize(&self, key: Self::Key) -> RenderPipelineDescriptor {
        let mut defs = Vec::new();
        let (label, layout, entry, format, multisampled) = match key {
            CloudSeaKey::March { multisampled } => {
                defs.push("CS_MARCH".into());
                (
                    "cloud_sea_march",
                    self.march_layouts[multisampled as usize].clone(),
                    "fs_march",
                    HALF_FORMAT,
                    multisampled,
                )
            }
            CloudSeaKey::Composite {
                format,
                multisampled,
            } => {
                defs.push("CS_COMPOSITE".into());
                (
                    "cloud_sea_composite",
                    self.composite_layouts[multisampled as usize].clone(),
                    "fs_composite",
                    format,
                    multisampled,
                )
            }
        };
        if multisampled {
            defs.push("MULTISAMPLED".into());
        }
        RenderPipelineDescriptor {
            label: Some(label.into()),
            layout: vec![layout],
            vertex: self.fullscreen.to_vertex_state(),
            fragment: Some(FragmentState {
                shader: self.shader.clone(),
                shader_defs: defs,
                entry_point: Some(entry.into()),
                targets: vec![Some(ColorTargetState {
                    format,
                    blend: None,
                    write_mask: ColorWrites::ALL,
                })],
            }),
            ..default()
        }
    }
}

fn prepare_pipelines(
    mut commands: Commands,
    cache: Res<PipelineCache>,
    pipeline: Res<CloudSeaPipeline>,
    mut specialized: ResMut<SpecializedRenderPipelines<CloudSeaPipeline>>,
    views: Query<(Entity, &ViewTarget, &Msaa), With<CloudSeaView>>,
    all_views: Query<(&ViewTarget, &Msaa), With<Camera3d>>,
) {
    // Warm every reachable key on every 3-D view (the `pipe_warm` census contract).
    let mut keys = |format: TextureFormat, multisampled: bool| ViewCloudSeaPipelines {
        march: specialized.specialize(&cache, &pipeline, CloudSeaKey::March { multisampled }),
        composite: specialized.specialize(
            &cache,
            &pipeline,
            CloudSeaKey::Composite {
                format,
                multisampled,
            },
        ),
    };
    for (target, msaa) in &all_views {
        keys(target.main_texture_format(), msaa.samples() > 1);
    }
    for (entity, target, msaa) in &views {
        let ids = keys(target.main_texture_format(), msaa.samples() > 1);
        commands.entity(entity).insert(ids);
    }
}

fn prepare_resources(
    mut commands: Commands,
    mut textures: ResMut<TextureCache>,
    device: Res<RenderDevice>,
    queue: Res<RenderQueue>,
    mut views: Query<(
        Entity,
        &ExtractedCamera,
        &CloudSeaView,
        Option<&mut CloudSeaUniform>,
    )>,
) {
    for (entity, camera, view, uniform) in &mut views {
        let Some(size) = camera.physical_viewport_size else {
            continue;
        };
        match uniform {
            Some(mut uniform) => {
                uniform.0.set(*view);
                uniform.0.write_buffer(&device, &queue);
            }
            None => {
                let mut uniform = UniformBuffer::from(*view);
                uniform.write_buffer(&device, &queue);
                commands.entity(entity).insert(CloudSeaUniform(uniform));
            }
        }
        let march = textures.get(
            &device,
            TextureDescriptor {
                label: Some("cloud_sea_march"),
                size: Extent3d {
                    width: size.x.div_ceil(DIVISOR).max(1),
                    height: size.y.div_ceil(DIVISOR).max(1),
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: TextureDimension::D2,
                format: HALF_FORMAT,
                usage: TextureUsages::RENDER_ATTACHMENT | TextureUsages::TEXTURE_BINDING,
                view_formats: &[],
            },
        );
        commands.entity(entity).insert(CloudSeaTexture(march));
    }
}

#[derive(Default)]
struct CloudSeaNode;

impl ViewNode for CloudSeaNode {
    type ViewQuery = (
        &'static ViewTarget,
        &'static ViewDepthTexture,
        &'static ViewUniformOffset,
        // Gates the pass: the uniform, texture and pipelines outlive a disabled frame.
        &'static CloudSeaView,
        &'static CloudSeaUniform,
        &'static CloudSeaTexture,
        &'static ViewCloudSeaPipelines,
    );

    fn run<'w>(
        &self,
        _graph: &mut RenderGraphContext,
        context: &mut RenderContext<'w>,
        (target, depth, view_offset, _, uniform, half, ids): QueryItem<'w, '_, Self::ViewQuery>,
        world: &'w World,
    ) -> Result<(), NodeRunError> {
        let cache = world.resource::<PipelineCache>();
        let (Some(march), Some(composite)) = (
            cache.get_render_pipeline(ids.march),
            cache.get_render_pipeline(ids.composite),
        ) else {
            return Ok(());
        };
        if !depth
            .texture
            .usage()
            .contains(TextureUsages::TEXTURE_BINDING)
        {
            return Ok(());
        }
        let (Some(view), Some(params)) = (
            world.resource::<ViewUniforms>().uniforms.binding(),
            uniform.0.binding(),
        ) else {
            return Ok(());
        };
        let settings = world.resource::<CloudSeaPipeline>();
        let multisampled = (depth.texture.sample_count() > 1) as usize;
        let device = context.render_device();
        let march_bind = device.create_bind_group(
            "cloud_sea_march",
            &cache.get_bind_group_layout(&settings.march_layouts[multisampled]),
            &BindGroupEntries::sequential((depth.view(), view.clone(), params.clone())),
        );
        let out = target.post_process_write();
        let composite_bind = device.create_bind_group(
            "cloud_sea_composite",
            &cache.get_bind_group_layout(&settings.composite_layouts[multisampled]),
            &BindGroupEntries::sequential((
                out.source,
                depth.view(),
                &half.0.default_view,
                view,
                params,
            )),
        );
        let diagnostics = context.diagnostic_recorder();
        let stages: [(&str, &TextureView, &RenderPipeline, &BindGroup); 2] = [
            ("cloud_sea_march", &half.0.default_view, march, &march_bind),
            ("cloud_sea_composite", out.destination, composite, &composite_bind),
        ];
        for (label, destination, pipeline, bind) in stages {
            let mut pass = context
                .command_encoder()
                .begin_render_pass(&RenderPassDescriptor {
                    label: Some(label),
                    color_attachments: &[Some(RenderPassColorAttachment {
                        view: destination,
                        depth_slice: None,
                        resolve_target: None,
                        ops: Operations::default(),
                    })],
                    depth_stencil_attachment: None,
                    timestamp_writes: None,
                    occlusion_query_set: None,
                });
            let span = diagnostics.pass_span(&mut pass, label);
            pass.set_pipeline(pipeline);
            pass.set_bind_group(0, bind, &[view_offset.offset]);
            pass.draw(0..3, 0..1);
            span.end(&mut pass);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seas_fit_the_uniform_and_only_custom_maps_have_one() {
        for sea in SEAS {
            assert!(sea.map >= 800, "no 1.12 map has a cloud sea");
            assert!(sea.towers.len() <= MAX_TOWERS && sea.rings.len() <= MAX_RINGS);
            assert!(sea.slab.x < sea.slab.y && sea.slab.y < sea.slab.z);
            for r in sea.rings {
                assert!(r.z.0 < r.z.1 && r.turns != 0.0);
            }
        }
    }

    #[test]
    fn the_view_points_the_sun_up_in_wow_space() {
        let mut lighting = WowLighting::default();
        lighting.sun_dir = Vec3::new(0.0, -1.0, 0.0);
        let view = CloudSeaView::new(&SEAS[0], &lighting, 1.0, false);
        assert!((view.sun.truncate() - Vec3::Z).length() < 1e-5);
        assert_eq!(view.counts.x, SEAS[0].towers.len() as f32);
    }
}
