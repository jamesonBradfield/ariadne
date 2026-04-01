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
        self.health -= damage;
    }

    pub fn heal(&mut self, amount: f32) {
        self.health += amount;
    }
}


#[test]
fn test_take_damage_with_armor() {
    let mut entity = Entity::new();
    entity.take_damage(30.0);
    assert_eq!(entity.health, 70.0);
}

#[test]
fn test_take_damage_exceeds_health() {
    let mut entity = Entity::new();
    entity.take_damage(200.0);
    assert_eq!(entity.health, -100.0);
}

#[test]
fn test_heal_after_damage() {
    let mut entity = Entity::new();
    entity.take_damage(30.0);
    entity.heal(20.0);
    assert_eq!(entity.health, 90.0);
}

#[test]
fn test_heal_over_max_health() {
    let mut entity = Entity::new();
    entity.heal(100.0);
    assert_eq!(entity.health, 150.0);
}