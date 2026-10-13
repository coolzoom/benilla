//! Android: winit reports every pointer as a touch, a mouse included, and never moves the window's
//! cursor. The client is mouse-driven: a glue button clicks on `Interaction` `Pressed → Hovered`
//! (`glue::glue_clicks`), which a lifted finger, leaving no cursor to hover, never reaches. One
//! finger is replayed as the left button and the cursor, and stays where it lifted, as a mouse
//! does.
//!
//! With the touch interface up (`mobileInterface`, `MobileInterface.xml`) every finger is routed
//! where it lands: the stick (`BenillaMobileStick`) holds the four directions its drag points at,
//! as the movement keys' bindings do; the jump and autorun buttons fire their one-shots; a finger
//! on the open world turns the camera, and a second one there pinches the zoom; the rest is the
//! mouse finger. The stock movement functions refuse a call from Lua outside a binding body, so
//! the stick is driven here and not from its frame's scripts.
//!
//! The cursor is set for the frame and cleared in `PostUpdate`: bevy_winit warps the OS pointer to a
//! changed `Some` position, which Android refuses with an error every frame.

use bevy::input::mouse::{AccumulatedMouseMotion, MouseButtonInput};
use bevy::input::touch::{TouchInput, TouchPhase};
use bevy::input::{ButtonState, InputSystems};
use bevy::prelude::*;
use bevy::window::{CursorMoved, PrimaryWindow};

use benilla_ui::script::{FiredInput, UiScript};

use crate::bindings::{BindingsState, Input};

pub(crate) struct TouchMousePlugin;

impl Plugin for TouchMousePlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<TouchLook>()
            .add_systems(PreUpdate, touch_to_mouse.before(InputSystems))
            // After the accumulator, which would overwrite the world drag's motion.
            .add_systems(PreUpdate, add_touch_look.after(InputSystems))
            .add_systems(PostUpdate, clear_cursor);
    }
}

/// The stick's reach in root units, and the drag under which it holds nothing.
const STICK_RADIUS: f32 = 95.0;
const STICK_DEAD: f32 = 22.0;
/// A direction is held once it is within 67.5° of the drag.
const STICK_EDGE: f32 = 0.38;
/// Root units of finger travel per raw mouse unit the look session reads.
const LOOK_GAIN: f32 = 1.6;
/// Yards of zoom per root unit a pinch closes.
const PINCH_YARDS: f32 = 0.04;

/// The world drag's motion this frame, in raw mouse units, for the look session.
#[derive(Resource, Default)]
struct TouchLook(Vec2);

fn add_touch_look(mut look: ResMut<TouchLook>, mut motion: ResMut<AccumulatedMouseMotion>) {
    motion.delta += std::mem::take(&mut look.0);
}

/// What a finger is doing, decided where it landed.
#[derive(Clone, Copy, PartialEq, Debug)]
enum Role {
    Mouse,
    Stick,
    Look,
    /// A jump or autorun press: fired on landing, inert after.
    Button,
}

#[derive(Default)]
struct Pointer {
    /// The finger the mouse follows.
    finger: Option<u64>,
    at: Option<Vec2>,
    /// A tap that began and ended in one frame releases the next, so the press is seen first.
    release_next: bool,
    /// Every finger down and its role, last position in window pixels.
    roles: Vec<(u64, Role, Vec2)>,
    /// The stick's centre (root units), held from the press.
    stick_centre: Vec2,
    /// The two world fingers' last spread, for the pinch.
    pinch: Option<f32>,
    /// A `MouselookStart` holds the camera for a world drag.
    looking: bool,
}

/// The engine-hit regions of the touch interface, in root units.
#[derive(Default)]
struct Regions {
    stick: Option<benilla_ui::layout::Rect>,
    jump: Option<benilla_ui::layout::Rect>,
    autorun: Option<benilla_ui::layout::Rect>,
}

