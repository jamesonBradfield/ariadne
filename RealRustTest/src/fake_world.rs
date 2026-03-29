use crate::realtime_probe::RealtimeProbe;
use godot::classes::{
    geometry_instance_3d::ShadowCastingSetting,
    image::Format,
    Camera3D,
    Cubemap,
    IMeshInstance3D,
    Image,
    ImageTexture,
    Material,
    MeshInstance3D,
    Node3D,
    RenderingServer,
    Shader,
    ShaderMaterial,
    Texture2D,
};
use godot::prelude::*;

#[derive(GodotClass)]
#[class(base=MeshInstance3D)]
pub struct FakeWorld {
    #[export]
    probe: Option<Gd<Node3D>>,

    #[export]
    initial_palette: Option<Gd<Texture2D>>,

    player_camera: Option<Gd<Camera3D>>,
    cubemap: Option<Gd<Cubemap>>,
    material: Option<Gd<ShaderMaterial>>,
    pal: Option<Gd<Texture2D>>,

    base: Base<MeshInstance3D>,
}

#[godot_api]
impl IMeshInstance3D for FakeWorld {
    fn init(base: Base<MeshInstance3D>) -> Self {
        Self {
            probe: None,
            initial_palette: None,
            player_camera: None,
            cubemap: None,
            material: None,
            pal: None,
            base,
        }
    }

    fn ready(&mut self) {
        self.base_mut()
            .set_cast_shadows_setting(ShadowCastingSetting::OFF);

        let mut tree = self.base().get_tree().unwrap();

        // Use string literals directly; gdext handles the AsArg<StringName> conversion automatically
        let cameras = tree.get_nodes_in_group("player_cameras");
        if !cameras.is_empty() {
            self.player_camera = cameras.at(0).try_cast::<Camera3D>().ok();
        }

        if let Some(render_mgr) = self.base().get_node_or_null("/root/RenderManager") {
            let settings_variant = render_mgr.get("settings");
            if !settings_variant.is_nil() {
                if let Ok(settings) = settings_variant.try_to::<Gd<Object>>() {
                    let mask = settings.get("fake_world_mask").try_to::<u32>().unwrap_or(1);
                    self.base_mut().set_layer_mask(mask);
                }
            }
        }

        // Create material if it doesn't exist
        if self.material.is_none() {
            self.material = Some(ShaderMaterial::new_gd());
            godot_print!("FakeWorld: Created new ShaderMaterial");
        }

        if let Some(shader) = godot::classes::ResourceLoader::singleton()
            .load("res://Shaders/fake_world.gdshader")
            .map(|res| res.cast::<Shader>())
        {
            let mut mat = self.material.as_ref().unwrap().clone();
            mat.set_shader(&shader);

            if let Some(palette) = &self.pal {
                mat.set_shader_parameter("palette", &palette.to_variant());
            }
            mat.set_shader_parameter("env_cubemap", &Rid::Invalid.to_variant());

            // Set material override on the MeshInstance3D itself (self.base())
            self.base_mut().set_material_override(&mat.upcast::<Material>());
            // Note: We don't need to store the parent Node3D here
            // The parent_node field is unused and can be removed if needed
        } else {
            godot_error!("FakeWorld: Failed to load shader from res://Shaders/fake_world.gdshader");
        }
        // Connect to the probe_updated signal using typed signal API
        // The signal is declared in RealtimeProbe and emits: Array<Gd<Image>>, Array<Gd<Image>>, Rid
        // For typed signals, pass ByRef types (Array, Gd<T>) by reference, ByValue types (Rid) by value
        if let Some(probe_node) = self.probe.as_ref().cloned() {
            if let Ok(mut probe) = probe_node.try_cast::<RealtimeProbe>() {
                let callable = self.base().callable("_on_probe_cycle_complete");
                probe.connect("probe_updated", &callable);
                godot_print!("FakeWorld: Connected probe_updated signal to _on_probe_cycle_complete");
            } else {
                godot_warn!("FakeWorld: Probe is not a RealtimeProbe!");
            }
        } else {
            godot_warn!("FakeWorld: No probe assigned!");
        }
    }

    fn process(&mut self, _delta: f64) {
        if let Some(mut probe) = self.probe.clone() {
            probe.call("update_fake_world_position", &[]);
        }
    }
}

