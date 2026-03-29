use godot::prelude::*;

mod fake_world;
mod mass_render;
mod realtime_probe;
struct TexelSplatting;

#[gdextension]
unsafe impl ExtensionLibrary for TexelSplatting {}