fn contains(r: &Option<benilla_ui::layout::Rect>, p: Vec2) -> bool {
    r.is_some_and(|r| p.x >= r.left && p.x <= r.right && p.y >= r.bottom && p.y <= r.top)
}

#[allow(clippy::too_many_arguments)]
fn touch_to_mouse(
    mut touches: MessageReader<TouchInput>,
    mut windows: Query<(Entity, &mut Window), With<PrimaryWindow>>,
    mut buttons: MessageWriter<MouseButtonInput>,
    mut moved: MessageWriter<CursorMoved>,
    mut pointer: Local<Pointer>,
    script: Option<NonSend<UiScript>>,
    mut binds: Option<ResMut<BindingsState>>,
    mut motion: ResMut<TouchLook>,
) {
    let Ok((window, mut win)) = windows.single_mut() else {
        return;
    };
    let height = win.height();
    let button = |state| MouseButtonInput {
        button: MouseButton::Left,
        state,
        window,
    };
    if std::mem::take(&mut pointer.release_next) {
        buttons.write(button(ButtonState::Released));
    }
    // The interface's regions, off the rects the last tick resolved; none in the stock layout.
    let regions = script
        .as_ref()
        .filter(|s| s.frame_visible("BenillaMobileHud"))
        .map(|s| Regions {
            stick: s.frame_rect("BenillaMobileStick"),
            jump: s.frame_rect("BenillaMobileJump"),
            autorun: s.frame_rect("BenillaMobileAutoRun"),
        });
    let mut pressed_now = false;
    let mut look = Vec2::ZERO;
    for touch in touches.read() {
        let ui = crate::ui_script::window_to_ui(height, touch.position);
        let known = pointer.roles.iter().position(|r| r.0 == touch.id);
        if touch.phase == TouchPhase::Started && known.is_none() {
            let role = match &regions {
                Some(r) if contains(&r.stick, ui) => {
                    let s = r.stick.expect("hit");
                    pointer.stick_centre =
                        Vec2::new((s.left + s.right) / 2.0, (s.bottom + s.top) / 2.0);
                    Role::Stick
                }
                Some(r) if contains(&r.jump, ui) || contains(&r.autorun, ui) => {
                    if let Some(b) = binds.as_mut() {
                        b.fire_touch(if contains(&r.jump, ui) {
                            FiredInput::Jump
                        } else {
                            FiredInput::ToggleAutoRun
                        });
                    }
                    Role::Button
                }
                // The open world: a hit on no frame, or the world frame. A busy mouse finger
                // leaves a second finger to the camera too.
                Some(_)
                    if pointer.finger.is_some()
                        || script.as_ref().is_some_and(|s| {
                            s.hit_test(ui.x, ui.y)
                                .is_none_or(|id| s.is_world_frame(id))
                        }) =>
                {
                    Role::Look
                }
                _ => Role::Mouse,
            };
            pointer.roles.push((touch.id, role, touch.position));
            if role == Role::Look {
                pointer.pinch = None;
            }
        }
        let Some(i) = pointer.roles.iter().position(|r| r.0 == touch.id) else {
            continue;
        };
        let (_, role, last) = pointer.roles[i];
        pointer.roles[i].2 = touch.position;
        let ended = matches!(touch.phase, TouchPhase::Ended | TouchPhase::Canceled);
        match role {
            Role::Stick => {
                let want = if ended {
                    Vec::new()
                } else {
                    stick_dirs(ui - pointer.stick_centre)
                };
                if let Some(b) = binds.as_mut() {
                    b.set_touch_moves(&want);
                }
                if let Some(s) = script.as_ref() {
                    let d = if ended {
                        Vec2::ZERO
                    } else {
                        (ui - pointer.stick_centre).clamp_length_max(STICK_RADIUS)
                    };
                    let _ = s.run(&format!(
                        "if BenillaMobileStick_SetKnob then BenillaMobileStick_SetKnob({}, {}) end",
                        d.x, d.y
                    ));
                }
            }
            Role::Look => {
                let looks = pointer.roles.iter().filter(|r| r.1 == Role::Look).count();
                if looks >= 2 {
                    let mut fingers = pointer
                        .roles
                        .iter()
                        .filter(|r| r.1 == Role::Look)
                        .map(|r| r.2);
                    let (a, b) = (fingers.next(), fingers.next());
                    if let (Some(a), Some(b)) = (a, b) {
                        let spread = a.distance(b) / crate::ui_script::seam_scale(height);
                        if let (Some(was), Some(binds)) = (pointer.pinch, binds.as_mut()) {
                            let yards = (spread - was) * PINCH_YARDS;
                            if yards > 0.0 {
                                binds.fire_touch(FiredInput::CameraZoomIn(yards));
                            } else if yards < 0.0 {
                                binds.fire_touch(FiredInput::CameraZoomOut(-yards));
                            }
                        }
                        pointer.pinch = Some(spread);
                    }
                } else if touch.phase == TouchPhase::Moved {
                    look += (touch.position - last) * LOOK_GAIN;
                }
            }
            Role::Button => {}
            Role::Mouse => {
                let delta = pointer.at.map(|at| touch.position - at);
                pointer.at = Some(touch.position);
                moved.write(CursorMoved {
                    window,
                    position: touch.position,
                    delta,
                });
                match touch.phase {
                    TouchPhase::Started => {
                        pointer.finger = Some(touch.id);
                        pressed_now = true;
                        buttons.write(button(ButtonState::Pressed));
                    }
                    TouchPhase::Moved => {}
                    TouchPhase::Ended | TouchPhase::Canceled => {
                        pointer.finger = None;
                        if pressed_now {
                            pointer.release_next = true;
                        } else {
                            buttons.write(button(ButtonState::Released));
                        }
                    }
                }
            }
        }
        if ended {
            pointer.roles.remove(i);
            pointer.pinch = None;
        }
    }
    // A world drag turns the camera as a right-drag does: `MouselookStart`, which has no
    // binding gate, holds the look session, and the drag is its motion.
    let looking = pointer.roles.iter().filter(|r| r.1 == Role::Look).count() == 1;
    if looking != pointer.looking {
        pointer.looking = looking;
        if let Some(s) = script.as_ref() {
            let _ = s.run(if looking { "MouselookStart()" } else { "MouselookStop()" });
        }
    }
    motion.0 += look;
    if pointer.at.is_some() {
        win.set_cursor_position(pointer.at);
    }
}

