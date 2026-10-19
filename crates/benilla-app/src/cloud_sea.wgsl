// iNilla (cloud sea): a ray-marched volumetric cloud sea, two stages (see cloud_sea.rs).
//   CS_MARCH     reduced resolution (1/counts.z): march the density field, light it, write premultiplied colour
//                and the transmittance left over.
//   CS_COMPOSITE full resolution: depth-aware upsample, `scene × T + cloud`.
// The density field works in WoW space (+z up); identifiers carry no trailing digit (naga_oil).

#import bevy_core_pipeline::fullscreen_vertex_shader::FullscreenVertexOutput

const MAX_TOWERS: u32 = 12u;
const MAX_RINGS: u32 = 6u;
// The swell (0.55 × 60) plus the domes (55) over the mean sea top, yd.
const SEA_REACH: f32 = 90.0;

struct CloudSea {
    sun: vec4<f32>,        // toward the sun (unit, WoW space), animation time (s)
    sun_colour: vec4<f32>, // direct light colour, fog end (yd)
    ambient: vec4<f32>,    // sky fill colour, march steps
    fog: vec4<f32>,        // fog colour, fog start (yd)
    slab: vec4<f32>,       // floor z, mean sea top z, ceiling z, march cap (yd)
    corridor: vec4<f32>,   // clear lane from (x, y) to (z, w)
    lane: vec4<f32>,       // lane half width, highest sea top in it, extinction/yd, debug
    wind: vec4<f32>,       // sea drift (yd/s) xy, tower rise (yd/s), swirl spin (rad/s)
    counts: vec4<f32>,     // towers, rings, march resolution divisor
    towers: array<vec4<f32>, 12>, // x, y, top z, base radius
    rings: array<vec4<f32>, 6>,   // centre x, y, radius, band thickness
    rings_b: array<vec4<f32>, 6>, // z start, z end, signed turns, gap direction (rad; > 50 none)
}

fn to_wow(b: vec3<f32>) -> vec3<f32> {
    return vec3<f32>(-b.z, -b.x, b.y);
}

// Distance (yd) along the view ray to the scene; the sky (depth 0, infinite reverse-Z) is `cap`.
fn ray_distance(world_from_clip: mat4x4<f32>, eye: vec3<f32>, ndc_xy: vec2<f32>, z: f32, cap: f32) -> f32 {
    if (z <= 0.0) {
        return cap;
    }
    let q = world_from_clip * vec4<f32>(ndc_xy, z, 1.0);
    return min(length(q.xyz / q.w - eye), cap);
}

// iNilla: both passes reconstruct the same centred reduced-resolution ray, including
// the partial final tile. The depth texel is the nearest full-resolution guide.
fn march_pixel(p: vec2<i32>, scale: f32, dims: vec2<i32>) -> vec2<f32> {
    return min((vec2<f32>(p) + 0.5) * scale, vec2<f32>(dims) - 0.5);
}

#ifdef CS_MARCH

#import bevy_render::view::View

#ifdef MULTISAMPLED
@group(0) @binding(0) var depth: texture_depth_multisampled_2d;
#else
@group(0) @binding(0) var depth: texture_depth_2d;
#endif
@group(0) @binding(1) var<uniform> view: View;
@group(0) @binding(2) var<uniform> cs: CloudSea;

fn ign(p: vec2<f32>) -> f32 {
    return fract(52.9829189 * fract(dot(p, vec2<f32>(0.06711056, 0.00583715))));
}

fn hash(p: vec3<f32>) -> f32 {
    var q = fract(p * 0.1031);
    q += dot(q, q.zyx + 31.32);
    return fract((q.x + q.y) * q.z);
}

