// main.rs
use std::time::{SystemTime, UNIX_EPOCH};

struct Entity {
    health: f32,
    armor: f32,
    is_dead: bool,
}

impl Entity {
    pub fn new() -> Self {
        Self {
            health: 100.0,
            armor: 50.0,
            is_dead: false,
        }
    }

    pub fn take_damage(&mut self, damage: f32) {
    let armor_constant = 100.0;
    let mitigated_damage = damage * (1.0 - self.armor / (armor_constant + self.armor));
    self.health -= mitigated_damage;
    self.is_dead = self.health <= 0.0;
}
}

fn main() {
    let mut entity = Entity::new();
    println!("Entity created with {} health.", entity.health);
}
