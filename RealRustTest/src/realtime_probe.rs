use godot::classes::{
    rendering_server::TextureLayeredType, Camera3D, INode3D, Image, Node3D, RenderingServer,
    ShaderMaterial, SubViewport,
};
use godot::prelude::*;

const FACE_RESOLUTION: i32 = 512;

#[derive(GodotClass)]
#[class(base=Node3D)]
pub struct RealtimeProbe {
    base: Base<Node3D>,

    #[export]
    cameras: Array<Gd<Camera3D>>,

    #[export]
    follow_node: Option<Gd<Node3D>>,

    #[export]
    fake_world_node: Option<Gd<Node3D>>,

    #[export]
    world_3d: Option<Gd<Node3D>>,

    #[export]
    material: Option<Gd<ShaderMaterial>>,

    #[export(range = (1.0, 1000.0, 0.01))]
    tick_rate_ms: f64,

    time_accumulator: f64,
    faces: Vec<Gd<Image>>,
    depth_faces: Vec<Gd<Image>>,

    /// Persistent GPU identifier for the cubemap
    cubemap_rid: Rid,
}

#[godot_api]
impl INode3D for RealtimeProbe {
    fn init(base: Base<Node3D>) -> Self {
        Self {
            base,
            cameras: Array::new(),
            follow_node: None,
            fake_world_node: None,
            world_3d: None,
            material: None,
            time_accumulator: 0.0,
            tick_rate_ms: 16.67,
            faces: Vec::with_capacity(6),
            depth_faces: Vec::with_capacity(6),
            cubemap_rid: Rid::Invalid,
        }
    }

    fn process(&mut self, delta: f64) {
        if let Some(target) = self.follow_node.clone() {
            let target_pos = target.get_global_position();
            self.base_mut().set_global_position(target_pos);
        }

        self.time_accumulator += delta * 1000.0;
        if self.time_accumulator >= self.tick_rate_ms {
            self.time_accumulator = 0.0;
            self.capture_environment();
        }
    }

    fn exit_tree(&mut self) {
        // Essential: Free the GPU memory when the node is removed
        if !self.cubemap_rid.is_invalid() {
            RenderingServer::singleton().free_rid(self.cubemap_rid);
            self.cubemap_rid = Rid::Invalid;
        }
    }
}

#[godot_api]
impl RealtimeProbe {
    #[signal]
    fn probe_updated(images: Array<Gd<Image>>, depth_images: Array<Gd<Image>>, cubemap_rid: Rid);

    #[func]
    pub fn connect_probe_updated_signal(&mut self, callable: Callable) {
        // Helper to connect the signal externally if needed
        self.base_mut().connect("probe_updated", &callable);
    }

    #[func]
    pub fn get_cubemap_rid(&self) -> Rid {
        self.cubemap_rid
    }

    #[func]
    pub fn spawn_cameras(&mut self) {
        if self.cameras.len() == 6 {
            godot_warn!("RealtimeProbe: Already have 6 cameras!");
            return;
        }
        self._spawn_cameras();
    }

    #[func]
    fn _spawn_cameras(&mut self) {
        let face_rotations = [
            Vector3::new(0.0, -90.0, 0.0), // +X (Right)
            Vector3::new(0.0, 90.0, 0.0),  // -X (Left)
            Vector3::new(90.0, 0.0, 0.0),  // +Y (Top)
            Vector3::new(-90.0, 0.0, 0.0), // -Y (Bottom)
            Vector3::new(0.0, 180.0, 0.0), // +Z (Back)
            Vector3::new(0.0, 0.0, 0.0),   // -Z (Front)
        ];

        let world = self.base().get_world_3d();

        for (i, &rotation) in face_rotations.iter().enumerate() {
            let mut vp_gd = SubViewport::new_alloc();
            vp_gd.set_name(&format!("FaceViewport_{}", i));
            vp_gd.set_size(Vector2i::new(FACE_RESOLUTION, FACE_RESOLUTION));
            vp_gd.set_update_mode(godot::classes::sub_viewport::UpdateMode::ONCE);

            if let Some(w) = &world {
                vp_gd.set_world_3d(w);
            }

            let mut cam_gd = Camera3D::new_alloc();
            cam_gd.set_name(&format!("FaceCamera_{}", i));
            cam_gd.set_fov(90.0);
            cam_gd.set_rotation_degrees(rotation);

            // Add camera to subviewport
            vp_gd.add_child(&cam_gd);
            // Add subviewport to the probe node
            self.base_mut().add_child(&vp_gd);

            // Clone camera for later use in capture
            self.cameras.push(&cam_gd.clone());
        }
    }