#[godot_api]
impl FakeWorld {
    #[func]
    fn _on_probe_cycle_complete(
        &mut self,
        _faces: Array<Gd<Image>>,
        _depth_faces: Array<Gd<Image>>,
        cubemap_rid: Rid,
    ) {
        godot_print!(
            "FakeWorld: Received probe_updated signal with cubemap RID: {:?}",
            cubemap_rid
        );

        // Pass the cubemap RID directly to the shader
        if let Some(ref mut mat) = self.material {
            // Set the shader parameter directly on the stored material
            mat.set_shader_parameter("env_cubemap", &cubemap_rid.to_variant());

            // Verify the shader parameter was set correctly
            let variant = mat.get_shader_parameter("env_cubemap");
            let rid_from_shader = variant.try_to::<Rid>().unwrap_or(Rid::Invalid);
            godot_print!(
                "FakeWorld: Verified env_cubemap shader parameter (RID: {:?})",
                rid_from_shader
            );

            if rid_from_shader == cubemap_rid {
                godot_print!("FakeWorld: Shader parameter matches received RID!");
            } else {
                godot_error!("FakeWorld: Shader parameter DOES NOT MATCH received RID!");
            }
        } else {
            godot_error!("FakeWorld: Material is None when trying to set shader parameter!");
        }
        godot_print!(
            "FakeWorld: env_cubemap shader parameter set (RID: {:?})",
            cubemap_rid
        );
    }

    #[func]
    fn set_palette(&mut self, palette_texture: Gd<Texture2D>) {
        self.initial_palette = Some(palette_texture.clone());
        self.pal = Some(palette_texture.clone());
        if let Some(mut mat) = self.material.clone() {
            mat.set_shader_parameter("palette", &palette_texture.to_variant());
            self.material = Some(mat);
        }
    }

    #[func]
    pub fn get_cubemap_rid(&self) -> Rid {
        // Returns the cubemap RID for debugging
        self.cubemap
            .as_ref()
            .map(|c| c.get_rid())
            .unwrap_or(Rid::Invalid)
    }

    #[func]
    pub fn generate_palette_from_image(&self, source_image: Gd<Image>) -> Gd<Texture2D> {
        let mut palette_image =
            Image::create(16, 1, false, Format::RGBA8).expect("Failed to create palette Image");
        let mut sampled_colors: Vec<Color> = Vec::new();

        let width = source_image.get_width();
        let height = source_image.get_height();

        'outer: for y in 0..height {
            for x in 0..width {
                let color = source_image.get_pixel(x, y);

                let r = (color.r * 15.0).trunc() / 15.0;
                let g = (color.g * 15.0).trunc() / 15.0;
                let b = (color.b * 15.0).trunc() / 15.0;
                let quantized_color = Color::from_rgba(r, g, b, 1.0);

                let mut already_added = false;
                for existing in &sampled_colors {
                    let dr = existing.r - quantized_color.r;
                    let dg = existing.g - quantized_color.g;
                    let db = existing.b - quantized_color.b;
                    let dist = (dr * dr + dg * dg + db * db).sqrt();

                    if dist < 0.05 {
                        already_added = true;
                        break;
                    }
                }

                if !already_added {
                    sampled_colors.push(quantized_color);
                    if sampled_colors.len() >= 16 {
                        break 'outer;
                    }
                }
            }
        }

        for i in 0..16 {
            if i < sampled_colors.len() {
                palette_image.set_pixel(i as i32, 0, sampled_colors[i]);
            } else {
                palette_image.set_pixel(i as i32, 0, Color::from_rgba(1.0, 1.0, 1.0, 1.0));
            }
        }

        palette_image.generate_mipmaps();

        let tex =
            ImageTexture::create_from_image(&palette_image).expect("Failed to create ImageTexture");
        tex.upcast()
    }
}

impl Drop for FakeWorld {
    fn drop(&mut self) {
        // Clean up cubemap RID if it exists
        if let Some(ref cubemap) = self.cubemap {
            let rid = cubemap.get_rid();
            if !rid.is_invalid() {
                let mut rs = RenderingServer::singleton();
                rs.free_rid(rid);
                godot_print!("FakeWorld: Cleaned up cubemap RID: {:?}", rid);
            }
        }
    }
}
