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
fn test_new_entity() {
    let entity = Entity::new();
    assert_eq!(entity.health, 100.0);
    assert_eq!(entity.armor, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage() {
    let mut entity = Entity::new();
    entity.take_damage(50.0);
    assert_eq!(entity.health, 50.0);
}

#[test]
fn test_heal() {
    let mut entity = Entity::new();
    entity.take_damage(60.0);
    entity.heal(20.0);
    assert_eq!(entity.health, 60.0);
}