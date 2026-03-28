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
    self.dead = self.health <= 0.0;
}
}

fn main() {
    let mut entity = Entity::new();
    println!("Entity created with {} health.", entity.health);
}


#[test]
fn test_initial_state() {
    let mut entity = Entity::new();
    assert_eq!(entity.health, 100.0);
    assert_eq!(entity.armor, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_damage_reduction() {
    let mut entity = Entity::new();
    entity.take_damage(50.0);
    assert_eq!(entity.health, 66.66666666666667);
    assert!(!entity.is_dead);
}

#[test]
fn test_death_state() {
    let mut entity = Entity::new();
    entity.take_damage(150.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}

#[test]
fn test_negative_health() {
    let mut entity = Entity::new();
    entity.take_damage(200.0);
    assert_eq!(entity.health, -33.333333333333336);
    assert!(entity.is_dead);
}