fn vnoise(p: vec3<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    let a = mix(hash(i), hash(i + vec3<f32>(1.0, 0.0, 0.0)), u.x);
    let b = mix(hash(i + vec3<f32>(0.0, 1.0, 0.0)), hash(i + vec3<f32>(1.0, 1.0, 0.0)), u.x);
    let c = mix(hash(i + vec3<f32>(0.0, 0.0, 1.0)), hash(i + vec3<f32>(1.0, 0.0, 1.0)), u.x);
    let d = mix(hash(i + vec3<f32>(0.0, 1.0, 1.0)), hash(i + vec3<f32>(1.0, 1.0, 1.0)), u.x);
    return mix(mix(a, b, u.y), mix(c, d, u.y), u.z);
}

// 0..~1 fractal value noise.
fn fbm(p: vec3<f32>, octaves: u32) -> f32 {
    var sum = 0.0;
    var amp = 0.5;
    var norm = 0.0;
    var q = p;
    for (var i = 0u; i < octaves; i += 1u) {
        sum += amp * vnoise(q);
        norm += amp;
        q = q * 2.03 + vec3<f32>(1.7, 9.2, 3.1);
        amp *= 0.5;
    }
    return sum / norm;
}

fn segment_distance(p: vec2<f32>, a: vec2<f32>, b: vec2<f32>) -> f32 {
    let ab = b - a;
    let h = clamp(dot(p - a, ab) / dot(ab, ab), 0.0, 1.0);
    return length(p - a - ab * h);
}

// Coverage 0..1 of the large forms at `p`, and the point the detail noise is read at: each form
// carries its own motion (the sea drifts, towers rise, rings spin), so the detail rides along.
struct Shape {
    d: f32,
    q: vec3<f32>,
}

fn shape(p: vec3<f32>) -> Shape {
    let t = cs.sun.w;
    // The sea: a billowing top over a soft floor, held down along the approach lane.
    let drift = cs.wind.xy * t;
    var best = Shape(0.0, p - vec3<f32>(drift, 0.0));
    // Above the highest the swell and the domes can reach there is no sea to evaluate.
    if (p.z < cs.slab.y + SEA_REACH) {
        let billow = fbm(vec3<f32>((p.xy - drift) * 0.0042, 0.37), 3u);
        // Rolling domes over the swell: the folded noise peaks into rounded heads, not ridges.
        let heads = 1.0 - abs(fbm(vec3<f32>((p.xy - drift) * 0.0065, 2.9), 2u) * 2.0 - 1.0);
        var top = cs.slab.y + (billow - 0.45) * 60.0 + heads * heads * heads * 55.0;
        let lane = segment_distance(p.xy, cs.corridor.xy, cs.corridor.zw);
        top = mix(min(top, cs.lane.y), top, smoothstep(cs.lane.x, cs.lane.x * 2.4, lane));
        best.d = smoothstep(0.0, 30.0, top - p.z) * smoothstep(cs.slab.x, cs.slab.x + 45.0, p.z);
    }
    // Towers: columns boiling up out of the sea, thinning and swaying as they climb.
    let towers = u32(cs.counts.x);
    for (var i = 0u; i < MAX_TOWERS; i += 1u) {
        if (i >= towers) { break; }
        let tw = cs.towers[i];
        let base = cs.slab.y - 25.0;
        let h = (p.z - base) / (tw.z - base);
        if (h < 0.0 || h > 1.15) { continue; }
        let fi = f32(i);
        let sway = vec2<f32>(sin(h * 4.0 + fi * 2.3), cos(h * 3.0 + fi * 1.7)) * 22.0;
        if (length(p.xy - tw.xy - sway) > tw.w * 1.3) { continue; }
        let rising = p - vec3<f32>(0.0, 0.0, cs.wind.z * t);
        let r = tw.w * (1.0 - 0.45 * h) * (0.7 + 0.6 * fbm(rising * 0.009 + vec3<f32>(fi * 7.1), 2u));
        let dxy = length(p.xy - tw.xy - sway);
        let d = (1.0 - smoothstep(r * 0.3, r, dxy)) * (1.0 - smoothstep(0.82, 1.1, h));
        if (d > best.d) {
            best = Shape(d, rising);
        }
    }
    // Rings: helical bands spiralling around a centre, the whole helix turning.
    let rings = u32(cs.counts.y);
    for (var i = 0u; i < MAX_RINGS; i += 1u) {
        if (i >= rings) { break; }
        let a = cs.rings[i];
        let b = cs.rings_b[i];
        let v = p.xy - a.xy;
        let rho = length(v);
        if (abs(rho - a.z) > a.w * 1.6 || p.z < b.x - a.w || p.z > b.y + a.w) { continue; }
        let ang = atan2(v.y, v.x);
        let dir = sign(b.z);
        let turns = abs(b.z);
        let spin = cs.wind.w * t * dir;
        let u = (p.z - b.x) / (b.y - b.x);
        let strand = u * turns - dir * (ang - spin) / 6.2831853;
        let dz = (b.y - b.x) / turns * abs(fract(strand + 0.5) - 0.5);
        let taper = smoothstep(-0.05, 0.15, u) * (1.0 - smoothstep(0.85, 1.05, u));
        var d = (1.0 - smoothstep(0.2, 1.0, length(vec2<f32>(rho - a.z, dz)) / a.w)) * taper;
        if (b.w < 50.0) {
            d *= 1.0 - smoothstep(0.2, 0.55, cos(ang - b.w));
        }
        if (d > best.d) {
            let c = cos(-spin);
            let s = sin(-spin);
            best = Shape(d, vec3<f32>(a.xy + vec2<f32>(c * v.x - s * v.y, s * v.x + c * v.y), p.z));
        }
    }
    return best;
}

