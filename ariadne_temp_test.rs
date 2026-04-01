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
fn test_take_damage_with_armor_mitigation() {
    let mut entity = Entity::new();
    let damage = 100.0;
    let armor_value = 20.0;
    let mitigation = entity.take_damage(damage, armor_value);
    assert!(mitigation < damage);
}

#[test]
fn test_take_damage_transition_to_death() {
    let mut entity = Entity::new();
    let damage = 1000.0;
    let armor_value = 0.0;
    entity.take_damage(damage, armor_value);
    assert!(entity.is_dead());
}

#[test]
fn test_take_damage_no_armor() {
    let mut entity = Entity::new();
    let damage = 50.0;
    let armor_value = 0.0;
    let mitigation = entity.take_damage(damage, armor_value);
    assert_eq!(mitigation, damage);
}