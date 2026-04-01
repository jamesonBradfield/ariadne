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
    entity.take_damage(100.0);
    assert_eq!(entity.health, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage_exceeds_health() {
    let mut entity = Entity::new();
    entity.take_damage(200.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}

#[test]
fn test_heal_after_death() {
    let mut entity = Entity::new();
    entity.take_damage(200.0);
    entity.heal(50.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}

#[test]
fn test_take_damage_no_armor() {
    let mut entity = Entity::new();
    entity.armor = 0.0;
    entity.take_damage(100.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}