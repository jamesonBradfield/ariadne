use godot::{
    classes::{
        rendering_server::MultimeshTransformFormat, Image, Node3D, QuadMesh, RenderingServer,
    },
    prelude::*,
};

#[derive(GodotClass)]
#[class(base=Node3D)]
pub struct MassRenderingNode {
    base: Base<Node3D>,
    #[export]
    visible_count: i32,
    multimesh: Rid,
    multimesh_instance: Option<Rid>,
    #[export]
    mesh: Option<Gd<QuadMesh>>,
    #[export]
    depth_buffers: Array<Gd<Image>>,
}

#[godot_api]
impl INode3D for MassRenderingNode {
    fn init(base: Base<Node3D>) -> Self {
        let multimesh: Rid = RenderingServer::singleton().multimesh_create();
        Self {
            base,
            visible_count: 0,
            multimesh,
            multimesh_instance: None,
            mesh: None,
            depth_buffers: Array::new(),
        }
    }
}

#[godot_api]
impl MassRenderingNode {
    #[func]
    pub fn setup_multimesh(&self) {
        //validation...
        if self.multimesh_instance.is_some() {
            godot_warn!("Multimesh already initialized!");
            return;
        }
        let Some(world) = self.base().get_world_3d() else {
            godot_warn!("Failed to get world_3d");
            return;
        };
        let Some(ref mesh) = self.mesh else {
            godot_warn!("mesh NOT set!");
            return;
        };
        if self.visible_count <= 0 {
            godot_warn!("visible_count NOT set!");
            return;
        }
        let mut rs = RenderingServer::singleton();
        rs.multimesh_set_mesh(self.multimesh, mesh.get_rid());
        rs.multimesh_allocate_data(
            self.multimesh,
            self.visible_count,
            MultimeshTransformFormat::TRANSFORM_3D,
        );
        let instance = rs.instance_create();
        rs.instance_set_scenario(instance, world.get_scenario());
        rs.instance_set_base(instance, self.multimesh);
        rs.instance_set_visible(instance, true);
        self.multimesh_instance = Some(instance);
    }

    /// Original loop-based method - simple but slower for large counts
    #[func]
    pub fn draw_transforms(&mut self, transforms: Vec<Transform3D>) {
        if transforms.len() != self.visible_count as usize {
            godot_error!("your visible_count doesn't equal the length of your array");
            return;
        }
        let mut rs = RenderingServer::singleton();
        for i in 0..self.visible_count {
            rs.multimesh_instance_set_transform(self.multimesh, i, transforms[i as usize]);
        }
    }

    /// Batched buffer-based method - much faster for large instance counts
    #[func]
    pub fn draw_transforms_batched(&mut self, transforms: Vec<Transform3D>) {
        if transforms.len() != self.visible_count as usize {
            godot_error!("your visible_count doesn't equal the length of your array");
            return;
        }

        // Build buffer with correct row-major order
        // Pre-allocate the exact size to avoid reallocation
        let mut floats = Vec::with_capacity(transforms.len() * 12);

        for transform in transforms.iter() {
            let basis = transform.basis;
            let origin = transform.origin;

            // We extend from a fixed-size array which is better optimized
            // than individual push calls (often vectorizes well)
            floats.extend([
                basis.rows[0].x,
                basis.rows[1].x,
                basis.rows[2].x,
                origin.x,
                basis.rows[0].y,
                basis.rows[1].y,
                basis.rows[2].y,
                origin.y,
                basis.rows[0].z,
                basis.rows[1].z,
                basis.rows[2].z,
                origin.z,
            ]);
        }

        // Set the entire buffer at once
        let mut rs = RenderingServer::singleton();
        let buffer = PackedFloat32Array::from(floats.as_slice());
        rs.multimesh_set_buffer(self.multimesh, &buffer);
    }
}

impl Drop for MassRenderingNode {
    fn drop(&mut self) {
        let mut rs = RenderingServer::singleton();
        if let Some(instance) = self.multimesh_instance {
            rs.free_rid(instance);
        }
        rs.free_rid(self.multimesh);
    }
}
