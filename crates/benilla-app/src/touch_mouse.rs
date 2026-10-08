//! Android: winit reports every pointer as a touch, a mouse included, and never moves the window's
//! cursor. The client is mouse-driven: a glue button clicks on `Interaction` `Pressed → Hovered`
//! (`glue::glue_clicks`), which a lifted finger, leaving no cursor to hover, never reaches. The
//! first finger is replayed as the left button and the cursor, and stays where it lifted, as a
//! mouse does.
//!
//! The cursor is set for the frame and cleared in `PostUpdate`: bevy_winit warps the OS pointer to a
//! changed `Some` position, which Android refuses with an error every frame.

use bevy::input::mouse::MouseButtonInput;
use bevy::input::touch::{TouchInput, TouchPhase};
use bevy::input::{ButtonState, InputSystems};
use bevy::prelude::*;
use bevy::window::{CursorMoved, PrimaryWindow};

pub(crate) struct TouchMousePlugin;

impl Plugin for TouchMousePlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(PreUpdate, touch_to_mouse.before(InputSystems))
            .add_systems(PostUpdate, clear_cursor);
    }
}

#[derive(Default)]
struct Pointer {
    finger: Option<u64>,
    at: Option<Vec2>,
    /// A tap that began and ended in one frame releases the next, so the press is seen first.
    release_next: bool,
}

fn touch_to_mouse(
    mut touches: MessageReader<TouchInput>,
    mut windows: Query<(Entity, &mut Window), With<PrimaryWindow>>,
    mut buttons: MessageWriter<MouseButtonInput>,
    mut moved: MessageWriter<CursorMoved>,
    mut pointer: Local<Pointer>,
) {
    let Ok((window, mut win)) = windows.single_mut() else {
        return;
    };
    let button = |state| MouseButtonInput {
        button: MouseButton::Left,
        state,
        window,
    };
    if std::mem::take(&mut pointer.release_next) {
        buttons.write(button(ButtonState::Released));
    }
    let mut pressed_now = false;
    for touch in touches.read() {
        if pointer.finger.is_some_and(|f| f != touch.id) {
            continue;
        }
        if pointer.finger.is_none() && touch.phase != TouchPhase::Started {
            continue;
        }
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
    if pointer.at.is_some() {
        win.set_cursor_position(pointer.at);
    }
}

fn clear_cursor(mut windows: Query<&mut Window, With<PrimaryWindow>>) {
    for mut win in &mut windows {
        if win.physical_cursor_position().is_some() {
            win.set_cursor_position(None);
        }
    }
}
