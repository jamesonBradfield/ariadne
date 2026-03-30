pub struct Entity {
    pub health: f32,
    pub armor: f32,
    pub is_dead: bool,
}

impl Entity {
    pub fn new() -> Self {
        Self { health: 100.0, armor: 50.0, is_dead: false }
    }
    pub fn take_damage(&mut self, damage: f32) {
        self.health -= damage;
    }
}


#[test]
fn test_armor_mitigation_and_death() {
    let mut entity = Entity::new();
    entity.take_damage(100.0);
    assert_eq!(entity.health, 50.0);
    assert!(!entity.is_dead);
    
    entity.take_damage(100.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}
