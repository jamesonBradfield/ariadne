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
    let damage_after_reduction = damage - self.armor;
    self.health -= damage_after_reduction.max(0.0);
    self.is_dead = self.health <= 0.0;
}

    pub fn heal(&mut self, amount: f32) {
    self.health += amount;
    if self.health > self.max_health {
        self.health = self.max_health;
    }
}
}

fn main() {
    let mut entity = Entity::new();
    println!("Entity created with {} health.", entity.health);
}


#[test]
fn test_new() {
    let entity = Entity::new();
    assert_eq!(entity.health, 100.0);
    assert_eq!(entity.armor, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_heal() {
    let mut entity = Entity::new();
    entity.heal(50.0);
    assert_eq!(entity.health, 100.0);
}

#[test]
fn test_heal_small() {
    let mut entity = Entity::new();
    entity.heal(20.0);
    assert_eq!(entity.health, 100.0);
}

#[test]
fn test_take_damage_less_than_armor() {
    let mut entity = Entity::new();
    entity.take_damage(30.0);
    assert_eq!(entity.health, 100.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage_equal_to_armor() {
    let mut entity = Entity::new();
    entity.take_damage(50.0);
    assert_eq!(entity.health, 100.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage_more_than_armor() {
    let mut entity = Entity::new();
    entity.take_damage(150.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}

#[test]
fn test_take_damage_partial() {
    let mut entity = Entity::new();
    entity.take_damage(100.0);
    assert_eq!(