fn remap(x: f32, lo: f32) -> f32 {
    return clamp((x - lo) / max(1.0 - lo, 0.05), 0.0, 1.0);
}

// iNilla: erosion alone maps a solid interior straight back to one. Multiply by
// a correlated low-frequency body field as well, so dense interiors retain structure.
// Shared with the light march: empty billows must not cast solid-form shadows.
fn body_density(s: Shape) -> f32 {
    if (s.d <= 0.002) {
        return 0.0;
    }
    let lobes = 1.0 - abs(fbm(s.q * 0.011, 2u) * 2.0 - 1.0);
    let body = remap(s.d, 0.12 + (1.0 - lobes) * 0.65);
    return body * mix(0.32, 1.0, lobes * lobes);
}

fn density(s: Shape) -> f32 {
    let body = body_density(s);
    if (body <= 0.0) {
        return 0.0;
    }
    // The fine detail also evolves in place, so the billows boil as well as drift.
    let fine = fbm(s.q * 0.045 + vec3<f32>(0.0, 0.0, cs.sun.w * 0.12), 2u);
    return remap(body, fine * 0.45 * (1.0 - body * 0.6));
}

// Omit only the finest erosion in the three-sample light march.
fn shadow_density(p: vec3<f32>) -> f32 {
    return body_density(shape(p));
}

fn hg(mu: f32, g: f32) -> f32 {
    let denom = 1.0 + g * g - 2.0 * g * mu;
    return (1.0 - g * g) / (denom * sqrt(denom));
}