/// The directions a stick drag `d` (root units, y up) holds.
fn stick_dirs(d: Vec2) -> Vec<Input> {
    let length = d.length();
    let mut want = Vec::new();
    if length < STICK_DEAD {
        return want;
    }
    let edge = STICK_EDGE * length;
    if d.y > edge {
        want.push(Input::MoveForward);
    }
    if d.y < -edge {
        want.push(Input::MoveBackward);
    }
    if d.x > edge {
        want.push(Input::StrafeRight);
    }
    if d.x < -edge {
        want.push(Input::StrafeLeft);
    }
    want
}

fn clear_cursor(mut windows: Query<&mut Window, With<PrimaryWindow>>) {
    for mut win in &mut windows {
        if win.physical_cursor_position().is_some() {
            win.set_cursor_position(None);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_stick_holds_what_its_drag_points_at() {
        assert!(stick_dirs(Vec2::new(5.0, 10.0)).is_empty(), "inside the dead zone");
        assert_eq!(stick_dirs(Vec2::new(0.0, 80.0)), vec![Input::MoveForward]);
        assert_eq!(
            stick_dirs(Vec2::new(-60.0, -60.0)),
            vec![Input::MoveBackward, Input::StrafeLeft]
        );
        assert_eq!(stick_dirs(Vec2::new(90.0, 10.0)), vec![Input::StrafeRight]);
    }
}
