//! The mountable MPQs of a `Data` folder, one name per line — the one rule, for the shell.
//!
//! `android.sh` needs the list to pack an XAPK: a glob picks up `base.MPQ` and `backup.MPQ`,
//! which `benilla-formats`' chain never mounts, and the player then carries 21 MB of archives the
//! client will not open. This example is the shell's door onto [`inilla_core::data`], the same
//! module the iOS launcher and the editors read.
//!
//! ```sh
//! cargo run -q -p inilla-core --example data-list -- <Data folder>
//! ```

fn main() {
    let Some(dir) = std::env::args().nth(1) else {
        eprintln!("usage: data-list <Data folder>");
        std::process::exit(2);
    };
    let status = inilla_core::data::status(std::path::Path::new(&dir));
    if status.present.is_empty() {
        eprintln!("no mountable MPQ in {dir}");
        std::process::exit(1);
    }
    if !status.missing_required.is_empty() {
        eprintln!("missing required: {}", status.missing_required.join(", "));
        std::process::exit(1);
    }
    for (name, _) in &status.present {
        println!("{name}");
    }
}