@fragment
fn fs_march(in: FullscreenVertexOutput) -> @location(0) vec4<f32> {
    let dims = vec2<i32>(textureDimensions(depth));
    let hp = vec2<i32>(in.position.xy);
    let centre = march_pixel(hp, cs.counts.z, dims);
    let full = vec2<i32>(centre);
    let z = textureLoad(depth, full, 0);
    let uv = centre / vec2<f32>(dims);
    let ndc = uv * vec2(2.0, -2.0) + vec2(-1.0, 1.0);
    let far = view.world_from_clip * vec4<f32>(ndc, max(z, 0.000001), 1.0);
    let ray_b = normalize(far.xyz / far.w - view.world_position);
    let dist = ray_distance(view.world_from_clip, view.world_position, ndc, z, cs.slab.w);
    let o = to_wow(view.world_position);
    let d = to_wow(ray_b);
    // Clip the ray to the slab the clouds live in.
    var t0 = 0.5;
    var t1 = dist;
    if (abs(d.z) > 1e-5) {
        let ta = (cs.slab.x - o.z) / d.z;
        let tb = (cs.slab.z - o.z) / d.z;
        t0 = max(t0, min(ta, tb));
        t1 = min(t1, max(ta, tb));
    } else if (o.z < cs.slab.x || o.z > cs.slab.z) {
        return vec4<f32>(0.0, 0.0, 0.0, 1.0);
    }
    if (t1 <= t0) {
        return vec4<f32>(0.0, 0.0, 0.0, 1.0);
    }
    let mu = dot(d, cs.sun.xyz);
    // Forward lobe for the silver lining toward the sun, a back lobe so the far side is not flat.
    let phase = mix(hg(mu, 0.55), hg(mu, -0.2), 0.4);
    let sigma = cs.lane.z;
    let steps = u32(cs.ambient.w);
    // Cloud tops scatter near-white even under a golden sun; the hue survives in the sunlit rims.
    let sun_rgb = mix(cs.sun_colour.rgb, vec3<f32>(max(cs.sun_colour.r, max(cs.sun_colour.g, cs.sun_colour.b))), 0.55);
    let shade_rgb = cs.ambient.rgb * vec3<f32>(0.92, 0.98, 1.08);
    var tr = 1.0;
    var col = vec3<f32>(0.0);
    // iNilla: fixed coverage partitions the whole clipped segment. Jitter stays
    // inside each interval, so every ray integrates exactly the same length.
    let step_length = (t1 - t0) / max(f32(steps), 1.0);
    let jitter = ign(vec2<f32>(hp));
    for (var i = 0u; i < 192u; i += 1u) {
        if (i >= steps || tr < 0.015) { break; }
        let t = t0 + (f32(i) + jitter) * step_length;
        let p = o + d * t;
        let dt = step_length;
        let s = shape(p);
        let dens = density(s);
        if (dens > 0.0) {
            // Self-shadow toward the sun: four coarse samples of the large forms.
            var depth_to_sun = 0.0;
            var reach = 8.0;
            for (var k = 0u; k < 3u; k += 1u) {
                depth_to_sun += shadow_density(p + cs.sun.xyz * reach) * reach * 0.9;
                reach *= 3.2;
            }
            let beer = exp(-depth_to_sun * sigma);
            // Bounded two-lobe approximation: direct Beer transmission plus a
            // softer, energy-limited multiple-scatter contribution.
            let sun_t = clamp(beer + (1.0 - beer) * exp(-depth_to_sun * sigma * 0.25) * 0.3, 0.0, 1.0);
            // Powder: the sunlit rims of thin, dense-edged billows read brighter than the core.
            let powder = 1.0 - exp(-dens * 3.0);
            let height = clamp((p.z - cs.slab.x) / (cs.slab.y - cs.slab.x + 120.0), 0.0, 1.0);
            var c = sun_rgb * sun_t * phase * mix(0.6, 1.0, powder)
                + shade_rgb * mix(0.45, 1.15, height);
            let fogf = clamp((t - cs.fog.w) / max(cs.sun_colour.w - cs.fog.w, 1.0), 0.0, 1.0);
            c = mix(c, cs.fog.rgb, fogf * fogf);
            let alpha = 1.0 - exp(-dens * sigma * dt);
            col += tr * alpha * c;
            tr *= 1.0 - alpha;
        }
    }
    // A downward ray that reached the march cap still has sea under it: the horizon haze.
    if (dist >= cs.slab.w && d.z < 0.0) {
        col += tr * cs.fog.rgb;
        tr = 0.0;
    }
    if (cs.lane.w > 0.5) {
        return vec4<f32>(vec3<f32>(1.0 - tr), 0.0);
    }
    return vec4<f32>(col, tr);
}

