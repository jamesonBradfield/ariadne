#[test]
fn test_take_damage_mitigation() {
    let mut entity = Entity::new();
    entity.take_damage(100.0);
    assert!(entity.health < 100.0);
}

#[test]
fn test_take_damage_death_state() {
    let mut entity = Entity::new();
    entity.take_damage(200.0);
    assert!(entity.is_dead);
}