    #[func]
    fn capture_environment(&mut self) {
        if self.cameras.len() != 6 {
            godot_warn!("RealtimeProbe: Not all cameras ready for capture");
            return;
        }

        let origin = self.base().get_global_position();

        if let Some(mut fw) = self.fake_world_node.clone() {
            fw.set_global_position(origin);
        }

        let mut current_capture: Vec<Gd<Image>> = Vec::with_capacity(6);

        for i in 0..6 {
            let camera = self.cameras.at(i);
            // Positions cameras at the probe origin
            let mut cam_mut = camera.clone();
            cam_mut.set_global_position(origin);

            if let Some(vp) = camera
                .get_viewport()
                .and_then(|v| v.try_cast::<SubViewport>().ok())
            {
                if let Some(texture) = vp.get_texture() {
                    if let Some(image) = texture.get_image() {
                        // duplicate() creates a unique buffer so we can flip it safely
                        let mut img: Gd<Image> =
                            image.duplicate().expect("Failed to duplicate").cast();

                        // Correcting orientations for Godot Cubemap standards
                        if i != 3 {
                            img.flip_x();
                        } else {
                            img.flip_y();
                        }
                        current_capture.push(img);
                    }
                }
            }
        }

        if current_capture.len() == 6 {
            self.faces = current_capture;

            let mut rs = RenderingServer::singleton();

            if self.cubemap_rid.is_invalid() {
                let mut image_array = Array::<Gd<Image>>::new();
                for img in &self.faces {
                    image_array.push(img);
                }
                self.cubemap_rid =
                    rs.texture_2d_layered_create(&image_array, TextureLayeredType::CUBEMAP);
            } else {
                for (i, img) in self.faces.iter().enumerate() {
                    rs.texture_2d_update(self.cubemap_rid, img, i as i32);
                }
            }

            // Clone values before emit to avoid borrow checker issues
            let faces_array = self.get_faces_array();
            let depth_faces_array = self.get_depth_faces_array();
            let cubemap_rid = self.cubemap_rid;

            godot_print!(
                "RealtimeProbe: Emitting probe_updated signal with cubemap_rid: {:?}",
                cubemap_rid
            );
            // Typed signal emission - pass ByRef types by reference, ByValue types by value
            self.signals().probe_updated().emit(
                &faces_array,
                &depth_faces_array,
                cubemap_rid,
            );
        } else {
            godot_warn!("RealtimeProbe: Failed to capture all 6 faces");
        }

        // Update the fake world position after capture
        if let Some(mut fw) = self.fake_world_node.clone() {
            fw.call("update_fake_world_position", &[]);
        }

        // Set the cubemap as a shader parameter on the material
        if let Some(mut mat) = self.material.clone() {
            mat.set_shader_parameter("env_cubemap", &self.cubemap_rid.to_variant());
            self.material = Some(mat);
        }
    }

    #[func]
    pub fn get_faces_array(&self) -> Array<Gd<Image>> {
        self.faces.iter().cloned().collect()
    }

    #[func]
    pub fn get_depth_faces_array(&self) -> Array<Gd<Image>> {
        self.depth_faces.iter().cloned().collect()
    }
    /// Updates the fake_world_node's position to match the probe's current position.
    /// This maintains the holodeck illusion when rendering the cubemap projection.
    #[func]
    pub fn update_fake_world_position(&self) {
        if let Some(mut fw) = self.fake_world_node.clone() {
            let pos = self.base().get_global_position();
            fw.set_global_position(pos);
            godot_print!("RealtimeProbe: Updated fake world position to {:?}", pos);
        }
    }

    #[func]
    pub fn is_ready(&self) -> bool {
        self.cameras.len() == 6
    }

    #[func]
    pub fn capture_environment_once(&mut self) {
        if self.cameras.len() != 6 {
            godot_warn!("RealtimeProbe: Need 6 cameras before capturing");
            return;
        }

        self.capture_environment();
        let rid = self.get_cubemap_rid();
        godot_print!("RealtimeProbe: Capture complete, cubemap RID: {:?}", rid);
    }

    #[func]
    pub fn get_probe_updated_signal(&self) -> Callable {
        // Get the signal callable for external connections
        self.base().callable("probe_updated")
    }
}