#endif

#ifdef CS_COMPOSITE

#import bevy_render::view::View

@group(0) @binding(0) var scene: texture_2d<f32>;
#ifdef MULTISAMPLED
@group(0) @binding(1) var depth: texture_depth_multisampled_2d;
#else
@group(0) @binding(1) var depth: texture_depth_2d;
#endif
@group(0) @binding(2) var clouds: texture_2d<f32>;
@group(0) @binding(3) var<uniform> view: View;
@group(0) @binding(4) var<uniform> cs: CloudSea;

fn key_at(p: vec2<i32>, dims: vec2<i32>) -> f32 {
    let q = min(p, dims - vec2<i32>(1));
    let z = textureLoad(depth, q, 0);
    let uv = (vec2<f32>(q) + 0.5) / vec2<f32>(dims);
    let ndc = uv * vec2(2.0, -2.0) + vec2(-1.0, 1.0);
    return ray_distance(view.world_from_clip, view.world_position, ndc, z, cs.slab.w);
}

fn key_at_reduced(p: vec2<i32>, dims: vec2<i32>, scale: f32) -> f32 {
    let q = vec2<i32>(march_pixel(p, scale, dims));
    return key_at(q, dims);
}

@fragment
fn fs_composite(in: FullscreenVertexOutput) -> @location(0) vec4<f32> {
    let p = vec2<i32>(in.position.xy);
    let source = textureLoad(scene, p, 0);
    let dims = vec2<i32>(textureDimensions(depth));
    let key = key_at(p, dims);
    // Bilinear footprint in the reduced grid, each tap weighted by depth agreement with
    // the full-resolution pixel the march read for it.
    let half_dims = vec2<i32>(textureDimensions(clouds));
    let scale = cs.counts.z;
    // Centres, rather than corners, are shared with fs_march. This also behaves
    // correctly when the full extent is not an exact multiple of the divisor.
    let h = (vec2<f32>(p) + 0.5) / scale - 0.5;
    let base = vec2<i32>(floor(h));
    let f = h - floor(h);
    let tolerance = 0.05 * key + 1.0;
    var sum = vec4<f32>(0.0);
    var weight = 0.0;
    var nearest = vec4<f32>(0.0);
    var nearest_delta = 1e30;
    for (var j = 0; j <= 1; j += 1) {
        for (var i = 0; i <= 1; i += 1) {
            let q = clamp(base + vec2<i32>(i, j), vec2<i32>(0), half_dims - vec2<i32>(1));
            let bilinear = select(1.0 - f.x, f.x, i == 1) * select(1.0 - f.y, f.y, j == 1);
            let guide = key_at_reduced(q, dims, scale);
            let delta = abs(guide - key);
            if (delta < nearest_delta) {
                nearest_delta = delta;
                nearest = textureLoad(clouds, q, 0);
            }
            let compatible = delta <= tolerance;
            var w = 0.0;
            if (compatible) {
                w = bilinear * exp(-abs(guide - key) / tolerance);
            }
            sum += textureLoad(clouds, q, 0) * w;
            weight += w;
        }
    }
    // iNilla: incompatible depth guides contribute exactly zero; a fully rejected
    // footprint leaves the scene untouched rather than adding an epsilon leak.
    // iNilla: a reduced ray can straddle a bridge edge; keep its nearest cloud
    // sample instead of erasing the whole footprint when all four guides reject.
    var c = nearest;
    if (weight > 0.0001) {
        c = sum / weight;
    }
    if (cs.lane.w > 0.5) {
        return vec4<f32>(c.rgb, source.a);
    }
    return vec4<f32>(source.rgb * c.a + c.rgb, source.a);
}

#endif
